"""주식시세 정제, 요약과 비교 지표 계산."""

from __future__ import annotations

import pandas as pd


MOVING_AVERAGE_WINDOWS = (5, 20, 60)
BOLLINGER_WINDOW = 20
BOLLINGER_STD_MULTIPLIER = 2


STOCK_PRICE_COLUMNS = [
    "기업명",
    "종목코드",
    "기준일",
    "시장구분",
    "종가",
    "시가",
    "고가",
    "저가",
    "거래량",
    "거래대금",
    "상장주식수",
    "시가총액",
    "등락률",
    "정규화주가",
]

STOCK_SUMMARY_COLUMNS = [
    "기업명",
    "종목코드",
    "기준일",
    "최근종가",
    "기간수익률",
    "기간최고가",
    "기간최저가",
    "평균거래량",
    "평균거래대금",
    "시가총액",
]

FIELD_MAP = {
    "basDt": "기준일",
    "mrktCtg": "시장구분",
    "clpr": "종가",
    "mkp": "시가",
    "hipr": "고가",
    "lopr": "저가",
    "trqu": "거래량",
    "trPrc": "거래대금",
    "lstgStCnt": "상장주식수",
    "mrktTotAmt": "시가총액",
    "fltRt": "등락률",
}

NUMBER_COLUMNS = [
    "종가",
    "시가",
    "고가",
    "저가",
    "거래량",
    "거래대금",
    "상장주식수",
    "시가총액",
    "등락률",
]


def prepare_stock_prices(
    rows: list[dict], company_name: str, stock_code: str
) -> pd.DataFrame:
    """API 레코드를 분석 가능한 일별 데이터프레임으로 정제한다."""
    if not rows:
        return pd.DataFrame(columns=STOCK_PRICE_COLUMNS)

    data = pd.DataFrame(rows).rename(columns=FIELD_MAP)
    required = list(FIELD_MAP.values())
    for column in required:
        if column not in data:
            data[column] = pd.NA
    data["기준일"] = pd.to_datetime(data["기준일"], format="%Y%m%d", errors="coerce")
    for column in NUMBER_COLUMNS:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=["기준일", "종가"]).copy()
    data = data.sort_values("기준일").drop_duplicates("기준일", keep="last")
    data.insert(0, "종목코드", stock_code)
    data.insert(0, "기업명", company_name)
    first_close = data["종가"].iloc[0] if not data.empty else None
    data["정규화주가"] = (
        data["종가"] / first_close * 100 if first_close not in (None, 0) else pd.NA
    )
    return data[STOCK_PRICE_COLUMNS].reset_index(drop=True)


def normalize_for_comparison(prices: pd.DataFrame) -> pd.DataFrame:
    """첫 공통 거래일 종가를 100으로 맞춰 복수 기업을 비교한다."""
    if prices.empty or prices["기업명"].nunique() < 2:
        return prices.copy()
    date_sets = [set(group["기준일"]) for _, group in prices.groupby("기업명")]
    common_dates = set.intersection(*date_sets) if date_sets else set()
    if not common_dates:
        result = prices.copy()
        result["정규화주가"] = pd.NA
        return result

    base_date = min(common_dates)
    result = prices[prices["기준일"] >= base_date].copy()
    base_prices = (
        result[result["기준일"] == base_date]
        .set_index("기업명")["종가"]
        .to_dict()
    )
    result["정규화주가"] = result.apply(
        lambda row: row["종가"] / base_prices[row["기업명"]] * 100
        if base_prices.get(row["기업명"])
        else pd.NA,
        axis=1,
    )
    return result


def add_moving_averages(
    prices: pd.DataFrame, windows: tuple[int, ...] = MOVING_AVERAGE_WINDOWS
) -> pd.DataFrame:
    """거래일 기준 종가 단순이동평균 열을 추가한다."""
    result = prices.sort_values("기준일").copy()
    for window in windows:
        if window <= 0:
            raise ValueError("이동평균 기간은 1일 이상이어야 합니다.")
        result[f"이동평균{window}일"] = result["종가"].rolling(
            window=window, min_periods=window
        ).mean()
    return result


def add_bollinger_bands(
    prices: pd.DataFrame,
    window: int = BOLLINGER_WINDOW,
    std_multiplier: float = BOLLINGER_STD_MULTIPLIER,
) -> pd.DataFrame:
    """종가 기준 볼린저 밴드 중간·상한·하한 열을 추가한다."""
    if window <= 0:
        raise ValueError("볼린저 밴드 기간은 1일 이상이어야 합니다.")
    if std_multiplier < 0:
        raise ValueError("볼린저 밴드 표준편차 배수는 0 이상이어야 합니다.")

    result = prices.sort_values("기준일").copy()
    rolling = result["종가"].rolling(window=window, min_periods=window)
    result["BB중간"] = rolling.mean()
    standard_deviation = rolling.std(ddof=0)
    result["BB상한"] = result["BB중간"] + std_multiplier * standard_deviation
    result["BB하한"] = result["BB중간"] - std_multiplier * standard_deviation
    return result


def summarize_stock_prices(prices: pd.DataFrame) -> pd.DataFrame:
    """기업별 최신 시세와 선택 기간 요약값을 계산한다."""
    if prices.empty:
        return pd.DataFrame(columns=STOCK_SUMMARY_COLUMNS)

    summaries = []
    for (company_name, stock_code), group in prices.groupby(
        ["기업명", "종목코드"], sort=False
    ):
        group = group.sort_values("기준일")
        first_close = group["종가"].iloc[0]
        last = group.iloc[-1]
        period_return = (
            (last["종가"] / first_close - 1) * 100
            if pd.notna(first_close) and first_close != 0
            else pd.NA
        )
        summaries.append(
            {
                "기업명": company_name,
                "종목코드": stock_code,
                "기준일": last["기준일"],
                "최근종가": last["종가"],
                "기간수익률": period_return,
                "기간최고가": group["고가"].max(),
                "기간최저가": group["저가"].min(),
                "평균거래량": group["거래량"].mean(),
                "평균거래대금": group["거래대금"].mean(),
                "시가총액": last["시가총액"],
            }
        )
    return pd.DataFrame(summaries, columns=STOCK_SUMMARY_COLUMNS)
