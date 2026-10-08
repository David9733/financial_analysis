from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd

from src.app import (
    MACRO_TABLE_HIDDEN_KEYS,
    build_headline_kpi_cards,
    build_headline_kpi_matrix,
    build_csv_preview,
    build_kpi_matrix,
    build_macro_radar_matrix,
    build_macro_radar_summaries,
    build_market_overview_cards,
    group_stock_chart_items,
)
from src.main import _market_overview_item, collect_market_macro


def metric(value, unit="%", status="available") -> dict:
    return {"value": value, "unit": unit, "status": status, "reason": None}


class ResultDashboardViewModelTests(unittest.TestCase):
    def test_csv_preview_keeps_all_columns_and_only_first_five_rows(self):
        frame = pd.DataFrame(
            {"첫째 열": range(7), "둘째 열": [f"값 {index}" for index in range(7)]}
        )

        preview = build_csv_preview("sample", "샘플", frame, "/sample.csv")

        self.assertEqual(preview["columns"], ["첫째 열", "둘째 열"])
        self.assertEqual(len(preview["rows"]), 5)
        self.assertEqual(preview["rows"][-1], ["4", "값 4"])
        self.assertEqual(preview["download_url"], "/sample.csv")

    def test_headline_kpis_follow_company_industry(self):
        payload = {
            "companies": [
                {
                    "company": "일반사",
                    "analysis_type": "일반기업",
                    "financial_kpi": {
                        "revenue_growth": metric(1),
                        "operating_margin": metric(2),
                        "roe": metric(3),
                        "debt_ratio": metric(4),
                    },
                },
                {
                    "company": "은행",
                    "analysis_type": "금융업",
                    "financial_kpi": {
                        "net_interest_income": metric(100, "원"),
                        "net_fee_income": metric(200, "원"),
                        "roe": metric(5),
                        "roa": metric(6),
                    },
                },
                {
                    "company": "보험사",
                    "analysis_type": "보험업",
                    "financial_kpi": {
                        "insurance_revenue_growth": metric(7),
                        "insurance_margin": metric(8),
                        "roe": metric(9),
                        "investment_profit": metric(300, "원"),
                    },
                },
            ]
        }

        cards = build_headline_kpi_cards(payload)

        self.assertEqual([len(card["metrics"]) for card in cards], [4, 4, 4])
        self.assertEqual(cards[0]["metrics"][0]["label"], "매출 성장률")
        self.assertEqual(cards[1]["metrics"][0]["label"], "순이자손익")
        self.assertEqual(cards[2]["metrics"][0]["label"], "보험서비스수익 성장률")

    def test_mixed_industry_matrix_keeps_not_applicable_cells(self):
        payload = {
            "companies": [
                {
                    "company": "일반사",
                    "analysis_type": "일반기업",
                    "financial_kpi": {"revenue_growth": metric(4.2)},
                },
                {
                    "company": "은행",
                    "analysis_type": "금융업",
                    "financial_kpi": {"roe": metric(8.1)},
                },
            ]
        }

        matrix = build_headline_kpi_matrix(payload)
        revenue_row = next(row for row in matrix["rows"] if row["key"] == "revenue_growth")

        self.assertEqual(matrix["companies"], ["일반사", "은행"])
        self.assertEqual(revenue_row["values"], ["4.2%", "해당 없음"])

    def test_financial_matrix_can_hide_not_applicable_cells_and_rows(self):
        payload = {
            "companies": [
                {
                    "company": "일반사",
                    "financial_kpi": {
                        "revenue_growth": metric(4.2),
                        "roa": metric(None, "", "not_applicable"),
                    },
                },
                {
                    "company": "은행",
                    "financial_kpi": {
                        "revenue_growth": metric(None, "", "not_applicable"),
                        "roa": metric(None, "", "not_applicable"),
                    },
                },
            ]
        }

        matrix = build_kpi_matrix(
            payload, "financial_kpi", hide_not_applicable=True
        )

        self.assertEqual([row["key"] for row in matrix["rows"]], ["revenue_growth"])
        self.assertEqual(matrix["rows"][0]["values"], ["4.2%", ""])

    def test_macro_radar_is_separated_from_market_and_external_factors(self):
        payload = {
            "companies": [
                {
                    "company": "삼성전자",
                    "macro_kpi": {
                        "usd_krw_latest": metric(1358, "원"),
                        "radar_usd_krw_excess_corr": metric(0.017, ""),
                        "radar_usd_krw_sign_persistence": metric(
                            None, "%", "neutral_direction"
                        ),
                        "radar_usd_krw_judgement": metric(
                            "노출 약 × 안정성 판정 불가 (기준 방향 없음)", ""
                        ),
                    },
                }
            ]
        }

        external = build_kpi_matrix(
            payload,
            "macro_kpi",
            exclude_keys=MACRO_TABLE_HIDDEN_KEYS,
        )
        radar = build_macro_radar_matrix(payload)
        summaries = build_macro_radar_summaries(payload)

        self.assertEqual([row["key"] for row in external["rows"]], ["usd_krw_latest"])
        self.assertEqual(
            [row["key"] for row in radar["rows"]],
            [
                "radar_usd_krw_excess_corr",
                "radar_usd_krw_sign_persistence",
            ],
        )
        self.assertEqual(
            summaries,
            [
                {
                    "label": "환율",
                    "value": "노출 약 + 안정성 판정 불가 (기준 방향 없음)",
                }
            ],
        )

    def test_market_overview_uses_latest_date_and_period_change(self):
        index_frame = pd.DataFrame(
            {
                "기준일": pd.to_datetime(["2026-01-02", "2026-01-31"]),
                "시장지수종가": [100.0, 110.0],
            }
        )
        rate_frame = pd.DataFrame(
            {
                "기준일": pd.to_datetime(["2026-01-02", "2026-01-31"]),
                "국고채3년": [3.0, 3.2],
            }
        )

        index_item = _market_overview_item(
            "KOSPI", "KOSPI", index_frame, "시장지수종가",
            date(2026, 1, 1), date(2026, 1, 31), "p", "pct"
        )
        rate_item = _market_overview_item(
            "treasury_3y", "국고채 3년", rate_frame, "국고채3년",
            date(2026, 1, 1), date(2026, 1, 31), "%", "diff"
        )
        cards = build_market_overview_cards([index_item, rate_item])

        self.assertEqual(index_item["latest_date"], "2026-01-31")
        self.assertAlmostEqual(index_item["change"], 10.0)
        self.assertAlmostEqual(rate_item["change"], 20.0)
        self.assertEqual(cards[1]["change"], "기간 변화 +20.00bp")

    def test_collects_both_indices_but_merges_company_market_only(self):
        prices = pd.DataFrame(
            {
                "기업명": ["코스피사", "코스피사"],
                "종목코드": ["000001", "000001"],
                "기준일": pd.to_datetime(["2026-01-02", "2026-01-03"]),
                "종가": [1000.0, 1010.0],
                "시장구분": ["KOSPI", "KOSPI"],
            }
        )
        stock_client = Mock()

        def index_rows(market, *_args):
            values = [100.0, 110.0] if market == "KOSPI" else [200.0, 240.0]
            return [
                {"basDt": "20260102", "clpr": str(values[0])},
                {"basDt": "20260103", "clpr": str(values[1])},
            ]

        stock_client.get_market_index_prices.side_effect = index_rows
        empty_series = SimpleNamespace(rows=[], failed_dates=[])
        with patch("src.main.get_exim_api_key", return_value="key"), patch(
            "src.main.get_ecos_api_key", return_value="key"
        ), patch("src.main.ExchangeRateClient") as exchange_client, patch(
            "src.main.InterestRateClient"
        ) as rate_client:
            exchange_client.return_value.get_usd_krw.return_value = empty_series
            rate_client.return_value.get_treasury_3y.return_value = empty_series
            rate_client.return_value.get_corporate_aa_minus_3y.return_value = empty_series
            merged = collect_market_macro(prices, [], stock_client=stock_client)

        requested = {
            call.args[0] for call in stock_client.get_market_index_prices.call_args_list
        }
        self.assertEqual(requested, {"KOSPI", "KOSDAQ"})
        self.assertEqual(merged["시장지수종가"].tolist(), [100.0, 110.0])
        self.assertEqual(
            [item["key"] for item in merged.attrs["market_overview"][:2]],
            ["KOSPI", "KOSDAQ"],
        )

    def test_stock_charts_are_grouped_by_comparison_purpose(self):
        items = [
            {"filename": "stock_price_1.png", "group": "price"},
            {"filename": "stock_price_2.png", "group": "price"},
            {"filename": "macro_1.png", "group": "macro"},
            {"filename": "market_correlation_heatmap_1.png", "group": "correlation"},
        ]

        groups = group_stock_chart_items(items)

        self.assertEqual([group["key"] for group in groups], ["price", "macro", "correlation"])
        self.assertEqual(len(groups[0]["charts"]), 2)


if __name__ == "__main__":
    unittest.main()
