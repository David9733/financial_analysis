"""기업 수익률과 시장·외부 요인의 상관계수로 히트맵 인사이트를 만든다."""

from __future__ import annotations

import math
from typing import Any


CORRELATION_SIGNAL_THRESHOLD = 0.3
STRONG_CORRELATION_THRESHOLD = 0.7
MIN_SIGNALS_FOR_CONCLUSION = 2

FACTOR_SETTINGS = (
    ("시장지수", "corr_return_market_index", "market_index_change"),
    ("환율", "corr_return_usd_krw", "usd_krw_change"),
    ("금리", "corr_return_treasury_3y", "treasury_3y_change_bp"),
    ("신용 스프레드", "corr_return_credit_spread", "credit_spread_change_bp"),
)


def _available_number(metric: dict[str, Any] | None) -> float | None:
    """화면 판정에 사용할 수 있는 유한한 KPI 값만 반환한다."""
    if not metric or metric.get("status") != "available":
        return None
    value = metric.get("value")
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _available_text(metric: dict[str, Any] | None) -> str | None:
    if not metric or metric.get("status") != "available":
        return None
    value = str(metric.get("value") or "").strip()
    return value or None


def _correlation_strength(value: float | None) -> str:
    if value is None:
        return "계산 불가"
    magnitude = abs(value)
    if magnitude < CORRELATION_SIGNAL_THRESHOLD:
        return "약함"
    if magnitude < STRONG_CORRELATION_THRESHOLD:
        return "중간"
    return "강함"


def _format_correlation(value: float | None) -> str:
    if value is None:
        return "계산 불가"
    return f"{value:+.2f}({_correlation_strength(value)})"


def _format_change(value: float, digits: int, unit: str) -> str:
    if value == 0:
        return f"0{unit}"
    number = f"{value:+.{digits}f}".rstrip("0").rstrip(".")
    return f"{number}{unit}"


def _direction_text(
    factor: str, change: float | None, market_name: str | None
) -> str | None:
    if change is None:
        if factor == "시장지수":
            return f"{market_name or '시장지수'} 방향 판단 불가"
        if factor == "환율":
            return "원화 방향 판단 불가"
        return f"{factor} 방향 판단 불가"
    if factor == "시장지수":
        name = market_name or "시장지수"
        direction = "상승" if change > 0 else "하락" if change < 0 else "보합"
        return f"{name} {direction}({_format_change(change, 2, '%')})"
    if factor == "환율":
        direction = "원화 약세" if change > 0 else "원화 강세" if change < 0 else "원화 보합"
        return f"{direction}(환율 {_format_change(change, 2, '%')})"
    if factor == "금리":
        direction = "상승" if change > 0 else "하락" if change < 0 else "보합"
        return f"금리 {direction}({_format_change(change, 1, 'bp')})"
    direction = "확대" if change > 0 else "축소" if change < 0 else "보합"
    return f"신용 스프레드 {direction}({_format_change(change, 1, 'bp')})"


def _environment_text(
    changes: dict[str, float | None], market_name: str | None, active_factors: set[str]
) -> str:
    parts = [
        text
        for factor in ("시장지수", "금리", "환율", "신용 스프레드")
        if factor in active_factors
        if (text := _direction_text(factor, changes.get(factor), market_name))
    ]
    if not parts:
        return "조회기간 실제 환경을 계산할 수 없습니다."
    return f"조회기간 실제 환경: {'·'.join(parts)}."


def build_correlation_insight(macro_kpi: dict[str, dict[str, Any]]) -> str:
    """실제 요인 방향과 기업 수익률 상관을 결합해 주가 방향 신호를 요약한다."""
    correlations: dict[str, float | None] = {}
    changes: dict[str, float | None] = {}
    active_factors = set()
    evidence_parts = []
    signals = []
    for factor, correlation_key, change_key in FACTOR_SETTINGS:
        correlation = _available_number(macro_kpi.get(correlation_key))
        change = _available_number(macro_kpi.get(change_key))
        correlations[factor] = correlation
        changes[factor] = change
        if correlation_key in macro_kpi:
            active_factors.add(factor)
            evidence_parts.append(
                f"주가–{factor} r={_format_correlation(correlation)}"
            )
        if change_key in macro_kpi:
            active_factors.add(factor)
        if (
            correlation is not None
            and change is not None
            and change != 0
            and abs(correlation) >= CORRELATION_SIGNAL_THRESHOLD
        ):
            effect = correlation * (1 if change > 0 else -1)
            signals.append(
                {
                    "factor": factor,
                    "effect": "상승 방향" if effect > 0 else "하락 방향",
                    "strong": abs(correlation) >= STRONG_CORRELATION_THRESHOLD,
                }
            )

    environment = _environment_text(
        changes,
        _available_text(macro_kpi.get("market_index_name")),
        active_factors,
    )
    rising = [
        signal["factor"] for signal in signals if signal["effect"] == "상승 방향"
    ]
    falling = [
        signal["factor"] for signal in signals if signal["effect"] == "하락 방향"
    ]

    if len(signals) < MIN_SIGNALS_FOR_CONCLUSION:
        conclusion = "유효한 중간 이상 신호가 2개 미만이라 종합 판단을 유보합니다."
    elif not falling:
        conclusion = (
            f"유효 신호 {len(signals)}개가 모두 과거 주가 상승 방향으로 "
            f"나타났습니다({', '.join(rising)})."
        )
    elif not rising:
        conclusion = (
            f"유효 신호 {len(signals)}개가 모두 과거 주가 하락 방향으로 "
            f"나타났습니다({', '.join(falling)})."
        )
    else:
        conclusion = (
            f"유효 신호 {len(signals)}개 중 주가 상승 방향 {len(rising)}개"
            f"({', '.join(rising)}), 주가 하락 방향 {len(falling)}개"
            f"({', '.join(falling)})로 방향이 혼재합니다."
        )

    strong_signals = [signal for signal in signals if signal["strong"]]
    strong_text = ""
    if strong_signals:
        strong_text = " 강한 신호: " + "·".join(
            f"{signal['factor']} {signal['effect']}" for signal in strong_signals
        ) + "."
    evidence = f" ({', '.join(evidence_parts)})" if evidence_parts else ""
    return f"{environment} {conclusion}{strong_text}{evidence}"


def build_company_correlation_insights(payload: dict[str, Any]) -> dict[str, str]:
    """KPI payload를 기업명별 히트맵 인사이트로 변환한다."""
    return {
        company["company"]: build_correlation_insight(company.get("macro_kpi", {}))
        for company in payload.get("companies", [])
    }
