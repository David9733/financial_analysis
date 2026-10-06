"""시계열 결측·이상치 처리 규칙과 처리 내역 기록.

- 결측: 휴장·미고시는 직전 값(ffill), 첫 행이 비면 다음 값(bfill). 평균으로 채우지 않는다.
- 이상치: 값 수준이 아니라 하루 변화의 IQR 밖이면 '표시'만 한다.
  추세가 있는 시계열은 수준 기준 IQR이 정상 구간까지 잘라 내기 때문이다.
- 입력 오류: 앞뒤 값 대비 10·100·1000배로 튀었다 돌아오는 소수점·단위 오류만
  원래 값으로 고친다. 실제로 크게 움직인 날은 남긴다.
- 모든 처리 내역은 QualityLog에 남긴다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


IQR_MULTIPLIER = 1.5
SCALE_FACTORS = (10, 100, 1000)
SCALE_TOLERANCE = 0.05
MIN_OUTLIER_OBSERVATIONS = 20

LOG_COLUMNS = ["대상", "기업명", "기준일", "처리", "원래값", "처리값", "사유"]
ACTION_FFILL = "ffill"
ACTION_BFILL = "bfill"
ACTION_SCALE_FIX = "입력오류보정"
ACTION_OUTLIER = "이상치표시"


@dataclass
class QualityLog:
    """결측 채움·입력 오류 보정·이상치 표시 내역."""

    records: list[dict[str, Any]] = field(default_factory=list)

    def add(
        self,
        target: str,
        day,
        action: str,
        original,
        processed,
        reason: str,
        company: str | None = None,
    ) -> None:
        self.records.append(
            {
                "대상": target,
                "기업명": company or "",
                "기준일": pd.Timestamp(day).date().isoformat() if pd.notna(day) else "",
                "처리": action,
                "원래값": None if original is None or pd.isna(original) else float(original),
                "처리값": None if processed is None or pd.isna(processed) else float(processed),
                "사유": reason,
            }
        )

    def to_frame(self) -> pd.DataFrame:
        frame = pd.DataFrame(self.records, columns=LOG_COLUMNS)
        if frame.empty:
            return frame
        return frame.sort_values(["기업명", "대상", "기준일"], kind="stable").reset_index(drop=True)

    def count(self, action: str) -> int:
        return sum(1 for record in self.records if record["처리"] == action)

    def summary_text(self) -> str:
        return (
            "데이터 처리: "
            f"직전 값 채움 {self.count(ACTION_FFILL)}건, "
            f"첫 행 다음 값 채움 {self.count(ACTION_BFILL)}건, "
            f"입력 오류 보정 {self.count(ACTION_SCALE_FIX)}건, "
            f"하루 변화 이상치 표시 {self.count(ACTION_OUTLIER)}건"
            + ("(원인 확인 필요)" if self.count(ACTION_OUTLIER) else "")
        )


def _scale_factor(value: float, neighbor: float) -> int | None:
    """value/neighbor가 10^k(k=±1..±3)에 가까우면 부호 있는 배율을 반환한다."""
    if value <= 0 or neighbor <= 0:
        return None
    ratio = value / neighbor
    for factor in SCALE_FACTORS:
        if abs(ratio / factor - 1) <= SCALE_TOLERANCE:
            return factor
        if abs(ratio * factor - 1) <= SCALE_TOLERANCE:
            return -factor
    return None


def correct_scale_errors(
    frame: pd.DataFrame,
    column: str,
    log: QualityLog | None = None,
    *,
    target: str | None = None,
    company: str | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    """앞뒤 관측값 모두와 10^k배 차이 나는 점만 원래 단위로 되돌린다.

    수준이 바뀐 뒤 유지되는 경우(예: 액면분할)는 다음 값과 배율이 맞지 않아
    보정하지 않는다. 반환하는 multiplier는 보정에 곱한 값(보정 없으면 1)이다.
    """
    result = frame.sort_values("기준일").copy()
    multiplier = pd.Series(1.0, index=result.index)
    observed = result[column].dropna()
    values = observed.to_numpy(dtype=float)
    for position in range(1, len(values) - 1):
        current = values[position]
        before = _scale_factor(current, values[position - 1])
        after = _scale_factor(current, values[position + 1])
        if before is None or before != after:
            continue
        scale = 1 / before if before > 0 else float(-before)
        index = observed.index[position]
        corrected = current * scale
        result.at[index, column] = corrected
        multiplier.at[index] = scale
        if log is not None:
            log.add(
                target or column,
                result.at[index, "기준일"],
                ACTION_SCALE_FIX,
                current,
                corrected,
                f"앞뒤 값 대비 {abs(before)}배 {'큼' if before > 0 else '작음'}(소수점 또는 단위 오류)",
                company,
            )
    return result, multiplier


def daily_change(series: pd.Series, kind: str) -> pd.Series:
    """kind='pct'는 전일 대비 변화율(%), 'diff'는 전일 대비 차이."""
    numbers = pd.to_numeric(series, errors="coerce").astype(float)
    if kind == "pct":
        return numbers.pct_change(fill_method=None) * 100
    if kind == "diff":
        return numbers.diff()
    raise ValueError("kind는 'pct' 또는 'diff'여야 합니다.")


def pair_valid(filled: pd.Series) -> pd.Series:
    """당일과 전일 모두 실제 관측값인 날(보간 없이 계산된 하루 변화)."""
    filled = filled.fillna(False).astype(bool)
    return ~filled & ~filled.shift(1, fill_value=True)


def iqr_bounds(
    changes: pd.Series, valid: pd.Series | None = None, k: float = IQR_MULTIPLIER
) -> tuple[float, float] | None:
    """유효한 하루 변화로만 IQR 경계를 계산한다. 관측이 부족하면 None."""
    mask = changes.notna() if valid is None else (valid.to_numpy() & changes.notna().to_numpy())
    observed = changes[mask]
    if len(observed) < MIN_OUTLIER_OBSERVATIONS:
        return None
    q1, q3 = observed.quantile(0.25), observed.quantile(0.75)
    spread = q3 - q1
    return float(q1 - k * spread), float(q3 + k * spread)


def flag_change_outliers(
    changes: pd.Series, valid: pd.Series | None = None, k: float = IQR_MULTIPLIER
) -> pd.Series:
    """하루 변화가 IQR 범위 밖인 유효 관측일을 True로 표시한다. 값은 바꾸지 않는다."""
    flags = pd.Series(False, index=changes.index)
    bounds = iqr_bounds(changes, valid, k)
    if bounds is None:
        return flags
    lower, upper = bounds
    usable = changes.notna() if valid is None else (
        pd.Series(valid.to_numpy(), index=changes.index) & changes.notna()
    )
    return usable & ((changes < lower) | (changes > upper))
