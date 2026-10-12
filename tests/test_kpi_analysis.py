from __future__ import annotations

import unittest
from unittest.mock import Mock

import pandas as pd

from src.financial_analysis import FINAL_COLUMNS, select_output_periods
from src.kpi_analysis import _financial_trends, build_kpi_payload
from src.main import _query_years


class KPIAnalysisTests(unittest.TestCase):
    @staticmethod
    def financial_frame() -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "기업명": "테스트전자",
                    "분석유형": "일반기업",
                    "연도": 2024,
                    "매출": 1000,
                    "영업이익": 100,
                    "당기순이익": 80,
                    "총자산": 800,
                    "영업이익률": 10.0,
                    "부채비율": 50.0,
                    "이자보상배율": 8.0,
                    "ROE": 12.0,
                    "매출성장": 5.0,
                    "영업이익성장": 7.0,
                    "당기순이익성장": 6.0,
                    "매출채권회전일수": 30.0,
                },
                {
                    "기업명": "테스트전자",
                    "분석유형": "일반기업",
                    "연도": 2025,
                    "매출": 1200,
                    "영업이익": 144,
                    "당기순이익": 100,
                    "총자산": 1000,
                    "영업이익률": 12.0,
                    "부채비율": 45.0,
                    "이자보상배율": 9.0,
                    "ROE": 13.0,
                    "매출성장": 20.0,
                    "영업이익성장": 44.0,
                    "당기순이익성장": 25.0,
                    "매출채권회전일수": 28.0,
                },
            ]
        )

    @staticmethod
    def stock_frame() -> pd.DataFrame:
        dates = pd.date_range("2025-01-01", periods=45, freq="B")
        return pd.DataFrame(
            {
                "기업명": "테스트전자",
                "종목코드": "000001",
                "기준일": dates,
                "종가": [100 + index for index in range(45)],
                "고가": [105 + index for index in range(45)],
                "저가": [95 + index for index in range(45)],
                "거래량": [1000 + index * 10 for index in range(45)],
                "거래대금": [100000 + index * 1000 for index in range(45)],
            }
        )

    def test_builds_financial_and_market_kpis(self):
        payload = build_kpi_payload(
            self.financial_frame(), self.stock_frame(), "1y"
        )
        company = payload["companies"][0]

        self.assertEqual(payload["schema_version"], "1.6")
        self.assertEqual(company["financial_period"], "2025")
        self.assertAlmostEqual(company["financial_kpi"]["net_margin"]["value"], 8.33)
        self.assertAlmostEqual(company["financial_kpi"]["roa"]["value"], 11.11)
        self.assertEqual(
            company["market_kpi"]["recent_volume_change"]["status"], "available"
        )
        self.assertEqual(company["market_kpi"]["latest_close"]["value"], 144.0)
        self.assertEqual(company["market_kpi"]["period_high"]["value"], 149.0)
        self.assertEqual(
            company["market_kpi"]["latest_date"]["status"], "available"
        )
        self.assertEqual(company["financial_periods"], ["2024", "2025"])
        self.assertEqual(len(company["financial_history"]), 2)
        self.assertEqual(
            company["financial_history"][0]["financial_kpi"]["roe"]["value"],
            12.0,
        )
        self.assertEqual(
            company["financial_trend"]["roe"]["status"],
            "no_comparison_period",
        )

    def test_financial_trends_use_metric_direction_and_three_consecutive_years(self):
        history = []
        for period, margin, debt, roe, growth in (
            (2023, 8.0, 80.0, 10.0, 5.0),
            (2024, 9.0, 70.0, 8.0, 5.0),
            (2025, 10.0, 60.0, 11.0, 5.0),
        ):
            history.append(
                {
                    "period": str(period),
                    "financial_kpi": {
                        "operating_margin": {
                            "value": margin,
                            "status": "available",
                        },
                        "debt_ratio": {"value": debt, "status": "available"},
                        "roe": {"value": roe, "status": "available"},
                        "revenue_growth": {
                            "value": growth,
                            "status": "available",
                        },
                    },
                }
            )

        trends = _financial_trends(history)

        self.assertEqual(trends["operating_margin"]["value"], "개선")
        self.assertEqual(trends["debt_ratio"]["value"], "개선")
        self.assertEqual(trends["roe"]["value"], "변동")
        self.assertEqual(trends["revenue_growth"]["value"], "보합")
        self.assertEqual(trends["operating_margin"]["periods"], ["2023", "2024", "2025"])

    def test_one_year_output_uses_separate_three_year_trend_source(self):
        trend_source = self.financial_frame()
        year_2023 = trend_source.iloc[0].copy()
        year_2023["연도"] = 2023
        year_2023["영업이익률"] = 8.0
        year_2023["부채비율"] = 55.0
        year_2023["ROE"] = 11.0
        trend_source = pd.concat(
            [year_2023.to_frame().T, trend_source], ignore_index=True
        )
        displayed = trend_source.tail(1).copy()

        payload = build_kpi_payload(
            displayed,
            pd.DataFrame(),
            "1m",
            financial_trend_source=trend_source,
        )
        company = payload["companies"][0]

        self.assertEqual(company["financial_periods"], ["2025"])
        self.assertEqual(len(company["financial_history"]), 1)
        self.assertEqual(company["financial_trend"]["operating_margin"]["value"], "개선")
        self.assertEqual(
            company["financial_trend"]["operating_margin"]["periods"],
            ["2023", "2024", "2025"],
        )

    def test_one_year_query_collects_enough_history_for_three_year_trend(self):
        client = Mock()
        client.get_annual_financials.return_value = ([], "CFS")

        collected = _query_years(client, "001", "테스트전자", None, None, 1)

        self.assertEqual(len(collected), 4)
        self.assertEqual(client.get_annual_financials.call_count, 4)

    def test_financial_trends_reject_nonconsecutive_years(self):
        history = [
            {
                "period": str(period),
                "financial_kpi": {
                    "roe": {"value": value, "status": "available"}
                },
            }
            for period, value in ((2022, 8.0), (2024, 9.0), (2025, 10.0))
        ]

        trend = _financial_trends(history)["roe"]

        self.assertEqual(trend["status"], "no_comparison_period")

    def test_volume_history_only_changes_recent_volume_kpi(self):
        history = self.stock_frame().copy()
        selected = history.tail(20).copy()

        payload = build_kpi_payload(
            self.financial_frame(),
            selected,
            "1m",
            volume_history=history,
        )
        market = payload["companies"][0]["market_kpi"]

        self.assertEqual(market["recent_volume_change"]["status"], "available")
        self.assertEqual(
            market["start_date"]["value"],
            selected["기준일"].min().date().isoformat(),
        )
        self.assertEqual(market["average_volume"]["value"], round(selected["거래량"].mean()))

    def test_missing_stock_data_is_explicit(self):
        payload = build_kpi_payload(
            self.financial_frame(), pd.DataFrame(), "1y"
        )
        market = payload["companies"][0]["market_kpi"]
        self.assertTrue(all(metric["status"] == "missing" for metric in market.values()))

    def test_one_year_selection_keeps_precalculated_comparison_metrics(self):
        rows = []
        for year, revenue_growth, roa in ((2024, 5.0, 8.0), (2025, 10.88, 8.36)):
            row = {column: pd.NA for column in FINAL_COLUMNS}
            row.update(
                {
                    "기업명": "삼성전자",
                    "분석유형": "일반기업",
                    "연도": year,
                    "매출성장": revenue_growth,
                    "영업이익성장": 33.23 if year == 2025 else 4.0,
                    "당기순이익성장": 31.22 if year == 2025 else 3.0,
                    "ROA": roa,
                }
            )
            rows.append(row)

        selected = select_output_periods(pd.DataFrame(rows), number_of_years=1)

        self.assertEqual(selected.iloc[0]["매출성장"], 10.88)
        self.assertEqual(selected.iloc[0]["영업이익성장"], 33.23)
        self.assertEqual(selected.iloc[0]["당기순이익성장"], 31.22)
        self.assertEqual(selected.iloc[0]["ROA"], 8.36)

    def test_financial_and_insurance_kpis_follow_industry(self):
        base = self.financial_frame().iloc[-1].to_dict()
        finance = {
            **base,
            "기업명": "테스트은행",
            "분석유형": "금융업",
            "순이자손익": 500,
            "순수수료손익": 120,
        }
        insurance = {
            **base,
            "기업명": "테스트보험",
            "분석유형": "보험업",
            "보험서비스수익": 900,
            "보험서비스손익": 90,
            "보험서비스마진": 10.0,
            "보험서비스수익성장": 8.0,
            "투자손익": 70,
        }
        payload = build_kpi_payload(
            pd.DataFrame([finance, insurance]), pd.DataFrame(), "1y"
        )
        companies = {item["company"]: item for item in payload["companies"]}

        self.assertEqual(
            companies["테스트은행"]["financial_kpi"]["net_interest_income"]["value"],
            500.0,
        )
        self.assertEqual(
            companies["테스트보험"]["financial_kpi"]["insurance_margin"]["value"],
            10.0,
        )
        self.assertEqual(
            companies["테스트은행"]["financial_kpi"]["insurance_margin"]["status"],
            "not_applicable",
        )


if __name__ == "__main__":
    unittest.main()
