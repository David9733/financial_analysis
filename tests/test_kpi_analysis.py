from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import Mock

import pandas as pd

from src.financial_analysis import (
    FINAL_COLUMNS,
    RAW_COLUMNS,
    calculate_metrics,
    extract_source_accounts,
    select_output_periods,
)
from src.kpi_analysis import _financial_trends, build_kpi_payload
from src.dart_api import CompanyNotFoundError
from src.main import _query_years, _resolve_company_inputs
from src.star_score import GROWTH_ANCHORS, build_star_score, interpolate_score


class KPIAnalysisTests(unittest.TestCase):
    def test_multiple_invalid_company_names_return_all_similar_company_guides(self):
        client = Mock()
        client.find_company.side_effect = [
            {
                "corp_code": "00126380",
                "corp_name": "삼성전자",
                "stock_code": "005930",
            },
            CompanyNotFoundError(
                "입력한 기업명 '롯데웰프드'을(를) 정확히 찾을 수 없습니다. "
                "비슷한 기업: 롯데웰푸드, 롯데푸드"
            ),
            CompanyNotFoundError(
                "입력한 기업명 '에스케하이닉스'을(를) 정확히 찾을 수 없습니다. "
                "비슷한 기업: SK하이닉스"
            ),
        ]

        with self.assertRaises(CompanyNotFoundError) as raised:
            _resolve_company_inputs(
                client, ["삼성전자", "롯데웰프드", "에스케하이닉스"]
            )

        message = str(raised.exception)
        self.assertEqual(message.count("기업명을 확인해 주세요."), 1)
        self.assertEqual(
            message,
            "기업명을 확인해 주세요.\n"
            "- '롯데웰프드' → 비슷한 기업: 롯데웰푸드, 롯데푸드\n"
            "- '에스케하이닉스' → 비슷한 기업: SK하이닉스",
        )
        self.assertEqual(client.find_company.call_count, 3)

    def test_dart_comparative_amount_restores_missing_financial_year(self):
        def row(statement, account_id, name, current, previous):
            return {
                "sj_div": statement,
                "account_id": account_id,
                "account_nm": name,
                "thstrm_amount": str(current),
                "frmtrm_amount": str(previous),
                "currency": "KRW",
                "rcept_no": "20230001",
            }

        statement_rows = [
            row("CIS", "dart_OperatingIncomeLoss", "영업이익", 120, 100),
            row("CIS", "ifrs-full_ProfitLoss", "당기순이익", 100, 80),
            row("BS", "ifrs-full_Assets", "자산총계", 1200, 1000),
            row("BS", "ifrs-full_Liabilities", "부채총계", 700, 600),
            row("BS", "ifrs-full_Equity", "자본총계", 500, 400),
            row("CIS", "ifrs-full_InterestRevenueExpense", "순이자손익", 60, 50),
            row("CIS", "ifrs-full_FeeAndCommissionIncomeExpense", "순수수료손익", 25, 20),
        ]
        records = extract_source_accounts(
            "테스트금융", 2023, "CFS", statement_rows
        ) + extract_source_accounts(
            "테스트금융",
            2022,
            "CFS",
            statement_rows,
            amount_field="frmtrm_amount",
            log_missing=False,
        )

        metrics = calculate_metrics(pd.DataFrame(records, columns=RAW_COLUMNS))
        latest = metrics.loc[metrics["연도"] == 2023].iloc[0]

        self.assertEqual(metrics["연도"].tolist(), [2022, 2023])
        self.assertAlmostEqual(latest["영업이익성장"], 20.0)
        self.assertAlmostEqual(latest["당기순이익성장"], 25.0)
        self.assertAlmostEqual(latest["ROE"], 22.22)
        self.assertAlmostEqual(latest["ROA"], 9.09)

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

        self.assertEqual(payload["schema_version"], "1.7")
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
        self.assertEqual(
            [axis["key"] for axis in company["star_score"]],
            ["growth", "profitability", "stability", "efficiency", "market"],
        )
        self.assertTrue(
            all(
                axis["status"] == "available" and 0 <= axis["score"] <= 100
                for axis in company["star_score"]
            )
        )

    def test_star_score_interpolates_and_clamps_fixed_anchors(self):
        self.assertEqual(interpolate_score(-100.0, GROWTH_ANCHORS), 0.0)
        self.assertEqual(interpolate_score(100.0, GROWTH_ANCHORS), 100.0)
        self.assertEqual(interpolate_score(5.0, GROWTH_ANCHORS), 62.5)

    def test_financial_company_uses_sector_proxies(self):
        rows = pd.DataFrame(
            [
                {
                    "연도": year,
                    "순이자손익": interest,
                    "순수수료손익": fee,
                    "당기순이익": profit,
                    "총자산": assets,
                    "자본총계": equity,
                    "총자산성장": 5.0,
                }
                for year, interest, fee, profit, assets, equity in (
                    (2023, 80, 20, 30, 900, 70),
                    (2024, 90, 24, 35, 950, 75),
                    (2025, 105, 28, 40, 1000, 80),
                )
            ]
        )
        financial = {
            "net_income_growth": {"value": 14.3, "status": "available"},
            "roe": {"value": 10.0, "status": "available"},
            "roa": {"value": 4.0, "status": "available"},
        }
        market = {
            "period_return": {"value": 12.0, "status": "available"},
            "price_to_ma20": {"value": 3.0, "status": "available"},
            "daily_volatility": {"value": 1.5, "status": "available"},
        }
        macro = {"market_index_change": {"value": 5.0, "status": "available"}}

        axes = build_star_score("금융업", rows, financial, {}, market, macro)

        self.assertTrue(all(axis["status"] == "available" for axis in axes))
        self.assertTrue(next(axis for axis in axes if axis["key"] == "stability")["is_proxy"])
        self.assertTrue(next(axis for axis in axes if axis["key"] == "efficiency")["is_proxy"])

    def test_star_axis_requires_half_of_planned_weight(self):
        rows = pd.DataFrame([{"연도": 2025, "매출채권회전일수": pd.NA}])
        axes = build_star_score("일반기업", rows, {}, {}, {}, {})

        self.assertTrue(all(axis["status"] == "insufficient_data" for axis in axes))

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
        client.get_annual_financials.return_value = ([{"account_id": "test"}], "CFS")

        collected = _query_years(client, "001", "테스트전자", None, None, 1)

        self.assertEqual(len(collected), 4)
        self.assertEqual(client.get_annual_financials.call_count, 4)

    def test_empty_annual_response_does_not_count_as_collected_year(self):
        client = Mock()
        client.get_annual_financials.side_effect = [
            ([], "CFS"),
            *[([{"account_id": str(index)}], "CFS") for index in range(4)],
        ]

        collected = _query_years(client, "001", "테스트전자", None, None, 1)

        self.assertEqual(len(collected), 4)
        self.assertEqual(client.get_annual_financials.call_count, 5)

    def test_year_queries_run_with_at_most_three_workers(self):
        class ConcurrentClient:
            def __init__(self):
                self.active = 0
                self.maximum_active = 0
                self.lock = threading.Lock()

            def get_annual_financials(self, corp_code, year):
                with self.lock:
                    self.active += 1
                    self.maximum_active = max(self.maximum_active, self.active)
                time.sleep(0.03)
                with self.lock:
                    self.active -= 1
                return ([{"account_id": str(year)}], "CFS")

        client = ConcurrentClient()

        collected = _query_years(client, "001", "테스트전자", 2021, 2025, 5)

        # 첫 표시 연도의 성장률 계산에 필요한 직전 연도까지 수집한다.
        self.assertEqual([year for year, _, _ in collected], list(range(2020, 2026)))
        self.assertEqual(client.maximum_active, 3)

    def test_display_period_does_not_change_financial_trend_or_star_axes(self):
        trend_source = self.financial_frame()
        oldest = trend_source.iloc[0].copy()
        oldest["연도"] = 2023
        oldest["매출성장"] = 2.0
        oldest["영업이익성장"] = 3.0
        oldest["당기순이익성장"] = 4.0
        trend_source = pd.concat(
            [oldest.to_frame().T, trend_source], ignore_index=True
        )
        results = []
        for years in (1, 2, 3):
            displayed = trend_source.tail(years).copy()
            payload = build_kpi_payload(
                displayed,
                self.stock_frame(),
                "1y",
                financial_trend_source=trend_source,
            )
            company = payload["companies"][0]
            results.append(
                (
                    company["financial_trend"],
                    [
                        (axis["key"], axis["score"], axis["status"])
                        for axis in company["star_score"]
                        if axis["key"] != "market"
                    ],
                )
            )

        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1], results[2])

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

    def test_volume_history_supplies_lookback_kpis(self):
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
        self.assertEqual(market["price_to_ma20"]["status"], "available")
        self.assertEqual(market["bollinger_position"]["status"], "available")
        self.assertEqual(
            market["start_date"]["value"],
            selected["기준일"].min().date().isoformat(),
        )
        self.assertEqual(market["average_volume"]["value"], round(selected["거래량"].mean()))

    def test_short_selection_uses_history_for_moving_average_kpis(self):
        history = self.stock_frame().copy()
        selected = history.tail(15).copy()

        payload = build_kpi_payload(
            self.financial_frame(),
            selected,
            "1m",
            volume_history=history,
        )
        market = payload["companies"][0]["market_kpi"]

        moving_average = history["종가"].tail(20).mean()
        expected = round(
            (history["종가"].iloc[-1] - moving_average) / moving_average * 100, 2
        )
        self.assertEqual(market["price_to_ma20"]["status"], "available")
        self.assertEqual(market["price_to_ma20"]["value"], expected)
        self.assertEqual(market["bollinger_position"]["status"], "available")

    def test_short_radar_window_explains_insufficient_rolling_values(self):
        from src.kpi_analysis import _macro_radar_metrics

        size = 18
        index = pd.RangeIndex(size)
        company = pd.Series([(-1) ** step * (step + 1) for step in range(size)], index=index, dtype="float64")
        market = company * 0.5
        macro = company * 0.8 + 0.1
        valid = pd.Series(True, index=index)
        valid.iloc[0] = False

        result = _macro_radar_metrics(
            "usd_krw", company, market, macro, valid, valid, 0.9, None, None, "1m"
        )

        persistence = result["radar_usd_krw_sign_persistence"]
        self.assertEqual(persistence["status"], "no_comparison_period")
        self.assertIn("10거래일 이동상관 값이", persistence["reason"])
        self.assertIn("3개월 이상", persistence["reason"])

    def test_short_selection_without_history_marks_moving_average_kpis(self):
        selected = self.stock_frame().tail(15).copy()

        payload = build_kpi_payload(self.financial_frame(), selected, "1m")
        market = payload["companies"][0]["market_kpi"]

        for key in ("price_to_ma20", "bollinger_position"):
            self.assertEqual(market[key]["status"], "no_comparison_period")
            self.assertIsNone(market[key]["value"])

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
