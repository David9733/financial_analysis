"""업종별 재무 및 시장 KPI를 5축 기업 스타 점수로 변환한다."""

from __future__ import annotations

from typing import Any, Iterable

import pandas as pd


SCORE_LABELS = {
    "growth": "성장성",
    "profitability": "수익성",
    "stability": "재무 안정성",
    "efficiency": "효율성",
    "market": "시장흐름",
}
TREND_SCORES = {"개선": 100.0, "보합": 60.0, "변동": 40.0, "악화": 0.0}

GROWTH_ANCHORS = ((-20.0, 0.0), (-5.0, 25.0), (0.0, 50.0), (10.0, 75.0), (25.0, 100.0))
OPERATING_MARGIN_ANCHORS = ((-10.0, 0.0), (0.0, 25.0), (5.0, 50.0), (15.0, 75.0), (30.0, 100.0))
NET_MARGIN_ANCHORS = ((-10.0, 0.0), (0.0, 25.0), (3.0, 50.0), (10.0, 75.0), (20.0, 100.0))
ROE_ANCHORS = ((-10.0, 0.0), (0.0, 25.0), (5.0, 50.0), (10.0, 75.0), (20.0, 100.0))
ROA_ANCHORS = ((-5.0, 0.0), (0.0, 25.0), (2.0, 50.0), (5.0, 75.0), (10.0, 100.0))
INSURANCE_MARGIN_ANCHORS = ((-10.0, 0.0), (0.0, 25.0), (3.0, 50.0), (8.0, 75.0), (15.0, 100.0))
DEBT_RATIO_ANCHORS = ((50.0, 100.0), (100.0, 75.0), (150.0, 50.0), (250.0, 25.0), (400.0, 0.0))
INTEREST_COVERAGE_ANCHORS = ((0.0, 0.0), (1.0, 25.0), (2.0, 50.0), (5.0, 75.0), (10.0, 100.0))
RECEIVABLE_DAYS_ANCHORS = ((15.0, 100.0), (45.0, 75.0), (90.0, 50.0), (120.0, 25.0), (180.0, 0.0))
FINANCE_EQUITY_RATIO_ANCHORS = ((2.0, 0.0), (4.0, 25.0), (6.0, 50.0), (8.0, 75.0), (12.0, 100.0))
INSURANCE_EQUITY_RATIO_ANCHORS = ((3.0, 0.0), (7.0, 25.0), (12.0, 50.0), (20.0, 75.0), (30.0, 100.0))
FINANCE_ASSET_EFFICIENCY_ANCHORS = ((0.0, 0.0), (0.5, 25.0), (1.0, 50.0), (2.0, 75.0), (4.0, 100.0))
INSURANCE_ASSET_EFFICIENCY_ANCHORS = ((0.0, 0.0), (3.0, 25.0), (7.0, 50.0), (15.0, 75.0), (25.0, 100.0))
RETURN_ANCHORS = ((-20.0, 0.0), (-10.0, 25.0), (0.0, 50.0), (10.0, 75.0), (20.0, 100.0))
PRICE_TO_MA_ANCHORS = ((-15.0, 0.0), (-5.0, 25.0), (0.0, 50.0), (5.0, 75.0), (15.0, 100.0))
VOLATILITY_ANCHORS = ((0.5, 100.0), (1.5, 75.0), (2.5, 50.0), (3.5, 25.0), (5.0, 0.0))


def interpolate_score(value: float, anchors: Iterable[tuple[float, float]]) -> float:
    """고정 기준점 사이를 선형 보간하고 0~100 범위로 제한한다."""
    points = sorted(anchors, key=lambda item: item[0])
    if value <= points[0][0]:
        return max(0.0, min(100.0, points[0][1]))
    if value >= points[-1][0]:
        return max(0.0, min(100.0, points[-1][1]))
    for (left_value, left_score), (right_value, right_score) in zip(points, points[1:]):
        if left_value <= value <= right_value:
            ratio = (value - left_value) / (right_value - left_value)
            score = left_score + (right_score - left_score) * ratio
            return max(0.0, min(100.0, score))
    return 0.0


