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
    format_result_for_csv,
    select_output_periods,
)
from src.app import build_financial_kpi_matrix, format_kpi_metric
from src.kpi_analysis import _financial_trends, build_kpi_payload
from src.dart_api import CompanyNotFoundError
from src.main import _query_years, _resolve_company_inputs
from src.star_score import (
    GROWTH_ANCHORS,
    _growth,
    build_star_score,
    interpolate_score,
)


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
    def raw_record(company, year, key, amount):
        return {
            "기업명": company,
            "연도": year,
            "재무제표구분": "CFS",
            "원천항목": key,
            "계정ID": "",
            "계정명": "",
            "재무제표종류": "",
            "금액": amount,
            "통화": "KRW",
            "접수번호": "",
        }

    def test_growth_from_negative_base_is_labeled_instead_of_sign_flipped(self):
        def record(year, key, amount):
            return self.raw_record("테스트전환", year, key, amount)

        records = []
        for year, revenue, operating_profit, net_income in (
            (2023, 1000, -100, -20),
            (2024, 1100, 50, -30),
        ):
            records += [
                record(year, "revenue", revenue),
                record(year, "operating_profit", operating_profit),
                record(year, "net_income", net_income),
                record(year, "assets", 2000),
                record(year, "liabilities", 1000),
                record(year, "equity", 1000),
            ]

        metrics = calculate_metrics(pd.DataFrame(records, columns=RAW_COLUMNS))
        latest = metrics.loc[metrics["연도"] == 2024].iloc[0]

        # -100 → 50을 그대로 계산하면 -150%가 되어 감소로 읽힌다.
        self.assertTrue(pd.isna(latest["영업이익성장"]))
        self.assertTrue(pd.isna(latest["당기순이익성장"]))
        self.assertAlmostEqual(latest["매출성장"], 10.0)
        display = format_result_for_csv(metrics)
        self.assertEqual(display.loc[1, "영업이익성장"], "흑자전환")
        self.assertEqual(display.loc[1, "당기순이익성장"], "적자지속")
        self.assertNotIn("_영업이익성장비고", display.columns)

        payload = build_kpi_payload(
            select_output_periods(metrics, number_of_years=1),
            pd.DataFrame(),
            "1y",
            financial_trend_source=metrics,
        )
        financial_kpi = payload["companies"][0]["financial_kpi"]
        self.assertEqual(financial_kpi["operating_profit_growth"]["status"], "negative_base")
        self.assertEqual(financial_kpi["operating_profit_growth"]["reason"], "흑자전환")
        self.assertEqual(format_kpi_metric(financial_kpi["net_income_growth"]), "적자지속")
        self.assertEqual(financial_kpi["revenue_growth"]["status"], "available")

    def test_growth_trend_badge_uses_amounts_through_turnaround_year(self):
        def record(year, key, amount):
            return self.raw_record("테스트반등", year, key, amount)

        # SK하이닉스처럼 2023년 적자 뒤 흑자전환한 경우
        records = []
        for year, revenue, operating_profit in (
            (2022, 1000, 300),
            (2023, 900, -100),
            (2024, 1100, 50),
            (2025, 1000, 80),
        ):
            records += [
                record(year, "revenue", revenue),
                record(year, "operating_profit", operating_profit),
                record(year, "net_income", operating_profit),
                record(year, "assets", 2000),
                record(year, "liabilities", 1000),
                record(year, "equity", 1000),
            ]
        metrics = calculate_metrics(pd.DataFrame(records, columns=RAW_COLUMNS))

        payload = build_kpi_payload(
            select_output_periods(metrics, number_of_years=1),
            pd.DataFrame(),
            "1y",
            financial_trend_source=metrics,
        )
        trend = payload["companies"][0]["financial_trend"]

        # 2024년 성장률은 흑자전환으로 비어 있지만 금액 -100 → 50 → 80으로 판정한다.
        self.assertEqual(trend["operating_profit_growth"]["status"], "available")
        self.assertEqual(trend["operating_profit_growth"]["value"], "개선")
        self.assertEqual(trend["operating_profit_growth"]["values"], [-100.0, 50.0, 80.0])
        self.assertEqual(trend["operating_profit_growth"]["periods"], ["2023", "2024", "2025"])
        # 매출 900 → 1100 → 1000은 오르내림이 섞여 변동이다.
        self.assertEqual(trend["revenue_growth"]["value"], "변동")
        # 2024년 성장률이 흑자전환으로 비어 있어 성장 속도를 비교하지 않는다.
        self.assertFalse(trend["operating_profit_growth"]["slowdown"])

    def test_growth_trend_marks_slowdown_when_amount_rises_more_slowly(self):
        def record(year, key, amount):
            return self.raw_record("테스트둔화", year, key, amount)

        # 영업이익은 3년 연속 늘지만 성장률은 25% → 6.4%로 낮아지고,
        # 매출은 성장률이 10% → 20%로 높아진다(KB금융 영업이익과 같은 형태).
        records = []
        for year, revenue, operating_profit in (
            (2022, 1000, 80),
            (2023, 1100, 100),
            (2024, 1210, 125),
            (2025, 1452, 133),
        ):
            records += [
                record(year, "revenue", revenue),
                record(year, "operating_profit", operating_profit),
                record(year, "net_income", operating_profit),
                record(year, "assets", 2000),
                record(year, "liabilities", 1000),
                record(year, "equity", 1000),
            ]
        metrics = calculate_metrics(pd.DataFrame(records, columns=RAW_COLUMNS))
        payload = build_kpi_payload(
            select_output_periods(metrics, number_of_years=1),
            pd.DataFrame(),
            "1y",
            financial_trend_source=metrics,
        )
        trend = payload["companies"][0]["financial_trend"]

        self.assertEqual(trend["operating_profit_growth"]["value"], "개선")
        self.assertTrue(trend["operating_profit_growth"]["slowdown"])
        self.assertEqual(trend["revenue_growth"]["value"], "개선")
        self.assertFalse(trend["revenue_growth"]["slowdown"])

        matrix = build_financial_kpi_matrix(payload)
        rows = {row["key"]: row for row in matrix["rows"]}
        self.assertEqual(rows["operating_profit_growth"]["badges"], ["개선 · 둔화"])
        self.assertEqual(rows["operating_profit_growth"]["badge_tones"], ["improving"])
        self.assertEqual(rows["revenue_growth"]["badges"], ["개선"])
        self.assertIsNone(_growth(50, -100))
        self.assertIsNone(_growth(50, 0))
        self.assertAlmostEqual(_growth(150, 100), 50.0)

    def test_capital_impairment_is_labeled_and_scores_zero_stability(self):
        def record(year, key, amount):
            return self.raw_record("테스트잠식", year, key, amount)

        records = []
        for year, equity in ((2023, -100), (2024, -200)):
            records += [
                record(year, "revenue", 1000),
                record(year, "operating_profit", 50),
                record(year, "net_income", -100),
                record(year, "assets", 1000),
                record(year, "liabilities", 1000 - equity),
                record(year, "equity", equity),
                # 이자지급액을 음수(유출)로 공시한 경우
                record(year, "interest_paid", -25),
            ]

        metrics = calculate_metrics(pd.DataFrame(records, columns=RAW_COLUMNS))
        latest = metrics.loc[metrics["연도"] == 2024].iloc[0]

        # 그대로 계산하면 부채비율 -600%, ROE +66.67%가 된다.
        self.assertTrue(pd.isna(latest["부채비율"]))
        self.assertTrue(pd.isna(latest["ROE"]))
        self.assertAlmostEqual(latest["이자보상배율"], 2.0)
        display = format_result_for_csv(metrics)
        self.assertEqual(display.loc[1, "부채비율"], "자본잠식")
        self.assertEqual(display.loc[1, "ROE"], "자본잠식")

        payload = build_kpi_payload(
            select_output_periods(metrics, number_of_years=1),
            pd.DataFrame(),
            "1y",
            financial_trend_source=metrics,
        )
        company = payload["companies"][0]
        self.assertEqual(format_kpi_metric(company["financial_kpi"]["debt_ratio"]), "자본잠식")
        self.assertEqual(company["financial_kpi"]["roe"]["status"], "negative_base")
        stability = next(axis for axis in company["star_score"] if axis["key"] == "stability")
        # 부채비율 0점 50% + 이자보상배율 2배(50점) 50% = 25점
        self.assertEqual(stability["score"], 25)
        self.assertIn({"label": "부채비율", "value": "자본잠식"}, stability["evidence"])

    def test_financial_star_growth_skips_non_consecutive_previous_year(self):
        def rows(years):
            return pd.DataFrame(
                [
                    {
                        "연도": year,
                        "순이자손익": interest,
                        "순수수료손익": 100,
                        "총자산": 10_000,
                        "자본총계": 800,
                        "당기순이익": 50,
                    }
                    for year, interest in zip(years, (100, 150))
                ]
            )

        def growth_axis(years):
            axes = build_star_score("금융업", rows(years), {}, {}, {}, {})
            return next(axis for axis in axes if axis["key"] == "growth")

        labels = lambda axis: {item["label"] for item in axis["evidence"]}
        # 2023→2024는 1년 성장률이지만 2021→2024는 3년 변화라 성장률로 쓰지 않는다.
        self.assertIn("순이자손익 성장률", labels(growth_axis((2023, 2024))))
        self.assertEqual(growth_axis((2021, 2024))["status"], "insufficient_data")

    def test_interest_paid_classified_as_financing_activity_is_selected(self):
        rows = [
            {
                "sj_div": "CF",
                "account_id": "ifrs-full_InterestPaidClassifiedAsFinancingActivities",
                "account_nm": "이자지급",
                "thstrm_amount": "30",
            }
        ]
        records = extract_source_accounts("테스트", 2024, "CFS", rows, log_missing=False)
        interest = next(item for item in records if item["원천항목"] == "interest_paid")

        self.assertEqual(interest["금액"], 30.0)

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

    def test_year_queries_report_progress_for_each_checked_year(self):
        client = Mock()
        client.get_annual_financials.side_effect = [
            ([], "CFS"),
            *[([{"account_id": str(index)}], "CFS") for index in range(4)],
        ]
        reports = []

        _query_years(
            client,
            "001",
            "테스트전자",
            None,
            None,
            1,
            on_year_checked=lambda year, fraction: reports.append(fraction),
        )

        # 빈 연도까지 5번 확인하지만 필요한 4개 기준이라 비율은 1을 넘지 않는다.
        self.assertEqual(len(reports), 5)
        self.assertEqual(reports, sorted(reports))
        self.assertEqual(reports[-1], 1.0)
        self.assertTrue(all(0 < fraction <= 1 for fraction in reports))

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
