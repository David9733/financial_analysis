"""환율·금리 시계열 정제와 주식 거래일 기준 병합.

기준 달력은 주식 거래일이다. 주가 표에 매크로 값을 왼쪽 기준으로 붙이고,
주가는 있는데 매크로가 빈 날만 직전 관측값으로 채운다(ffill). 직전 값이 없는
첫 구간만 다음 값으로 채운다(bfill). 주가가 없는 날(예: 해외만 열린 날)은
행으로 들어오지 않으므로 수익률 계산이 틀어지지 않는다.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

if __package__:
    from .data_quality import (
        ACTION_BFILL,
        ACTION_FFILL,
        ACTION_OUTLIER,
        QualityLog,
        correct_scale_errors,
        daily_change,
        flag_change_outliers,
        iqr_bounds,
        pair_valid,
    )
else:
    from data_quality import (
        ACTION_BFILL,
        ACTION_FFILL,
        ACTION_OUTLIER,
        QualityLog,
        correct_scale_errors,
        daily_change,
        flag_change_outliers,
        iqr_bounds,
        pair_valid,
    )


FX_COLUMN = "원달러환율"
RATE_COLUMN = "국고채3년"
FX_FILLED_COLUMN = "환율보간"
RATE_FILLED_COLUMN = "금리보간"
PRICE_OUTLIER_COLUMN = "종가이상치"
FX_OUTLIER_COLUMN = "환율이상치"
RATE_OUTLIER_COLUMN = "금리이상치"
# 분석에는 값(수준) 대신 하루에 얼마나 움직였는지를 쓴다.
# 종가·환율은 변화율(오늘 ÷ 어제 − 1), 금리는 이미 %이므로 변화폭(오늘 − 어제).
PRICE_CHANGE_COLUMN = "종가등락률(%)"
FX_CHANGE_COLUMN = "환율변화율(%)"
RATE_CHANGE_PP_COLUMN = "금리변화폭(%p)"
RATE_CHANGE_BP_COLUMN = "금리변화폭(bp)"  # 1bp = 0.01%p
MACRO_SERIES = (
    (FX_COLUMN, FX_FILLED_COLUMN),
    (RATE_COLUMN, RATE_FILLED_COLUMN),
)
# (값 열, 하루 변화 열, 변화 방식, 보간 열, 이상치 열, 로그 대상명, 변화 단위)
CHANGE_SERIES = (
    ("종가", PRICE_CHANGE_COLUMN, "pct", None, PRICE_OUTLIER_COLUMN, "종가", "%"),
    (FX_COLUMN, FX_CHANGE_COLUMN, "pct", FX_FILLED_COLUMN, FX_OUTLIER_COLUMN, "원달러환율", "%"),
    (RATE_COLUMN, RATE_CHANGE_PP_COLUMN, "diff", RATE_FILLED_COLUMN, RATE_OUTLIER_COLUMN, "국고채3년", "%p"),
)
CHANGE_DIGITS = 4
BP_DIGITS = 2
# 주가 시작일 이전 값을 ffill 시드로 쓰기 위해 앞당겨 조회하는 기간
MACRO_LOOKBACK_DAYS = 10
# 이 기간보다 오래된 값은 직전 값으로 채우지 않는다(장기 수집 실패 방지).
MAX_FILL_DAYS = 10

MARKET_MACRO_COLUMNS = [
    "기업명",
    "종목코드",
    "기준일",
    "종가",
    PRICE_CHANGE_COLUMN,
    PRICE_OUTLIER_COLUMN,
    FX_COLUMN,
    FX_CHANGE_COLUMN,
    FX_FILLED_COLUMN,
    FX_OUTLIER_COLUMN,
    RATE_COLUMN,
    RATE_CHANGE_PP_COLUMN,
    RATE_CHANGE_BP_COLUMN,
    RATE_FILLED_COLUMN,
    RATE_OUTLIER_COLUMN,
]


def prepare_macro_series(rows: list[tuple[date, float]], column: str) -> pd.DataFrame:
    """(날짜, 값) 목록을 날짜 오름차순·중복 제거된 데이터프레임으로 만든다."""
    if not rows:
        return pd.DataFrame({"기준일": pd.Series(dtype="datetime64[ns]"), column: pd.Series(dtype="float64")})
    data = pd.DataFrame(rows, columns=["기준일", column])
    data["기준일"] = pd.to_datetime(data["기준일"], errors="coerce")
    data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=["기준일", column])
    data = data.sort_values("기준일").drop_duplicates("기준일", keep="last")
    return data.reset_index(drop=True)


def _attach_series(
    base: pd.DataFrame,
    series: pd.DataFrame,
    column: str,
    flag: str,
    log: QualityLog | None,
    company: str,
) -> None:
    """거래일 행에 매크로 값을 붙이고 빈 날만 직전 값(첫 구간은 다음 값)으로 채운다."""
    if series.empty:
        base[column] = float("nan")
        base[flag] = False
        return
    series = series.sort_values("기준일")
    exact = base[["기준일"]].merge(series, on="기준일", how="left")
    observed = exact[column].notna().to_numpy()
    # merge_asof(backward)는 각 거래일 이전의 가장 최근 관측값만 사용하므로
    # 미래 값이 섞이지 않는다. 결과 행은 항상 base(거래일)와 같다.
    filled = pd.merge_asof(
        base[["기준일"]],
        series,
        on="기준일",
        direction="backward",
        tolerance=pd.Timedelta(days=MAX_FILL_DAYS),
    )
    values = filled[column].copy()
    ffilled = (~observed) & values.notna().to_numpy()

    # 직전 값이 아예 없는 첫 구간만 다음 값으로 채운다. 중간 공백은 그대로 둔다.
    bfilled = pd.Series(False, index=values.index)
    first_valid = values.first_valid_index()
    if first_valid is not None and first_valid > 0:
        values.iloc[:first_valid] = values.iloc[first_valid]
        bfilled.iloc[:first_valid] = True

    base[column] = values.to_numpy()
    base[flag] = ffilled | bfilled.to_numpy()

    if log is not None:
        for position in range(len(base)):
            if bfilled.iloc[position]:
                action, reason = ACTION_BFILL, "첫 거래일 이전 관측값 없음 → 다음 값으로 채움"
            elif ffilled[position]:
                action, reason = ACTION_FFILL, "휴장, 미고시 또는 수집 실패 → 직전 값으로 채움"
            else:
                continue
            log.add(column, base.at[position, "기준일"], action, None, base.at[position, column], reason, company)


def _add_daily_changes(base: pd.DataFrame) -> None:
    """기업별 거래일 순서로 하루 변화 열을 만든다. 첫 거래일은 어제가 없어 빈 값이다."""
    for column, change_column, kind, *_ in CHANGE_SERIES:
        base[change_column] = daily_change(base[column], kind).round(CHANGE_DIGITS)
    base[RATE_CHANGE_BP_COLUMN] = (base[RATE_CHANGE_PP_COLUMN] * 100).round(BP_DIGITS)


def _flag_outliers(base: pd.DataFrame, log: QualityLog | None, company: str) -> None:
    """하루 변화가 IQR 범위를 벗어난 날을 표시만 하고 값은 그대로 둔다."""
    for column, change_column, _, filled_column, outlier_column, target, unit in CHANGE_SERIES:
        changes = base[change_column]
        filled = (
            base[filled_column]
            if filled_column is not None
            else pd.Series(False, index=base.index)
        )
        valid = pair_valid(filled)
        flags = flag_change_outliers(changes, valid)
        base[outlier_column] = flags.to_numpy()
        if log is None or not flags.any():
            continue
        lower, upper = iqr_bounds(changes, valid)
        for position in flags[flags].index:
            log.add(
                target,
                base.at[position, "기준일"],
                ACTION_OUTLIER,
                base.at[position, column],
                base.at[position, column],
                f"하루 변화 {changes.iloc[position]:+.3f}{unit}가 IQR 범위"
                f"({lower:+.3f}~{upper:+.3f}{unit}) 밖 — 값은 유지, 원인 확인 필요",
                company,
            )


def merge_macro_with_prices(
    prices: pd.DataFrame,
    fx: pd.DataFrame | None = None,
    rate: pd.DataFrame | None = None,
    log: QualityLog | None = None,
) -> pd.DataFrame:
    """기업별 주가 거래일에 환율·금리를 left join + ffill로 맞추고 이상치를 표시한다."""
    if prices.empty:
        return pd.DataFrame(columns=MARKET_MACRO_COLUMNS)

    sources = {
        FX_COLUMN: fx if fx is not None else prepare_macro_series([], FX_COLUMN),
        RATE_COLUMN: rate if rate is not None else prepare_macro_series([], RATE_COLUMN),
    }
    # 원천 시리즈 단계에서 소수점·단위 오류를 한 번만 보정한다.
    for column in list(sources):
        if not sources[column].empty:
            sources[column], _ = correct_scale_errors(
                sources[column], column, log, target=column
            )

    frames = []
    for (company_name, stock_code), group in prices.groupby(["기업명", "종목코드"], sort=False):
        base = (
            group[["기업명", "종목코드", "기준일", "종가"]]
            .sort_values("기준일")
            .reset_index(drop=True)
        )
        for column, flag in MACRO_SERIES:
            _attach_series(base, sources[column], column, flag, log, company_name)
        _add_daily_changes(base)
        _flag_outliers(base, log, company_name)

        if len(base) != len(group):
            raise ValueError(
                f"{company_name}: 병합 후 행 수({len(base)})가 주식 거래일 수({len(group)})와 다릅니다."
            )
        if not base["기준일"].is_monotonic_increasing or base["기준일"].duplicated().any():
            raise ValueError(f"{company_name}: 병합 결과의 날짜 순서가 올바르지 않습니다.")
        frames.append(base)

    merged = pd.concat(frames, ignore_index=True)
    if len(merged) != len(prices):
        raise ValueError("환율과 금리 병합 후 전체 행 수가 주식 거래일 수와 다릅니다.")
    return merged[MARKET_MACRO_COLUMNS]