def _number(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metric_value(metrics: dict[str, dict], key: str) -> float | None:
    metric = metrics.get(key, {})
    if metric.get("status") != "available":
        return None
    return _number(metric.get("value"))


def _growth(current: Any, previous: Any) -> float | None:
    current_number = _number(current)
    previous_number = _number(previous)
    # 전년 값이 0 이하이면 증감률 부호가 뒤집히므로 점수에 넣지 않는다.
    if current_number is None or previous_number is None or previous_number <= 0:
        return None
    return (current_number / previous_number - 1.0) * 100.0


def _ratio(numerator: Any, denominator: Any) -> float | None:
    numerator_number = _number(numerator)
    denominator_number = _number(denominator)
    if numerator_number is None or denominator_number in (None, 0.0):
        return None
    return numerator_number / denominator_number * 100.0


def _format_value(value: float, unit: str) -> str:
    digits = 1 if abs(value) < 100 else 0
    formatted = f"{value:,.{digits}f}"
    return f"{formatted}{unit}" if unit else formatted


def _component(
    label: str,
    value: float | None,
    unit: str,
    weight: float,
    anchors: Iterable[tuple[float, float]],
    *,
    trend_key: str | None = None,
    is_proxy: bool = False,
    fixed_score: float | None = None,
    fixed_display: str | None = None,
) -> dict[str, Any]:
    if fixed_score is not None:
        score = fixed_score
    else:
        score = interpolate_score(value, anchors) if value is not None else None
    if fixed_display is not None:
        display_value = fixed_display
    else:
        display_value = _format_value(value, unit) if value is not None else None
    return {
        "label": label,
        "value": value,
        "display_value": display_value,
        "weight": weight,
        "score": score,
        "trend_key": trend_key,
        "is_proxy": is_proxy,
    }


def _axis(
    key: str,
    components: list[dict[str, Any]],
    trends: dict[str, dict],
    *,
    is_proxy: bool = False,
) -> dict[str, Any]:
    planned_weight = sum(item["weight"] for item in components)
    available = [item for item in components if item["score"] is not None]
    available_weight = sum(item["weight"] for item in available)
    if not planned_weight or available_weight / planned_weight < 0.5:
        return {
            "key": key,
            "label": SCORE_LABELS[key],
            "score": None,
            "status": "insufficient_data",
            "evidence": [],
            "is_proxy": is_proxy or any(item["is_proxy"] for item in components),
            "reason": "예정된 점수 비중의 50% 이상을 계산할 KPI가 없습니다.",
        }

    level_score = sum(item["score"] * item["weight"] for item in available) / available_weight
    trend_items = []
    for item in available:
        trend = trends.get(item["trend_key"], {}) if item["trend_key"] else {}
        trend_score = TREND_SCORES.get(trend.get("value"))
        if trend.get("status") == "available" and trend_score is not None:
            trend_items.append((trend_score, item["weight"]))
    if trend_items:
        trend_score = sum(score * weight for score, weight in trend_items) / sum(
            weight for _, weight in trend_items
        )
        score = level_score * 0.8 + trend_score * 0.2
    else:
        score = level_score

    evidence = [
        {"label": item["label"], "value": item["display_value"]}
        for item in sorted(available, key=lambda item: item["weight"], reverse=True)[:3]
    ]
    return {
        "key": key,
        "label": SCORE_LABELS[key],
        "score": int(round(max(0.0, min(100.0, score)))),
        "status": "available",
        "evidence": evidence,
        "is_proxy": is_proxy or any(item["is_proxy"] for item in available),
        "reason": None,
    }


def _row_value(row: pd.Series | None, column: str) -> float | None:
    if row is None or column not in row:
        return None
    return _number(row[column])


def _positive_profit_persistence(rows: pd.DataFrame) -> float | None:
    """최근 3개 연속 사업연도 중 흑자인 연도의 비율을 반환한다."""
    if "당기순이익" not in rows or len(rows) < 3:
        return None
    recent = rows.sort_values("연도").tail(3)
    periods = [_number(value) for value in recent["연도"]]
    profits = [_number(value) for value in recent["당기순이익"]]
    if (
        any(value is None for value in periods + profits)
        or int(periods[1]) - int(periods[0]) != 1
        or int(periods[2]) - int(periods[1]) != 1
    ):
        return None
    return sum(value > 0 for value in profits) / 3 * 100


def build_star_score(
    analysis_type: str,
    score_rows: pd.DataFrame,
    financial_kpi: dict[str, dict],
    financial_trend: dict[str, dict],
    market_kpi: dict[str, dict],
    macro_kpi: dict[str, dict],
) -> list[dict[str, Any]]:
    """기업 하나의 성장성, 수익성, 안정성, 효율성 및 시장흐름 점수를 만든다."""
    ordered = score_rows.sort_values("연도").reset_index(drop=True)
    latest = ordered.iloc[-1] if not ordered.empty else None
    # 성장률과 평균자산은 바로 전 사업연도와 비교해야 하므로 연도가 이어질 때만 쓴다.
    previous = (
        ordered.iloc[-2]
        if len(ordered) >= 2
        and int(ordered.iloc[-1]["연도"]) - int(ordered.iloc[-2]["연도"]) == 1
        else None
    )
    latest_value = lambda column: _row_value(latest, column)
    previous_value = lambda column: _row_value(previous, column)

    if analysis_type == "금융업":
        growth = [
            _component("순이자손익 성장률", _growth(latest_value("순이자손익"), previous_value("순이자손익")), "%", 0.4, GROWTH_ANCHORS, trend_key="net_interest_income"),
            _component("순수수료손익 성장률", _growth(latest_value("순수수료손익"), previous_value("순수수료손익")), "%", 0.3, GROWTH_ANCHORS, trend_key="net_fee_income"),
            _component("총자산 성장률", latest_value("총자산성장"), "%", 0.15, GROWTH_ANCHORS, is_proxy=True),
            _component("당기순이익 성장률", _metric_value(financial_kpi, "net_income_growth"), "%", 0.15, GROWTH_ANCHORS, trend_key="net_income_growth"),
        ]
        profitability = [
            _component("ROE", _metric_value(financial_kpi, "roe"), "%", 0.5, ROE_ANCHORS, trend_key="roe"),
            _component("ROA", _metric_value(financial_kpi, "roa"), "%", 0.5, ROA_ANCHORS, trend_key="roa"),
        ]
        equity_ratio = _ratio(latest_value("자본총계"), latest_value("총자산"))
        profit_persistence = _positive_profit_persistence(ordered)
        stability = [
            _component("자기자본비중", equity_ratio, "%", 0.6, FINANCE_EQUITY_RATIO_ANCHORS, is_proxy=True),
            _component("최근 3년 흑자 지속", profit_persistence, "%", 0.4, ((0.0, 0.0), (33.0, 33.0), (67.0, 67.0), (100.0, 100.0)), is_proxy=True),
        ]
        average_assets = None
        if latest_value("총자산") is not None and previous_value("총자산") is not None:
            average_assets = (latest_value("총자산") + previous_value("총자산")) / 2
        core_income = None
        if latest_value("순이자손익") is not None and latest_value("순수수료손익") is not None:
            core_income = latest_value("순이자손익") + latest_value("순수수료손익")
        efficiency = [
            _component("핵심영업수익/평균자산", _ratio(core_income, average_assets), "%", 0.6, FINANCE_ASSET_EFFICIENCY_ANCHORS, is_proxy=True),
            _component("ROA", _metric_value(financial_kpi, "roa"), "%", 0.4, ROA_ANCHORS, trend_key="roa", is_proxy=True),
        ]
        proxy_axes = {"growth": True, "stability": True, "efficiency": True}
    elif analysis_type == "보험업":
        growth = [
            _component("보험서비스수익 성장률", _metric_value(financial_kpi, "insurance_revenue_growth"), "%", 0.4, GROWTH_ANCHORS, trend_key="insurance_revenue_growth"),
            _component("총자산 성장률", latest_value("총자산성장"), "%", 0.2, GROWTH_ANCHORS, is_proxy=True),
            _component("영업이익 성장률", _metric_value(financial_kpi, "operating_profit_growth"), "%", 0.2, GROWTH_ANCHORS, trend_key="operating_profit_growth"),
            _component("당기순이익 성장률", _metric_value(financial_kpi, "net_income_growth"), "%", 0.2, GROWTH_ANCHORS, trend_key="net_income_growth"),
        ]
        profitability = [
            _component("보험서비스마진", _metric_value(financial_kpi, "insurance_margin"), "%", 0.4, INSURANCE_MARGIN_ANCHORS, trend_key="insurance_margin"),
            _component("ROE", _metric_value(financial_kpi, "roe"), "%", 0.3, ROE_ANCHORS, trend_key="roe"),
            _component("ROA", _metric_value(financial_kpi, "roa"), "%", 0.3, ROA_ANCHORS, trend_key="roa"),
        ]
        profit_persistence = _positive_profit_persistence(ordered)
        stability = [
            _component("자기자본비중", _ratio(latest_value("자본총계"), latest_value("총자산")), "%", 0.6, INSURANCE_EQUITY_RATIO_ANCHORS, is_proxy=True),
            _component("최근 3년 흑자 지속", profit_persistence, "%", 0.4, ((0.0, 0.0), (33.0, 33.0), (67.0, 67.0), (100.0, 100.0)), is_proxy=True),
        ]
        average_assets = None
        if latest_value("총자산") is not None and previous_value("총자산") is not None:
            average_assets = (latest_value("총자산") + previous_value("총자산")) / 2
        insurance_inflow = None
        if latest_value("보험서비스수익") is not None and latest_value("투자손익") is not None:
            insurance_inflow = latest_value("보험서비스수익") + latest_value("투자손익")
        efficiency = [
            _component("보험·투자수익/평균자산", _ratio(insurance_inflow, average_assets), "%", 0.6, INSURANCE_ASSET_EFFICIENCY_ANCHORS, is_proxy=True),
            _component("ROA", _metric_value(financial_kpi, "roa"), "%", 0.4, ROA_ANCHORS, trend_key="roa", is_proxy=True),
        ]
        proxy_axes = {"growth": True, "stability": True, "efficiency": True}
    else:
        growth = [
            _component("매출 성장률", _metric_value(financial_kpi, "revenue_growth"), "%", 0.4, GROWTH_ANCHORS, trend_key="revenue_growth"),
            _component("영업이익 성장률", _metric_value(financial_kpi, "operating_profit_growth"), "%", 0.3, GROWTH_ANCHORS, trend_key="operating_profit_growth"),
            _component("당기순이익 성장률", _metric_value(financial_kpi, "net_income_growth"), "%", 0.3, GROWTH_ANCHORS, trend_key="net_income_growth"),
        ]
        profitability = [
            _component("영업이익률", _metric_value(financial_kpi, "operating_margin"), "%", 0.3, OPERATING_MARGIN_ANCHORS, trend_key="operating_margin"),
            _component("순이익률", _metric_value(financial_kpi, "net_margin"), "%", 0.25, NET_MARGIN_ANCHORS, trend_key="net_margin"),
            _component("ROE", _metric_value(financial_kpi, "roe"), "%", 0.25, ROE_ANCHORS, trend_key="roe"),
            _component("ROA", _metric_value(financial_kpi, "roa"), "%", 0.2, ROA_ANCHORS, trend_key="roa"),
        ]
        debt_metric = financial_kpi.get("debt_ratio", {})
        # 자본잠식은 부채비율을 계산할 수 없지만 안정성이 가장 낮은 상태이므로 0점으로 반영한다.
        capital_impaired = (
            debt_metric.get("status") == "negative_base"
            and debt_metric.get("reason") == "자본잠식"
        )
        stability = [
            _component(
                "부채비율",
                _metric_value(financial_kpi, "debt_ratio"),
                "%",
                0.5,
                DEBT_RATIO_ANCHORS,
                trend_key="debt_ratio",
                fixed_score=0.0 if capital_impaired else None,
                fixed_display="자본잠식" if capital_impaired else None,
            ),
            _component("이자보상배율", _metric_value(financial_kpi, "interest_coverage_ratio"), "배", 0.5, INTEREST_COVERAGE_ANCHORS, trend_key="interest_coverage_ratio"),
        ]
        efficiency = [
            _component("매출채권 회전일수", _metric_value(financial_kpi, "accounts_receivable_days"), "일", 1.0, RECEIVABLE_DAYS_ANCHORS, trend_key="accounts_receivable_days"),
        ]
        proxy_axes = {}

    period_return = _metric_value(market_kpi, "period_return")
    market_return = _metric_value(macro_kpi, "market_index_change")
    excess_return = period_return - market_return if period_return is not None and market_return is not None else None
    market = [
        _component("시장 대비 초과수익률", excess_return, "%p", 0.5, RETURN_ANCHORS),
        _component("기간 수익률", period_return, "%", 0.2, RETURN_ANCHORS),
        _component("20일 이동평균 대비", _metric_value(market_kpi, "price_to_ma20"), "%", 0.2, PRICE_TO_MA_ANCHORS),
        _component("일간 변동성", _metric_value(market_kpi, "daily_volatility"), "%", 0.1, VOLATILITY_ANCHORS),
    ]

    return [
        _axis("growth", growth, financial_trend, is_proxy=proxy_axes.get("growth", False)),
        _axis("profitability", profitability, financial_trend),
        _axis("stability", stability, financial_trend, is_proxy=proxy_axes.get("stability", False)),
        _axis("efficiency", efficiency, financial_trend, is_proxy=proxy_axes.get("efficiency", False)),
        _axis("market", market, {}, is_proxy=False),
    ]
