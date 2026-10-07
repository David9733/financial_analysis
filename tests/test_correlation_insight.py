from __future__ import annotations

import unittest

from src.correlation_insight import (
    build_company_correlation_insights,
    build_correlation_insight,
)


def metric(value, status="available"):
    return {"value": value, "unit": "", "status": status, "reason": None}


def macro(
    fx,
    rate,
    fx_status="available",
    rate_status="available",
    fx_change=2.4,
    rate_change=16.1,
):
    return {
        "corr_return_usd_krw": metric(fx, fx_status),
        "corr_return_treasury_3y": metric(rate, rate_status),
        "usd_krw_change": metric(fx_change),
        "treasury_3y_change_bp": metric(rate_change),
    }


def full_macro(
    market=0.75,
    fx=0.4,
    rate=-0.5,
    spread=-0.8,
    market_change=3.2,
    fx_change=2.4,
    rate_change=16.1,
    spread_change=8.0,
):
    return {
        "market_index_name": metric("KOSPI"),
        "corr_return_market_index": metric(market),
        "corr_return_usd_krw": metric(fx),
        "corr_return_treasury_3y": metric(rate),
        "corr_return_credit_spread": metric(spread),
        "market_index_change": metric(market_change),
        "usd_krw_change": metric(fx_change),
        "treasury_3y_change_bp": metric(rate_change),
        "credit_spread_change_bp": metric(spread_change),
    }


class CorrelationInsightTests(unittest.TestCase):
    def test_four_sign_combinations(self):
        cases = (
            (0.4, 0.5, "모두 과거 주가 상승 방향"),
            (-0.4, -0.5, "모두 과거 주가 하락 방향"),
            (0.4, -0.5, "주가 상승 방향 1개(환율), 주가 하락 방향 1개(금리)"),
            (-0.4, 0.5, "주가 상승 방향 1개(금리), 주가 하락 방향 1개(환율)"),
        )
        for fx, rate, expected in cases:
            with self.subTest(fx=fx, rate=rate):
                insight = build_correlation_insight(macro(fx, rate))
                self.assertIn(expected, insight)
                self.assertIn("금리 상승(+16.1bp)·원화 약세(환율 +2.4%)", insight)
                self.assertIn(f"주가–환율 r={fx:+.2f}(중간)", insight)
                self.assertIn(f"주가–금리 r={rate:+.2f}(중간)", insight)

    def test_weak_threshold_excludes_0299_but_includes_03(self):
        weak = build_correlation_insight(macro(0.299, 0.8))
        boundary = build_correlation_insight(macro(0.3, 0.8))

        self.assertIn("판단을 유보합니다", weak)
        self.assertIn("r=+0.30(약함)", weak)
        self.assertIn("모두 과거 주가 상승 방향", boundary)
        self.assertIn("r=+0.30(중간)", boundary)

    def test_strong_threshold_uses_absolute_value(self):
        positive = build_correlation_insight(macro(0.7, 0.69))
        negative = build_correlation_insight(macro(-0.7, -0.69))

        self.assertIn("주가–환율 r=+0.70(강함)", positive)
        self.assertIn("주가–금리 r=+0.69(중간)", positive)
        self.assertIn("주가–환율 r=-0.70(강함)", negative)
        self.assertIn("주가–금리 r=-0.69(중간)", negative)

    def test_four_factors_are_combined_and_strong_signals_are_named(self):
        insight = build_correlation_insight(full_macro())

        self.assertIn(
            "KOSPI 상승(+3.2%)·금리 상승(+16.1bp)·원화 약세(환율 +2.4%)"
            "·신용 스프레드 확대(+8bp)",
            insight,
        )
        self.assertIn(
            "유효 신호 4개 중 주가 상승 방향 2개(시장지수, 환율), "
            "주가 하락 방향 2개(금리, 신용 스프레드)로 방향이 혼재",
            insight,
        )
        self.assertIn(
            "강한 신호: 시장지수 상승 방향·신용 스프레드 하락 방향", insight
        )
        self.assertIn("주가–시장지수 r=+0.75(강함)", insight)
        self.assertIn("주가–신용 스프레드 r=-0.80(강함)", insight)

    def test_only_medium_or_strong_nonflat_signals_enter_conclusion(self):
        insight = build_correlation_insight(
            full_macro(market=0.299, fx=0.3, rate=0.7, spread=0.8, spread_change=0)
        )

        self.assertIn("주가–시장지수 r=+0.30(약함)", insight)
        self.assertIn("주가–환율 r=+0.30(중간)", insight)
        self.assertIn("주가–금리 r=+0.70(강함)", insight)
        self.assertIn("유효 신호 2개", insight)
        self.assertNotIn("신용 스프레드 상승 방향", insight)

    def test_actual_macro_directions_change_the_interpretation(self):
        rising = build_correlation_insight(macro(0.4, 0.5))
        falling = build_correlation_insight(
            macro(0.4, 0.5, fx_change=-1.2, rate_change=-8.0)
        )

        self.assertIn("원화 약세", rising)
        self.assertIn("모두 과거 주가 상승 방향", rising)
        self.assertIn("금리 하락(-8bp)·원화 강세(환율 -1.2%)", falling)
        self.assertIn("모두 과거 주가 하락 방향", falling)

    def test_missing_or_unavailable_correlation_defers_judgment(self):
        missing = build_correlation_insight(macro(None, 0.8, "missing"))
        unavailable = build_correlation_insight(
            macro(0.8, None, rate_status="no_comparison_period")
        )

        self.assertIn("판단을 유보합니다", missing)
        self.assertIn("주가–환율 r=계산 불가", missing)
        self.assertIn("판단을 유보합니다", unavailable)
        self.assertIn("주가–금리 r=계산 불가", unavailable)

    def test_missing_or_flat_direction_is_shown_and_defers_judgment(self):
        missing = macro(0.8, 0.8)
        missing["usd_krw_change"] = metric(None, "missing")
        flat = build_correlation_insight(macro(0.8, 0.8, rate_change=0))
        missing_text = build_correlation_insight(missing)

        self.assertIn("원화 방향 판단 불가", missing_text)
        self.assertIn("판단을 유보합니다", missing_text)
        self.assertIn("금리 보합(0bp)", flat)
        self.assertIn("판단을 유보합니다", flat)

    def test_company_payload_is_mapped_without_cross_company_values(self):
        payload = {
            "companies": [
                {"company": "첫째", "macro_kpi": macro(0.4, 0.5)},
                {"company": "둘째", "macro_kpi": macro(-0.4, -0.5)},
            ]
        }

        insights = build_company_correlation_insights(payload)

        self.assertIn("모두 과거 주가 상승 방향", insights["첫째"])
        self.assertIn("모두 과거 주가 하락 방향", insights["둘째"])


if __name__ == "__main__":
    unittest.main()
