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
RADAR_FACTOR_SETTINGS = (
    ("환율", "usd_krw", "corr_return_usd_krw", "usd_krw_change"),
    ("금리", "treasury_3y", "corr_return_treasury_3y", "treasury_3y_change_bp"),
    (
        "신용 스프레드",
        "credit_spread",
        "corr_return_credit_spread",
        "credit_spread_change_bp",
    ),
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
    return f"조회기간 실제 환경: {', '.join(parts)}."


def _build_macro_radar_insight(macro_kpi: dict[str, dict[str, Any]]) -> str | None:
    """시장 대비 차이와 이동상관 안정성이 큰 요인부터 레이더 문장으로 요약한다."""
    market_name = _available_text(macro_kpi.get("market_index_name")) or "시장지수"
    radar_rows = []
    for factor, prefix, company_key, change_key in RADAR_FACTOR_SETTINGS:
        company_corr = _available_number(macro_kpi.get(company_key))
        market_corr = _available_number(
            macro_kpi.get(f"radar_{prefix}_market_corr")
        )
        excess_corr = _available_number(
            macro_kpi.get(f"radar_{prefix}_excess_corr")
        )
        judgement_metric = macro_kpi.get(f"radar_{prefix}_judgement")
        judgement = _available_text(judgement_metric)
        if company_corr is None or market_corr is None or excess_corr is None or not judgement:
            continue
        radar_rows.append(
            {
                "factor": factor,
                "prefix": prefix,
                "company_corr": company_corr,
                "market_corr": market_corr,
                "excess_corr": excess_corr,
                "judgement": judgement,
                "base_judgement": judgement.replace(" (단기 참고)", ""),
                "window_days": (
                    judgement_metric.get("window_days") if judgement_metric else None
                ),
                "short_term": bool(
                    judgement_metric.get("short_term") if judgement_metric else False
                ),
                "change": _available_number(macro_kpi.get(change_key)),
                "persistence": _available_number(
                    macro_kpi.get(f"radar_{prefix}_sign_persistence")
                ),
                "switches": _available_number(
                    macro_kpi.get(f"radar_{prefix}_sign_switches")
                ),
                "switch_rate": _available_number(
                    macro_kpi.get(f"radar_{prefix}_sign_switch_rate")
                ),
            }
        )
    if not radar_rows:
        return None

    radar_rows.sort(key=lambda row: abs(row["excess_corr"]), reverse=True)
    focus_rows = radar_rows[:2]
    descriptions = []
    for row in focus_rows:
        window_text = (
            f"{int(row['window_days'])}거래일"
            if row["window_days"] is not None
            else "기간별"
        )
        stability_text = f"{window_text} 안정성은 자료 부족으로 판정을 유보합니다"
        if (
            row["persistence"] is not None
            and row["switches"] is not None
            and row["switch_rate"] is not None
        ):
            stability_text = (
                f"{window_text} 이동상관의 부호 유지율 {row['persistence']:.1f}%, "
                f"전환 {int(row['switches'])}회, 전환율 {row['switch_rate']:.1f}%로 "
                + (
                    "안정적입니다"
                    if row["base_judgement"].endswith("× 안정")
                    else "관계가 흔들렸습니다"
                )
            )
        descriptions.append(
            f"{row['factor']}은 기업 r={row['company_corr']:+.2f}, "
            f"{market_name} r={row['market_corr']:+.2f}, 시장 대비 "
            f"{row['excess_corr']:+.2f}로 "
            f"{row['base_judgement'].split(' × ')[0]}"
            f"{' (단기 참고)' if row['short_term'] else ''}이며, {stability_text}"
        )

    strongest = radar_rows[0]
    if strongest["base_judgement"] == "노출 강 × 안정" and strongest["short_term"]:
        conclusion = (
            f"{strongest['factor']}은 단기 조회에서 시장과 구별되는 관계가 일관되게 "
            "나타난 노출 후보이며, 더 긴 기간에서도 이어지는지 확인할 필요가 있습니다."
        )
    elif strongest["base_judgement"] == "노출 강 × 안정":
        conclusion = (
            f"{strongest['factor']}은 시장과 구별되는 관계가 기간 중 비교적 꾸준해 "
            "구조적 노출 후보로 추가 확인할 가치가 있습니다."
        )
    elif strongest["base_judgement"] == "노출 강 × 흔들림":
        conclusion = (
            f"{strongest['factor']}의 시장 대비 차이는 크지만 관계가 흔들려, "
            "부호 전환 시점의 공시나 시장 사건을 확인할 필요가 있습니다."
        )
    elif "노출 약" in strongest["judgement"]:
        conclusion = (
            "확인된 요인 중 시장과 뚜렷이 구별되는 기업 고유 동행성은 제한적입니다."
        )
    else:
        conclusion = (
            f"가장 큰 시장 대비 차이는 {strongest['factor']}에서 나타났으며, "
            "기업 고유 노출 여부는 다른 기간과 함께 확인할 필요가 있습니다."
        )

    changes = {
        factor: _available_number(macro_kpi.get(change_key))
        for factor, _, _, change_key in RADAR_FACTOR_SETTINGS
    }
    market_change = _available_number(macro_kpi.get("market_index_change"))
    changes["시장지수"] = market_change
    environment = _environment_text(
        changes,
        market_name,
        {"시장지수", *(row["factor"] for row in radar_rows)},
    )
    return (
        f"{environment} 매크로 레이더: {'; '.join(descriptions)}. "
        f"핵심 판정: {conclusion} "
        "해석 유의: 선택기간의 과거 동행성과 시장 대비 차이이며 "
        "인과관계나 미래 방향을 뜻하지 않습니다."
    )


def build_correlation_insight(macro_kpi: dict[str, dict[str, Any]]) -> str:
    """실제 요인 방향과 기업 수익률 상관을 결합해 주가 방향 신호를 요약한다."""
    radar_insight = _build_macro_radar_insight(macro_kpi)
    if radar_insight is not None:
        return radar_insight

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
        strong_text = " 강한 신호: " + ", ".join(
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
