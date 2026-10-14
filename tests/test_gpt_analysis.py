from __future__ import annotations

import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.gpt_analysis import (
    CompanyInsight,
    ComparisonInsight,
    GPTAnalysisError,
    InsightSection,
    KPIInsightResponse,
    MetricReference,
    analyze_kpis,
    build_fallback_insights,
    get_openai_api_key,
)


class GPTAnalysisTests(unittest.TestCase):
    @staticmethod
    def payload():
        return {
            "companies": [
                {
                    "company": "테스트전자",
                    "financial_period": "2025",
                    "financial_kpi": {
                        "roe": {"value": 10.2, "unit": "%", "status": "available", "reason": None},
                        "debt_ratio": {"value": None, "unit": "%", "status": "missing", "reason": "출처 데이터 없음"},
                    },
                    "market_kpi": {
                        "period_return": {"value": 5.4, "unit": "%", "status": "available", "reason": None}
                    },
                }
            ]
        }

    @staticmethod
    def parsed(evidence_key="roe", summary="ROE는 10.2%입니다."):
        section = InsightSection(summary=summary, evidence_keys=[evidence_key])
        return KPIInsightResponse(
            analyses=[
                CompanyInsight(
                    company="테스트전자",
                    one_line_summary=section,
                    data_basis="2025년 재무 데이터 기준",
                    growth=section,
                    profitability=section,
                    stability=section,
                    efficiency=section,
                    market=section,
                    financial_scenario=section,
                    relationships_and_mismatches=[section],
                    positive_signals=[section],
                    caution_signals=[],
                    additional_checks=[
                        InsightSection(
                            summary="최근 공시를 추가 확인할 필요가 있습니다.",
                            evidence_keys=[evidence_key],
                        )
                    ],
                    overall_summary=section,
                )
            ],
            comparisons=[],
        )

    def test_multi_company_fallback_handles_aligned_and_mixed_stability_trends(self):
        payload = self.payload()
        first = payload["companies"][0]
        first["company"] = "개선기업"
        first["financial_trend"] = {
            "debt_ratio": {
                "value": "개선", "unit": "", "status": "available", "reason": None
            },
            "interest_coverage_ratio": {
                "value": "개선", "unit": "", "status": "available", "reason": None
            },
        }
        second = deepcopy(first)
        second["company"] = "혼재기업"
        second["financial_trend"]["debt_ratio"]["value"] = "악화"
        payload["companies"].append(second)

        result = build_fallback_insights(payload)

        self.assertEqual(
            [analysis["company"] for analysis in result["analyses"]],
            ["개선기업", "혼재기업"],
        )
        self.assertGreaterEqual(len(result["comparisons"]), 1)
        summaries = {
            analysis["company"]: analysis["overall_summary"]["summary"]
            for analysis in result["analyses"]
        }
        self.assertNotIn("혼재", summaries["개선기업"])
        self.assertIn("모두 개선", summaries["개선기업"])
        self.assertIn("혼재", summaries["혼재기업"])

    def test_fallback_accepts_mixed_growth_trend_summary(self):
        payload = self.payload()
        payload["companies"][0]["financial_trend"] = {
            "revenue_growth": {
                "value": "변동", "unit": "", "status": "available", "reason": None
            },
            "operating_profit_growth": {
                "value": "개선", "unit": "", "status": "available", "reason": None
            },
            "net_income_growth": {
                "value": "개선", "unit": "", "status": "available", "reason": None
            },
        }

        result = build_fallback_insights(payload)

        self.assertIn("최근 3년 성장률 추세", result["analyses"][0]["growth"]["summary"])

    def test_multi_company_fallback_builds_category_comparisons(self):
        payload = self.payload()
        first = payload["companies"][0]
        first["company"] = "성장기업"
        first["financial_kpi"].update(
            {
                "revenue_growth": {
                    "value": 20.0, "unit": "%", "status": "available", "reason": None
                },
                "operating_margin": {
                    "value": 15.0, "unit": "%", "status": "available", "reason": None
                },
                "accounts_receivable_days": {
                    "value": 40.0, "unit": "일", "status": "available", "reason": None
                },
            }
        )
        first["financial_kpi"]["debt_ratio"] = {
            "value": 30.0, "unit": "%", "status": "available", "reason": None
        }
        first["market_kpi"]["market_index_change"] = {
            "value": 6.0, "unit": "%", "status": "available", "reason": None
        }
        second = deepcopy(first)
        second["company"] = "안정기업"
        second["financial_kpi"]["revenue_growth"]["value"] = 10.0
        second["financial_kpi"]["operating_margin"]["value"] = 12.0
        second["financial_kpi"]["debt_ratio"]["value"] = 20.0
        second["financial_kpi"]["accounts_receivable_days"]["value"] = 35.0
        second["market_kpi"]["period_return"]["value"] = 8.0
        payload["companies"].append(second)

        result = build_fallback_insights(payload)

        self.assertEqual(len(result["comparisons"]), 5)
        self.assertEqual(
            [comparison["summary"].split(":", 1)[0] for comparison in result["comparisons"]],
            ["성장성", "수익성", "재무 안정성", "효율성", "시장 흐름"],
        )
        self.assertIn("성장기업", result["comparisons"][0]["summary"])
        self.assertIn("안정기업", result["comparisons"][2]["summary"])
        self.assertIn("매출채권 회전일수가", result["comparisons"][3]["summary"])
        self.assertTrue(
            all(len(comparison["evidence"]) == 2 for comparison in result["comparisons"])
        )
        analyses = {analysis["company"]: analysis for analysis in result["analyses"]}
        self.assertIn("비교 시장지수보다 낮았습니다", analyses["성장기업"]["market"]["summary"])
        self.assertIn("비교 시장지수보다 높았습니다", analyses["안정기업"]["market"]["summary"])

    def test_missing_api_key_has_clear_error(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {}, clear=True
        ):
            with self.assertRaisesRegex(GPTAnalysisError, "OPENAI_API_KEY"):
                get_openai_api_key(Path(directory))

    def test_legacy_gpt_key_is_supported(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"GPT_KEY": "legacy-key"}, clear=True
        ):
            self.assertEqual(get_openai_api_key(Path(directory)), "legacy-key")

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_uses_responses_parse_without_storage(self, _api_key):
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            output_parsed=self.parsed(), output=[]
        )
        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(self.payload(), Path("."))

        self.assertEqual(result["analyses"][0]["company"], "테스트전자")
        self.assertNotIn("macro_outlook", result["analyses"][0])
        self.assertEqual(result["comparisons"], [])
        kwargs = client.responses.parse.call_args.kwargs
        self.assertFalse(kwargs["store"])
        self.assertIs(kwargs["text_format"], KPIInsightResponse)
        self.assertIn("15년 이상의 실무 경험", kwargs["instructions"])
        self.assertIn("원/달러 환율 상승은 원화 약세", kwargs["instructions"])
        self.assertIn("재무 체질과 금리 상승 및 원화 약세", kwargs["instructions"])
        self.assertNotIn("macro_outlook", kwargs["instructions"])
        self.assertIsInstance(kwargs["input"], str)

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_removes_unavailable_evidence_key_without_discarding_analysis(self, _api_key):
        payload = self.payload()
        payload["companies"][0]["financial_history"] = [
            {
                "period": "2023",
                "financial_kpi": {
                    "revenue_growth": {
                        "value": None,
                        "unit": "%",
                        "status": "missing",
                        "reason": "비교연도 없음",
                    }
                },
            }
        ]
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            output_parsed=self.parsed(
                evidence_key="financial_history.2023.revenue_growth",
                summary="확인이 필요합니다.",
            ),
            output=[],
        )
        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(payload, Path("."))

        self.assertEqual(client.responses.parse.call_count, 3)
        self.assertEqual(result["analyses"][0]["profitability"]["evidence_keys"], [])
        self.assertIn(
            "사용 가능한 KPI",
            result["analyses"][0]["profitability"]["summary"],
        )

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_repairs_numeric_claim_not_in_payload_after_retries(self, _api_key):
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            output_parsed=self.parsed(summary="ROE는 99.9%입니다."), output=[]
        )
        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(self.payload(), Path("."))

        self.assertEqual(client.responses.parse.call_count, 3)
        self.assertNotIn("99.9", result["analyses"][0]["profitability"]["summary"])
        self.assertEqual(
            result["analyses"][0]["profitability"]["evidence_keys"], ["roe"]
        )

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_repairs_investment_recommendation_language_after_retries(self, _api_key):
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            output_parsed=self.parsed(summary="이 종목을 매수해야 합니다."), output=[]
        )
        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(self.payload(), Path("."))

        self.assertNotIn("매수", result["analyses"][0]["profitability"]["summary"])

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_repairs_acquisition_recommendation_language_after_retries(self, _api_key):
        client = Mock()
        parsed = self.parsed()
        parsed.analyses[0].overall_summary = InsightSection(
            summary="이 기업을 인수해야 합니다.", evidence_keys=["roe"]
        )
        client.responses.parse.return_value = SimpleNamespace(
            output_parsed=parsed, output=[]
        )
        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(self.payload(), Path("."))

        self.assertNotIn("인수해야", result["analyses"][0]["overall_summary"]["summary"])

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_normalizes_prefixed_market_key_and_negative_magnitude(self, _api_key):
        payload = self.payload()
        payload["companies"][0]["stock_period"] = "1y"
        payload["companies"][0]["market_kpi"]["recent_volume_change"] = {
            "value": -27.42,
            "unit": "%",
            "status": "available",
            "reason": None,
        }
        parsed = self.parsed()
        parsed.analyses[0].market = InsightSection(
            summary="최근 거래량은 27.42% 감소했습니다.",
            evidence_keys=["market_kpi.recent_volume_change"],
        )
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            output_parsed=parsed, output=[]
        )
        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(payload, Path("."))

        self.assertEqual(
            result["analyses"][0]["market"]["evidence_keys"],
            ["recent_volume_change"],
        )

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_accepts_macro_kpi_evidence_and_numbers(self, _api_key):
        payload = self.payload()
        payload["companies"][0]["macro_kpi"] = {
            "corr_return_usd_krw": {
                "value": -0.31,
                "unit": "",
                "status": "available",
                "reason": None,
            }
        }
        parsed = self.parsed()
        parsed.analyses[0].market = InsightSection(
            summary="일간 수익률과 환율 변화의 상관계수는 -0.31로 반대 방향으로 함께 움직이는 경향이 있습니다.",
            evidence_keys=["macro_kpi.corr_return_usd_krw"],
        )
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            output_parsed=parsed, output=[]
        )
        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(payload, Path("."))

        self.assertEqual(client.responses.parse.call_count, 1)
        self.assertEqual(
            result["analyses"][0]["market"]["evidence_keys"],
            ["corr_return_usd_krw"],
        )
        self.assertIn("-0.31", result["analyses"][0]["market"]["summary"])

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_accepts_financial_trend_and_scenario_combined_evidence(self, _api_key):
        payload = self.payload()
        payload["companies"][0]["financial_trend"] = {
            "debt_ratio": {
                "value": "악화",
                "unit": "",
                "status": "available",
                "reason": None,
                "periods": ["2023", "2024", "2025"],
                "values": [40.0, 45.0, 50.0],
            }
        }
        payload["companies"][0]["macro_kpi"] = {
            "weak_krw_rising_rate_days": {
                "value": 8,
                "unit": "일",
                "status": "available",
                "reason": None,
            },
            "weak_krw_rising_rate_sample_quality": {
                "value": "제한적 표본",
                "unit": "",
                "status": "available",
                "reason": None,
            },
            "weak_krw_rising_rate_excess_return": {
                "value": -0.7,
                "unit": "%p",
                "status": "available",
                "reason": None,
            },
        }
        parsed = self.parsed()
        parsed.analyses[0].financial_scenario = InsightSection(
            summary="부채비율 3년 추세는 악화이며, 시나리오 8일 동안 시장보다 -0.7%p 낮았습니다.",
            evidence_keys=[
                "financial_trend.debt_ratio",
                "macro_kpi.weak_krw_rising_rate_days",
                "macro_kpi.weak_krw_rising_rate_sample_quality",
                "macro_kpi.weak_krw_rising_rate_excess_return",
            ],
        )
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            output_parsed=parsed, output=[]
        )

        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(payload, Path("."))

        self.assertEqual(client.responses.parse.call_count, 3)
        self.assertEqual(
            result["analyses"][0]["financial_scenario"]["evidence_keys"],
            [
                "financial_trend.debt_ratio",
                "weak_krw_rising_rate_days",
                "weak_krw_rising_rate_sample_quality",
                "weak_krw_rising_rate_excess_return",
            ],
        )

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_zero_scenario_days_replaces_vulnerability_claim(self, _api_key):
        payload = self.payload()
        payload["companies"][0]["macro_kpi"] = {
            "weak_krw_rising_rate_days": {
                "value": 0,
                "unit": "일",
                "status": "available",
                "reason": None,
            },
            "weak_krw_rising_rate_excess_return": {
                "value": None,
                "unit": "%p",
                "status": "no_comparison_period",
                "reason": "조건 충족 거래일 없음",
            },
        }
        parsed = self.parsed()
        parsed.analyses[0].financial_scenario = InsightSection(
            summary="시장 대비 차이가 없고 부채비율 때문에 취약 가능성이 있습니다.",
            evidence_keys=["roe"],
        )
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            output_parsed=parsed, output=[]
        )

        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(payload, Path("."))

        scenario = result["analyses"][0]["financial_scenario"]
        self.assertEqual(client.responses.parse.call_count, 3)
        self.assertIn("판단할 수 없습니다", scenario["summary"])
        self.assertNotIn("취약", scenario["summary"])
        self.assertEqual(
            scenario["evidence_keys"], ["weak_krw_rising_rate_days"]
        )

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_repairs_change_claim_without_trend_evidence(self, _api_key):
        payload = self.payload()
        payload["companies"][0]["financial_kpi"]["operating_margin"] = {
            "value": 13.07,
            "unit": "%",
            "status": "available",
            "reason": None,
        }
        parsed = self.parsed()
        parsed.analyses[0].profitability = InsightSection(
            summary="영업이익률이 13.07%로 개선되었습니다.",
            evidence_keys=["operating_margin"],
        )
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            output_parsed=parsed, output=[]
        )

        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(payload, Path("."))

        self.assertEqual(client.responses.parse.call_count, 3)
        self.assertNotIn(
            "개선", result["analyses"][0]["profitability"]["summary"]
        )

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_repairs_market_comparison_without_index_evidence(self, _api_key):
        parsed = self.parsed()
        parsed.analyses[0].overall_summary = InsightSection(
            summary="주가는 시장 대비 향상되었습니다.",
            evidence_keys=["period_return"],
        )
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            output_parsed=parsed, output=[]
        )

        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(self.payload(), Path("."))

        self.assertEqual(client.responses.parse.call_count, 3)
        self.assertNotIn(
            "시장 대비", result["analyses"][0]["overall_summary"]["summary"]
        )

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_repairs_relative_volatility_without_benchmark(self, _api_key):
        payload = self.payload()
        payload["companies"][0]["market_kpi"]["daily_volatility"] = {
            "value": 2.8,
            "unit": "%",
            "status": "available",
            "reason": None,
        }
        parsed = self.parsed()
        parsed.analyses[0].market = InsightSection(
            summary="일간 변동성이 2.8%로 상대적으로 높습니다.",
            evidence_keys=["daily_volatility"],
        )
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            output_parsed=parsed, output=[]
        )

        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(payload, Path("."))

        self.assertEqual(client.responses.parse.call_count, 3)
        self.assertNotIn(
            "상대적으로", result["analyses"][0]["market"]["summary"]
        )

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_removes_additional_check_without_kpi_evidence(self, _api_key):
        parsed = self.parsed()
        parsed.analyses[0].additional_checks = [
            InsightSection(
                summary="최근 공시를 추가 확인할 필요가 있습니다.",
                evidence_keys=[],
            )
        ]
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            output_parsed=parsed, output=[]
        )

        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(self.payload(), Path("."))

        self.assertEqual(client.responses.parse.call_count, 1)
        self.assertEqual(result["analyses"][0]["additional_checks"], [])

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_repairs_mixed_stability_and_false_mismatch_claims(self, _api_key):
        payload = self.payload()
        payload["companies"][0]["financial_trend"] = {
            "debt_ratio": {
                "value": "악화",
                "unit": "",
                "status": "available",
                "reason": None,
            },
            "interest_coverage_ratio": {
                "value": "개선",
                "unit": "",
                "status": "available",
                "reason": None,
            },
            "revenue_growth": {
                "value": "변동",
                "unit": "",
                "status": "available",
                "reason": None,
            },
            "operating_profit_growth": {
                "value": "변동",
                "unit": "",
                "status": "available",
                "reason": None,
            },
        }
        parsed = self.parsed()
        parsed.analyses[0].one_line_summary = InsightSection(
            summary="재무 안정성에 대한 우려가 존재합니다.",
            evidence_keys=[
                "financial_trend.debt_ratio",
                "financial_trend.interest_coverage_ratio",
            ],
        )
        parsed.analyses[0].relationships_and_mismatches = [
            InsightSection(
                summary="두 성장률 추세는 상반된 결과입니다.",
                evidence_keys=[
                    "financial_trend.revenue_growth",
                    "financial_trend.operating_profit_growth",
                ],
            )
        ]
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            output_parsed=parsed, output=[]
        )

        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(payload, Path("."))

        self.assertEqual(client.responses.parse.call_count, 3)
        insight = result["analyses"][0]
        self.assertNotIn("우려", insight["one_line_summary"]["summary"])
        self.assertEqual(insight["relationships_and_mismatches"], [])

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_replaces_empty_evidence_and_boilerplate_with_trend_content(self, _api_key):
        payload = self.payload()
        company = payload["companies"][0]
        company["financial_periods"] = ["2025"]
        company["market_kpi"].update(
            {
                "start_date": {
                    "value": "2026-09-11",
                    "unit": "",
                    "status": "available",
                    "reason": None,
                },
                "latest_date": {
                    "value": "2026-10-08",
                    "unit": "",
                    "status": "available",
                    "reason": None,
                },
                "market_index_change": {
                    "value": -4.11,
                    "unit": "%",
                    "status": "available",
                    "reason": None,
                },
            }
        )
        company["macro_kpi"] = {
            "market_index_name": {
                "value": "KOSPI",
                "unit": "",
                "status": "available",
                "reason": None,
            },
            "weak_krw_rising_rate_days": {
                "value": 0,
                "unit": "일",
                "status": "available",
                "reason": None,
            }
        }
        company["financial_kpi"]["operating_profit_growth"] = {
            "value": 33.23,
            "unit": "%",
            "status": "available",
            "reason": None,
        }
        company["financial_trend"] = {
            "operating_margin": {
                "value": "개선", "unit": "", "status": "available", "reason": None
            },
            "debt_ratio": {
                "value": "악화", "unit": "", "status": "available", "reason": None
            },
            "interest_coverage_ratio": {
                "value": "개선", "unit": "", "status": "available", "reason": None
            },
            "accounts_receivable_days": {
                "value": "악화", "unit": "", "status": "available", "reason": None
            },
        }
        parsed = self.parsed()
        parsed.analyses[0].one_line_summary = InsightSection(
            summary="재무 안정성이 양호하지만 부채비율 악화가 우려됩니다.",
            evidence_keys=[],
        )
        parsed.analyses[0].positive_signals = [
            InsightSection(
                summary="제시된 근거 KPI에서 긍정적인 흐름을 확인할 수 있습니다.",
                evidence_keys=["roe"],
            )
        ]
        parsed.analyses[0].caution_signals = [
            InsightSection(
                summary="부채비율 증가가 재무 안정성 리스크가 될 수 있습니다.",
                evidence_keys=["financial_trend.debt_ratio"],
            )
        ]
        parsed.analyses[0].efficiency = InsightSection(
            summary="제시된 효율성 KPI를 확인할 수 있습니다.",
            evidence_keys=["financial_trend.accounts_receivable_days"],
        )
        parsed.analyses[0].relationships_and_mismatches = [
            InsightSection(
                summary="매출 성장과 영업이익률이 함께 개선됐습니다.",
                evidence_keys=["operating_profit_growth"],
            )
        ]
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            output_parsed=parsed, output=[]
        )

        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(payload, Path("."))

        self.assertEqual(client.responses.parse.call_count, 3)
        insight = result["analyses"][0]
        self.assertEqual(
            insight["data_basis"],
            "2025년 재무, 시장 기준 기간: 2026-09-11 ~ 2026-10-08",
        )
        self.assertTrue(insight["one_line_summary"]["evidence_keys"])
        self.assertNotIn("양호", insight["one_line_summary"]["summary"])
        self.assertTrue(insight["positive_signals"])
        self.assertTrue(insight["caution_signals"])
        self.assertNotIn(
            "제시된", insight["positive_signals"][0]["summary"]
        )
        self.assertTrue(
            all("리스크" not in item["summary"] for item in insight["caution_signals"])
        )
        self.assertTrue(
            all("악화으로" not in item["summary"] for item in insight["caution_signals"])
        )
        self.assertTrue(
            any("악화로" in item["summary"] for item in insight["caution_signals"])
        )
        self.assertTrue(
            any(
                "재무 안정성 신호가 혼재" in item["summary"]
                for item in insight["caution_signals"]
            )
        )
        self.assertNotIn("악화으로", insight["efficiency"]["summary"])
        self.assertIn("악화로", insight["efficiency"]["summary"])
        self.assertEqual(insight["relationships_and_mismatches"], [])
        self.assertIn("KOSPI", insight["overall_summary"]["summary"])
        self.assertIn("판단할 수 없습니다", insight["overall_summary"]["summary"])
        self.assertTrue(
            {"period_return", "market_index_change", "weak_krw_rising_rate_days"}
            .issubset(insight["overall_summary"]["evidence_keys"])
        )

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_repairs_quality_growth_wording_and_metric_specific_change_claims(
        self, _api_key
    ):
        payload = self.payload()
        company = payload["companies"][0]
        company["financial_kpi"].update(
            {
                "revenue_growth": {
                    "value": 10.88,
                    "unit": "%",
                    "status": "available",
                    "reason": None,
                },
                "net_income_growth": {
                    "value": 31.22,
                    "unit": "%",
                    "status": "available",
                    "reason": None,
                },
                "interest_coverage_ratio": {
                    "value": 92.82,
                    "unit": "배",
                    "status": "available",
                    "reason": None,
                },
            }
        )
        company["financial_trend"] = {
            "debt_ratio": {
                "value": "악화",
                "unit": "",
                "status": "available",
                "reason": None,
            }
        }
        parsed = self.parsed()
        parsed.analyses[0].growth = InsightSection(
            summary="2025년 매출 성장률은 10.88%로 증가했습니다.",
            evidence_keys=["revenue_growth"],
        )
        parsed.analyses[0].positive_signals = [
            InsightSection(
                summary="2025년 매출 성장률이 10.88%로 양호합니다.",
                evidence_keys=["revenue_growth"],
            )
        ]
        parsed.analyses[0].relationships_and_mismatches = [
            InsightSection(
                summary=(
                    "순이익은 증가했지만, 부채비율 상승과 "
                    "이자보상배율이 함께 개선됐습니다."
                ),
                evidence_keys=[
                    "net_income_growth",
                    "financial_trend.debt_ratio",
                    "interest_coverage_ratio",
                ],
            )
        ]
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            output_parsed=parsed, output=[]
        )

        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(payload, Path("."))

        insight = result["analyses"][0]
        self.assertNotIn("성장률은 10.88%로 증가", insight["growth"]["summary"])
        self.assertTrue(
            all("양호" not in item["summary"] for item in insight["positive_signals"])
        )
        self.assertEqual(insight["relationships_and_mismatches"], [])

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_repairs_broad_growth_stability_and_excessive_summary_evidence(
        self, _api_key
    ):
        payload = self.payload()
        company = payload["companies"][0]
        company["financial_kpi"]["interest_coverage_ratio"] = {
            "value": 92.82,
            "unit": "배",
            "status": "available",
            "reason": None,
        }
        company["financial_trend"] = {
            "revenue_growth": {
                "value": "변동", "unit": "", "status": "available", "reason": None
            },
            "operating_profit_growth": {
                "value": "변동", "unit": "", "status": "available", "reason": None
            },
            "net_income_growth": {
                "value": "변동", "unit": "", "status": "available", "reason": None
            },
            "operating_margin": {
                "value": "개선", "unit": "", "status": "available", "reason": None
            },
            "net_margin": {
                "value": "개선", "unit": "", "status": "available", "reason": None
            },
            "roe": {
                "value": "개선", "unit": "", "status": "available", "reason": None
            },
            "roa": {
                "value": "개선", "unit": "", "status": "available", "reason": None
            },
            "debt_ratio": {
                "value": "악화", "unit": "", "status": "available", "reason": None
            },
            "interest_coverage_ratio": {
                "value": "개선", "unit": "", "status": "available", "reason": None
            },
        }
        parsed = self.parsed()
        parsed.analyses[0].one_line_summary = InsightSection(
            summary=(
                "2025년에는 전반적으로 성장성과 수익성이 향상되었으나, "
                "일부 재무 안정성 지표는 악화되었습니다."
            ),
            evidence_keys=list(
                f"financial_trend.{key}" for key in company["financial_trend"]
            ),
        )
        parsed.analyses[0].positive_signals = [
            InsightSection(
                summary=(
                    "이자보상배율이 높아 재무적 안정성을 가지고 있음을 암시합니다."
                ),
                evidence_keys=["interest_coverage_ratio"],
            )
        ]
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            output_parsed=parsed, output=[]
        )

        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(payload, Path("."))

        insight = result["analyses"][0]
        self.assertLessEqual(len(insight["one_line_summary"]["evidence_keys"]), 4)
        self.assertNotIn("성장성과 수익성이 향상", insight["one_line_summary"]["summary"])
        self.assertTrue(
            all("높아" not in item["summary"] for item in insight["positive_signals"])
        )
        self.assertTrue(
            all(
                "재무적 안정성을 가지고" not in item["summary"]
                for item in insight["positive_signals"]
            )
        )

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_repairs_growth_rate_improvement_volatility_and_year_by_year_wording(
        self, _api_key
    ):
        payload = self.payload()
        company = payload["companies"][0]
        company["financial_period"] = "2025"
        company["financial_kpi"].update(
            {
                "revenue_growth": {
                    "value": 10.88, "unit": "%", "status": "available", "reason": None
                },
                "operating_profit_growth": {
                    "value": 33.23, "unit": "%", "status": "available", "reason": None
                },
                "net_income_growth": {
                    "value": 31.22, "unit": "%", "status": "available", "reason": None
                },
            }
        )
        company["financial_trend"] = {
            key: {
                "value": "변동", "unit": "", "status": "available", "reason": None
            }
            for key in (
                "revenue_growth",
                "operating_profit_growth",
                "net_income_growth",
            )
        }
        parsed = self.parsed()
        parsed.analyses[0].one_line_summary = InsightSection(
            summary=(
                "2025년에 매출과 영업이익, 당기순이익의 성장률이 "
                "10.88%, 33.23%, 31.22%로 향상되었으나, "
                "3년 추세는 변동성을 보였습니다."
            ),
            evidence_keys=[
                "revenue_growth",
                "operating_profit_growth",
                "net_income_growth",
            ],
        )
        parsed.analyses[0].positive_signals = [
            InsightSection(
                summary="연도별 성장률이 모두 양수로 나타났습니다.",
                evidence_keys=[
                    "revenue_growth",
                    "operating_profit_growth",
                    "net_income_growth",
                ],
            )
        ]
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            output_parsed=parsed, output=[]
        )

        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(payload, Path("."))

        insight = result["analyses"][0]
        self.assertEqual(
            insight["one_line_summary"]["summary"],
            "2025년 매출과 영업이익, 당기순이익이 모두 전년 대비 증가했습니다.",
        )
        self.assertEqual(
            insight["positive_signals"][0]["summary"],
            "2025년 매출, 영업이익과 당기순이익 성장률은 모두 양수입니다.",
        )

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_repairs_unsupported_deficit_stability_and_level_trend_mixing(
        self, _api_key
    ):
        payload = self.payload()
        company = payload["companies"][0]
        company["financial_period"] = "2025"
        company["financial_kpi"].update(
            {
                "revenue_growth": {
                    "value": 10.88, "unit": "%", "status": "available", "reason": None
                },
                "operating_profit_growth": {
                    "value": 33.23, "unit": "%", "status": "available", "reason": None
                },
                "net_income_growth": {
                    "value": 31.22, "unit": "%", "status": "available", "reason": None
                },
                "operating_margin": {
                    "value": 13.07, "unit": "%", "status": "available", "reason": None
                },
                "net_margin": {
                    "value": 13.55, "unit": "%", "status": "available", "reason": None
                },
                "debt_ratio": {
                    "value": 29.94, "unit": "%", "status": "available", "reason": None
                },
                "interest_coverage_ratio": {
                    "value": 92.82, "unit": "배", "status": "available", "reason": None
                },
            }
        )
        company["financial_trend"] = {
            "operating_margin": {
                "value": "개선", "unit": "", "status": "available", "reason": None
            },
            "net_margin": {
                "value": "개선", "unit": "", "status": "available", "reason": None
            },
            "debt_ratio": {
                "value": "악화", "unit": "", "status": "available", "reason": None
            },
            "interest_coverage_ratio": {
                "value": "개선", "unit": "", "status": "available", "reason": None
            },
        }
        parsed = self.parsed()
        parsed.analyses[0].one_line_summary = InsightSection(
            summary=(
                "2025년 매출과 이익 모두 전년 대비 증가하였으며, "
                "운영 적자는 개선되고 부채비율이 악화되었습니다."
            ),
            evidence_keys=[
                "revenue_growth",
                "operating_profit_growth",
                "net_income_growth",
                "financial_trend.debt_ratio",
            ],
        )
        parsed.analyses[0].profitability = InsightSection(
            summary=(
                "2025년 영업이익률은 13.07%, 순이익률은 13.55%로 증가했습니다. "
                "3년 추세에서는 안정적으로 개선됩니다."
            ),
            evidence_keys=[
                "operating_margin",
                "net_margin",
                "financial_trend.operating_margin",
                "financial_trend.net_margin",
            ],
        )
        parsed.analyses[0].stability = InsightSection(
            summary=(
                "부채비율은 2025년에 29.94%로 악화되었으며, "
                "이자보상배율은 92.82배로 개선되었습니다."
            ),
            evidence_keys=[
                "debt_ratio",
                "interest_coverage_ratio",
                "financial_trend.debt_ratio",
                "financial_trend.interest_coverage_ratio",
            ],
        )
        parsed.analyses[0].caution_signals = [
            InsightSection(
                summary=(
                    "부채비율이 29.94%로 상승하며 최근 3년 추세도 "
                    "악화로 나타났습니다."
                ),
                evidence_keys=["debt_ratio", "financial_trend.debt_ratio"],
            ),
            InsightSection(
                summary="부채비율이 상승하여 재무 안정성에 유의해야 합니다.",
                evidence_keys=["financial_trend.debt_ratio"],
            ),
        ]
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            output_parsed=parsed, output=[]
        )

        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(payload, Path("."))

        insight = result["analyses"][0]
        self.assertNotIn("적자", insight["one_line_summary"]["summary"])
        self.assertNotIn("안정적으로", insight["profitability"]["summary"])
        self.assertNotIn("29.94%로 악화", insight["stability"]["summary"])
        self.assertIn("부채비율 악화", insight["stability"]["summary"])
        self.assertIn("이자보상배율 개선", insight["stability"]["summary"])
        self.assertTrue(
            all(
                "29.94%로 상승" not in item["summary"]
                for item in insight["caution_signals"]
            )
        )
        self.assertTrue(
            all(
                "재무 안정성에 유의" not in item["summary"]
                for item in insight["caution_signals"]
            )
        )
        self.assertIn("재무 안정성 신호가 혼재", insight["caution_signals"][0]["summary"])

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_repairs_market_return_sign_subject_and_false_growth_mismatch(
        self, _api_key
    ):
        payload = self.payload()
        company = payload["companies"][0]
        company["financial_period"] = "2025"
        company["financial_kpi"].update(
            {
                "revenue_growth": {
                    "value": 10.88, "unit": "%", "status": "available", "reason": None
                },
                "operating_profit_growth": {
                    "value": 33.23, "unit": "%", "status": "available", "reason": None
                },
                "net_income_growth": {
                    "value": 31.22, "unit": "%", "status": "available", "reason": None
                },
                "operating_margin": {
                    "value": 13.07, "unit": "%", "status": "available", "reason": None
                },
            }
        )
        company["market_kpi"].update(
            {
                "market_index_change": {
                    "value": -4.11, "unit": "%", "status": "available", "reason": None
                },
                "latest_close": {
                    "value": 262000, "unit": "원", "status": "available", "reason": None
                },
                "average_close": {
                    "value": 266206, "unit": "원", "status": "available", "reason": None
                },
            }
        )
        parsed = self.parsed()
        parsed.analyses[0].one_line_summary = InsightSection(
            summary=(
                "2025년 매출과 이익에서 긍정적인 성장률을 기록하며 "
                "일부 재무 지표에서는 개선을 나타냈습니다."
            ),
            evidence_keys=[
                "revenue_growth",
                "operating_profit_growth",
                "net_income_growth",
                "operating_margin",
            ],
        )
        parsed.analyses[0].market = InsightSection(
            summary=(
                "최근 1개월 동안 시장 수익률은 5.4% 감소했으나, "
                "최근 주가는 262,000원이고 평균 주가는 266,206원이었습니다."
            ),
            evidence_keys=["period_return", "latest_close", "average_close"],
        )
        parsed.analyses[0].relationships_and_mismatches = [
            InsightSection(
                summary=(
                    "영업이익과 순이익도 증가했지만, 매출 증가율은 10.88%로 "
                    "모든 지표가 개선된 것은 아닙니다."
                ),
                evidence_keys=[
                    "revenue_growth",
                    "operating_profit_growth",
                    "net_income_growth",
                ],
            )
        ]
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            output_parsed=parsed, output=[]
        )

        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(payload, Path("."))

        insight = result["analyses"][0]
        self.assertNotIn("긍정적인 성장률", insight["one_line_summary"]["summary"])
        self.assertIn("주가는 상승", insight["market"]["summary"])
        self.assertIn("시장지수는 하락", insight["market"]["summary"])
        self.assertEqual(insight["relationships_and_mismatches"], [])

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_repairs_long_period_growth_and_receivables_misinterpretations(
        self, _api_key
    ):
        payload = self.payload()
        company = payload["companies"][0]
        company["financial_period"] = "2025"
        company["financial_periods"] = [str(year) for year in range(2016, 2026)]
        company["financial_kpi"].update(
            {
                "revenue_growth": {
                    "value": 10.88, "unit": "%", "status": "available", "reason": None
                },
                "operating_profit_growth": {
                    "value": 33.23, "unit": "%", "status": "available", "reason": None
                },
                "net_income_growth": {
                    "value": 31.22, "unit": "%", "status": "available", "reason": None
                },
                "accounts_receivable_days": {
                    "value": 55.94, "unit": "일", "status": "available", "reason": None
                },
                "interest_coverage_ratio": {
                    "value": 92.82, "unit": "배", "status": "available", "reason": None
                },
            }
        )
        company["financial_history"] = [
            {
                "period": "2023",
                "financial_kpi": {
                    "operating_profit_growth": {
                        "value": -84.86,
                        "unit": "%",
                        "status": "available",
                        "reason": None,
                    }
                },
            },
            {
                "period": "2024",
                "financial_kpi": {
                    "operating_profit_growth": {
                        "value": 398.34,
                        "unit": "%",
                        "status": "available",
                        "reason": None,
                    },
                    "net_income_growth": {
                        "value": 122.45,
                        "unit": "%",
                        "status": "available",
                        "reason": None,
                    },
                },
            },
        ]
        company["financial_trend"] = {
            "operating_margin": {
                "value": "개선", "unit": "", "status": "available", "reason": None
            },
            "operating_profit_growth": {
                "value": "변동", "unit": "", "status": "available", "reason": None
            },
            "net_income_growth": {
                "value": "변동", "unit": "", "status": "available", "reason": None
            },
            "debt_ratio": {
                "value": "악화", "unit": "", "status": "available", "reason": None
            },
            "interest_coverage_ratio": {
                "value": "개선", "unit": "", "status": "available", "reason": None
            },
            "accounts_receivable_days": {
                "value": "악화", "unit": "", "status": "available", "reason": None
            },
        }
        parsed = self.parsed()
        parsed.analyses[0].one_line_summary = InsightSection(
            summary=(
                "2025년까지 매출과 이익은 감소세가 있었으나, 2024년부터 "
                "개선이 나타나며 새로운 성장 가능성을 보이고 있습니다."
            ),
            evidence_keys=[
                "revenue_growth",
                "financial_history.2024.operating_profit_growth",
                "financial_history.2024.net_income_growth",
                "financial_trend.operating_margin",
            ],
        )
        parsed.analyses[0].caution_signals = [
            InsightSection(
                summary="2023년 영업이익 감소율이 -84.86%로 급격히 악화되었습니다.",
                evidence_keys=["financial_history.2023.operating_profit_growth"],
            ),
            InsightSection(
                summary=(
                    "2025년의 accounts_receivable_days의 증가가 긴 지급기간을 "
                    "나타냅니다."
                ),
                evidence_keys=["accounts_receivable_days"],
            ),
        ]
        parsed.analyses[0].efficiency = InsightSection(
            summary=(
                "매출채권 회전 일수는 2025년에 55.94일로 증가하여 "
                "비효율성이 우려되는 상황입니다."
            ),
            evidence_keys=["accounts_receivable_days"],
        )
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            output_parsed=parsed, output=[]
        )

        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(payload, Path("."))

        insight = result["analyses"][0]
        self.assertNotIn("성장 가능성", insight["one_line_summary"]["summary"])
        self.assertTrue(
            all(
                "accounts_receivable_days" not in item["summary"]
                for item in insight["caution_signals"]
            )
        )
        self.assertTrue(
            all("지급기간" not in item["summary"] for item in insight["caution_signals"])
        )
        self.assertNotIn("55.94일로 증가", insight["efficiency"]["summary"])
        self.assertNotIn("비효율성", insight["efficiency"]["summary"])

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_repairs_reversed_year_profitability_and_invented_cost_claims(
        self, _api_key
    ):
        payload = self.payload()
        company = payload["companies"][0]
        company["financial_period"] = "2025"
        company["financial_periods"] = [str(year) for year in range(2016, 2026)]
        company["financial_kpi"].update(
            {
                "revenue_growth": {
                    "value": 10.88, "unit": "%", "status": "available", "reason": None
                },
                "operating_profit_growth": {
                    "value": 33.23, "unit": "%", "status": "available", "reason": None
                },
                "net_income_growth": {
                    "value": 31.22, "unit": "%", "status": "available", "reason": None
                },
                "accounts_receivable_days": {
                    "value": 55.94, "unit": "일", "status": "available", "reason": None
                },
                "interest_coverage_ratio": {
                    "value": 92.82, "unit": "배", "status": "available", "reason": None
                },
                "operating_margin": {
                    "value": 13.07, "unit": "%", "status": "available", "reason": None
                },
                "debt_ratio": {
                    "value": 29.94, "unit": "%", "status": "available", "reason": None
                },
            }
        )
        company["market_kpi"]["recent_volume_change"] = {
            "value": -20.86,
            "unit": "%",
            "status": "available",
            "reason": None,
        }
        company["market_kpi"]["period_return"] = {
            "value": 280.26,
            "unit": "%",
            "status": "available",
            "reason": None,
        }
        company["market_kpi"]["latest_close"] = {
            "value": 262000,
            "unit": "원",
            "status": "available",
            "reason": None,
        }
        company["financial_history"] = [
            {
                "period": "2023",
                "financial_kpi": {
                    "revenue_growth": {
                        "value": -14.33,
                        "unit": "%",
                        "status": "available",
                        "reason": None,
                    },
                    "net_income_growth": {
                        "value": -72.17,
                        "unit": "%",
                        "status": "available",
                        "reason": None,
                    },
                    "accounts_receivable_days": {
                        "value": 51.66,
                        "unit": "일",
                        "status": "available",
                        "reason": None,
                    },
                },
            },
            {
                "period": "2024",
                "financial_kpi": {
                    "revenue_growth": {
                        "value": 16.2,
                        "unit": "%",
                        "status": "available",
                        "reason": None,
                    },
                    "operating_profit_growth": {
                        "value": 398.34,
                        "unit": "%",
                        "status": "available",
                        "reason": None,
                    },
                    "net_income_growth": {
                        "value": 122.45,
                        "unit": "%",
                        "status": "available",
                        "reason": None,
                    },
                },
            },
        ]
        company["financial_trend"] = {
            "revenue_growth": {
                "value": "변동",
                "unit": "",
                "status": "available",
                "reason": None,
                "periods": ["2023", "2024", "2025"],
                "values": [-14.33, 16.2, 10.88],
            },
            "operating_profit_growth": {
                "value": "변동", "unit": "", "status": "available", "reason": None
            },
            "net_income_growth": {
                "value": "변동", "unit": "", "status": "available", "reason": None
            },
            "operating_margin": {
                "value": "개선", "unit": "", "status": "available", "reason": None
            },
            "debt_ratio": {
                "value": "악화", "unit": "", "status": "available", "reason": None
            },
            "interest_coverage_ratio": {
                "value": "개선", "unit": "", "status": "available", "reason": None
            },
            "accounts_receivable_days": {
                "value": "악화", "unit": "", "status": "available", "reason": None
            },
        }
        parsed = self.parsed()
        parsed.analyses[0].one_line_summary = InsightSection(
            summary=(
                "최근 3년간 매출 성장의 변동세를 보이며 운영 효율성과 "
                "수익성 측면에서 개선 신호가 나타났습니다."
            ),
            evidence_keys=[
                "financial_trend.revenue_growth",
                "financial_trend.operating_margin",
            ],
        )
        parsed.analyses[0].positive_signals = [
            InsightSection(
                summary=(
                    "2024년 순이익 성장률이 122.45%로 크게 증가하여 "
                    "수익성이 개선되었습니다."
                ),
                evidence_keys=["financial_history.2024.net_income_growth"],
            ),
            InsightSection(
                summary=(
                    "2025년 이자보상배율은 92.82배로 안정된 수익성을 "
                    "보이고 있습니다."
                ),
                evidence_keys=["interest_coverage_ratio"],
            ),
            InsightSection(
                summary="2025년 영업이익률이 13.07%로 고무적인 결과를 나타냅니다.",
                evidence_keys=["operating_margin"],
            ),
        ]
        parsed.analyses[0].caution_signals = [
            InsightSection(
                summary="지난 2023년 순이익이 -72.17% 감소하여 우려가 가중되고 있습니다.",
                evidence_keys=["financial_history.2023.net_income_growth"],
            ),
            InsightSection(
                summary=(
                    "accounts_receivable_days가 55.94일로 증가하여 "
                    "효율성 우려가 있습니다."
                ),
                evidence_keys=[
                    "accounts_receivable_days",
                    "financial_trend.accounts_receivable_days",
                ],
            ),
            InsightSection(
                summary="매출 성장률의 최근 3년간 변동 위험을 보이고 있습니다.",
                evidence_keys=["financial_trend.revenue_growth"],
            ),
            InsightSection(
                summary="영업이익 피크 이후 두 해 연속 감소세가 지속되었습니다.",
                evidence_keys=["financial_history.2024.operating_profit_growth"],
            ),
        ]
        parsed.analyses[0].growth = InsightSection(
            summary=(
                "2025년에 비해 2024년에 매출이 16.2% 증가했으며, 운영 이익과 "
                "당기순이익도 각각 398.34% 및 122.45% 개선되었습니다."
            ),
            evidence_keys=[
                "financial_history.2024.revenue_growth",
                "financial_history.2024.operating_profit_growth",
                "financial_history.2024.net_income_growth",
            ],
        )
        parsed.analyses[0].market = InsightSection(
            summary=(
                "최근 3년 동안 주가는 5.4% 상승했지만 거래량은 감소세를 보였습니다."
            ),
            evidence_keys=["period_return", "recent_volume_change"],
        )
        parsed.analyses[0].efficiency = InsightSection(
            summary=(
                "2023년 매출채권 회전일수는 51.66일이며 최근 3년 동안 증가했습니다. "
                "이로 인해 현금흐름의 효율성 개선이 필요합니다."
            ),
            evidence_keys=[
                "financial_history.2023.accounts_receivable_days",
                "financial_trend.accounts_receivable_days",
            ],
        )
        parsed.analyses[0].relationships_and_mismatches = [
            InsightSection(
                summary=(
                    "최근 3년간 매출채권 회전일수 증가와 원가 압박으로 인한 "
                    "이익률 감소가 서로 다른 방향을 보였습니다."
                ),
                evidence_keys=[
                    "financial_trend.accounts_receivable_days",
                    "financial_trend.operating_margin",
                ],
            ),
            InsightSection(
                summary="최근 3년 영업이익률은 감소했습니다.",
                evidence_keys=["financial_trend.operating_margin"],
            ),
            InsightSection(
                summary=(
                    "자사 매출과 이익 성장률이 최근 3년간 변동세로 나타났습니다."
                ),
                evidence_keys=["financial_trend.revenue_growth"],
            ),
            InsightSection(
                summary=(
                    "영업이익과 순이익이 증가하는 와중에 부채비율이 "
                    "악화되고 있는 경향이 있습니다."
                ),
                evidence_keys=[
                    "operating_profit_growth",
                    "net_income_growth",
                    "financial_trend.debt_ratio",
                ],
            ),
            InsightSection(
                summary="3년 동안 매출 성장률의 변동성이 나타나고 있습니다.",
                evidence_keys=["financial_trend.revenue_growth"],
            ),
            InsightSection(
                summary="부채비율이 2025년까지 지속적으로 악화되고 있습니다.",
                evidence_keys=["financial_trend.debt_ratio"],
            ),
            InsightSection(
                summary=(
                    "2025년 매출은 전년 대비 10.88% 증가하였으나, 이전 연도들의 "
                    "변동성과 성장 지속성에 주목할 필요가 있습니다."
                ),
                evidence_keys=[
                    "revenue_growth",
                    "financial_trend.revenue_growth",
                ],
            ),
            InsightSection(
                summary=(
                    "영업이익 성장률과 순이익 성장률이 최근 변동성을 보이고 있어 "
                    "추가적인 분석이 필요합니다."
                ),
                evidence_keys=[
                    "financial_trend.operating_profit_growth",
                    "financial_trend.net_income_growth",
                ],
            ),
            InsightSection(
                summary=(
                    "2025년 매출이 전년 대비 10.88% 증가하며 회복세가 이어지는 가운데, "
                    "2023년부터 2024년으로는 Positive 성장을 보였습니다."
                ),
                evidence_keys=[
                    "financial_history.2023.revenue_growth",
                    "financial_history.2024.revenue_growth",
                    "financial_trend.revenue_growth",
                ],
            ),
            InsightSection(
                summary=(
                    "2025년 부채비율은 29.94%로 나타났으나, 최근 3년 제반 추세가 "
                    "악화되었습니다."
                ),
                evidence_keys=["debt_ratio", "financial_trend.debt_ratio"],
            ),
            InsightSection(
                summary="2025년 매출은 전년 대비 10.88% 증가했습니다.",
                evidence_keys=["financial_trend.revenue_growth"],
            ),
            InsightSection(
                summary=(
                    "최근 저조한 성장률에도 불구하고 재무 안정성이 다소 개선되고 "
                    "있음을 나타냅니다."
                ),
                evidence_keys=[
                    "revenue_growth",
                    "operating_profit_growth",
                    "debt_ratio",
                    "interest_coverage_ratio",
                ],
            ),
            InsightSection(
                summary=(
                    "2023년 매출채권 회전일수는 증가하여 효율성이 저하되는 "
                    "추세입니다."
                ),
                evidence_keys=[
                    "financial_history.2023.accounts_receivable_days",
                    "financial_trend.accounts_receivable_days",
                ],
            ),
            InsightSection(
                summary=(
                    "2025년 매출채권 회전일수는 55.94일로 나타났으며, 최근 3년 "
                    "추세는 악화된 것으로 보입니다."
                ),
                evidence_keys=[
                    "accounts_receivable_days",
                    "financial_trend.accounts_receivable_days",
                ],
            ),
            InsightSection(
                summary=(
                    "최근 주가는 262,000 원으로 280.26%의 기간 수익률을 기록했습니다. "
                    "그러나 거래량은 20.86% 감소했습니다."
                ),
                evidence_keys=[
                    "latest_close",
                    "period_return",
                    "recent_volume_change",
                ],
            ),
        ]
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            output_parsed=parsed, output=[]
        )

        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(payload, Path("."))

        insight = result["analyses"][0]
        rendered = str(insight)
        self.assertNotIn("크게", rendered)
        self.assertNotIn("-72.17% 감소", rendered)
        self.assertNotIn("우려가 가중", rendered)
        self.assertNotIn("2025년에 비해 2024년", rendered)
        self.assertNotIn("운영 이익", rendered)
        self.assertNotIn("현금흐름의 효율성", rendered)
        self.assertNotIn("원가 압박", rendered)
        summaries = str(
            [
                section["summary"]
                for name in (
                    "positive_signals",
                    "caution_signals",
                    "relationships_and_mismatches",
                )
                for section in insight[name]
            ]
        )
        self.assertNotIn("accounts_receivable_days", summaries)
        self.assertNotIn("변동 위험", rendered)
        self.assertNotIn("피크", rendered)
        self.assertNotIn("두 해 연속 감소", rendered)
        self.assertNotIn("매출과 이익 성장률", rendered)
        self.assertNotIn("와중에", rendered)
        self.assertNotIn("운영 효율성과", rendered)
        self.assertNotIn("거래량은 감소세", rendered)
        self.assertNotIn("성장률의 변동성", rendered)
        self.assertNotIn("2025년까지 지속적으로 악화", rendered)
        self.assertNotIn("안정된 수익성", rendered)
        self.assertNotIn("성장 지속성에 주목", rendered)
        self.assertNotIn("최근 변동성을", rendered)
        self.assertNotIn("고무적인", rendered)
        self.assertNotIn("회복세가 이어", rendered)
        self.assertNotIn("Positive", rendered)
        self.assertNotIn("제반 추세", rendered)
        self.assertNotIn("저조한", rendered)
        self.assertNotIn("다소 개선", rendered)
        self.assertNotIn("효율성이 저하", rendered)
        self.assertNotIn("악화된 것으로 보", rendered)
        self.assertNotIn("원으로 280.26%", rendered)
        self.assertEqual(insight["relationships_and_mismatches"], [])

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_repairs_vague_long_period_market_and_relationship_claims(
        self, _api_key
    ):
        payload = self.payload()
        company = payload["companies"][0]
        company["financial_period"] = "2025"
        company["financial_kpi"].update(
            {
                "revenue_growth": {
                    "value": 10.88, "unit": "%", "status": "available", "reason": None
                },
                "operating_profit_growth": {
                    "value": 33.23, "unit": "%", "status": "available", "reason": None
                },
                "net_income_growth": {
                    "value": 31.22, "unit": "%", "status": "available", "reason": None
                },
                "operating_margin": {
                    "value": 13.07, "unit": "%", "status": "available", "reason": None
                },
                "net_margin": {
                    "value": 13.55, "unit": "%", "status": "available", "reason": None
                },
                "accounts_receivable_days": {
                    "value": 55.94, "unit": "일", "status": "available", "reason": None
                },
            }
        )
        company["financial_trend"] = {
            "operating_profit_growth": {
                "value": "변동", "unit": "", "status": "available", "reason": None
            },
            "operating_margin": {
                "value": "개선", "unit": "", "status": "available", "reason": None
            },
            "net_margin": {
                "value": "개선", "unit": "", "status": "available", "reason": None
            },
            "roe": {
                "value": "개선", "unit": "", "status": "available", "reason": None
            },
            "roa": {
                "value": "개선", "unit": "", "status": "available", "reason": None
            },
            "debt_ratio": {
                "value": "악화", "unit": "", "status": "available", "reason": None
            },
            "interest_coverage_ratio": {
                "value": "개선", "unit": "", "status": "available", "reason": None
            },
            "accounts_receivable_days": {
                "value": "악화", "unit": "", "status": "available", "reason": None
            },
        }
        company["market_kpi"].update(
            {
                "period_return": {
                    "value": 280.26, "unit": "%", "status": "available", "reason": None
                },
                "market_index_change": {
                    "value": 167.19, "unit": "%", "status": "available", "reason": None
                },
                "latest_close": {
                    "value": 262000, "unit": "원", "status": "available", "reason": None
                },
            }
        )
        parsed = self.parsed()
        parsed.analyses[0].one_line_summary = InsightSection(
            summary=(
                "2025년 재무 성과가 긍정적으로 나타났으나, 최근 3년의 성장성과 "
                "재무 지표 간에는 혼재된 신호가 관찰됩니다."
            ),
            evidence_keys=[
                "revenue_growth",
                "operating_profit_growth",
                "net_income_growth",
                "debt_ratio",
            ],
        )
        parsed.analyses[0].positive_signals = [
            InsightSection(
                summary=(
                    "2025년 영업이익과 순이익의 여러 지표에서 긍정적인 "
                    "성장세가 확인됩니다."
                ),
                evidence_keys=["operating_profit_growth", "net_income_growth"],
            )
        ]
        parsed.analyses[0].caution_signals = [
            InsightSection(
                summary=(
                    "매출채권 회전일수가 증가하면서 회수 효율성에 대한 우려가 "
                    "존재합니다."
                ),
                evidence_keys=["financial_trend.accounts_receivable_days"],
            )
        ]
        parsed.analyses[0].profitability = InsightSection(
            summary=(
                "운영 이익률은 13.07%, 순이익률은 13.55%로 나타났습니다."
            ),
            evidence_keys=["operating_margin", "net_margin"],
        )
        parsed.analyses[0].market = InsightSection(
            summary=(
                "최근 3년간 주가 수익률이 280.26%로 급증했으며, "
                "현재 주가는 262,000원입니다."
            ),
            evidence_keys=["period_return", "latest_close"],
        )
        parsed.analyses[0].relationships_and_mismatches = [
            InsightSection(
                summary=(
                    "영업이익이 증가했지만 운영 이익률이 안정적인 개선세를 보였습니다. "
                    "순이익이 이전 연도보다 감소하는 경향도 확인됐습니다."
                ),
                evidence_keys=[
                    "financial_trend.operating_profit_growth",
                    "operating_margin",
                ],
            )
        ]
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            output_parsed=parsed, output=[]
        )

        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(payload, Path("."))

        insight = result["analyses"][0]
        self.assertNotIn("긍정적", insight["one_line_summary"]["summary"])
        self.assertTrue(
            all("여러 지표" not in item["summary"] for item in insight["positive_signals"])
        )
        self.assertTrue(
            all("회수 효율성" not in item["summary"] for item in insight["caution_signals"])
        )
        self.assertNotIn("운영 이익률", insight["profitability"]["summary"])
        self.assertNotIn("급증", insight["market"]["summary"])
        self.assertNotIn("현재 주가", insight["market"]["summary"])
        self.assertEqual(insight["relationships_and_mismatches"], [])

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_repairs_stability_plan_and_unsupported_scenario_prediction(
        self, _api_key
    ):
        payload = self.payload()
        company = payload["companies"][0]
        company["financial_period"] = "2025"
        company["financial_kpi"].update(
            {
                "revenue_growth": {
                    "value": 10.88, "unit": "%", "status": "available", "reason": None
                },
                "operating_profit_growth": {
                    "value": 33.23, "unit": "%", "status": "available", "reason": None
                },
                "net_income_growth": {
                    "value": 31.22, "unit": "%", "status": "available", "reason": None
                },
                "net_margin": {
                    "value": 13.55, "unit": "%", "status": "available", "reason": None
                },
            }
        )
        company["financial_trend"] = {
            "operating_profit_growth": {
                "value": "변동", "unit": "", "status": "available", "reason": None
            },
            "operating_margin": {
                "value": "개선", "unit": "", "status": "available", "reason": None
            },
            "debt_ratio": {
                "value": "악화", "unit": "", "status": "available", "reason": None
            },
            "interest_coverage_ratio": {
                "value": "개선", "unit": "", "status": "available", "reason": None
            },
            "accounts_receivable_days": {
                "value": "악화", "unit": "", "status": "available", "reason": None
            },
        }
        company["macro_kpi"] = {
            "weak_krw_rising_rate_days": {
                "value": 37, "unit": "일", "status": "available", "reason": None
            },
            "weak_krw_rising_rate_sample_quality": {
                "value": "과거 참고 가능", "unit": "", "status": "available", "reason": None
            },
            "weak_krw_rising_rate_excess_return": {
                "value": -0.63, "unit": "%p", "status": "available", "reason": None
            },
        }
        parsed = self.parsed()
        parsed.analyses[0].positive_signals = [
            InsightSection(
                summary="순이익률이 13.55%로 안정적인 수익성을 보이고 있습니다.",
                evidence_keys=["net_margin"],
            )
        ]
        parsed.analyses[0].caution_signals = [
            InsightSection(
                summary=(
                    "계획했던 영업이익 성장 속도가 둔화되어 있는 경향이 있습니다."
                ),
                evidence_keys=["financial_trend.operating_profit_growth"],
            )
        ]
        parsed.analyses[0].financial_scenario = InsightSection(
            summary=(
                "재무 체질은 개선 추세가 있으나, 금리 상승과 원화 약세 "
                "시나리오에서 혼재된 결과가 나올 가능성이 있습니다."
            ),
            evidence_keys=["weak_krw_rising_rate_days"],
        )
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            output_parsed=parsed, output=[]
        )

        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(payload, Path("."))

        insight = result["analyses"][0]
        self.assertTrue(
            all("안정적인 수익성" not in item["summary"] for item in insight["positive_signals"])
        )
        self.assertTrue(
            all("계획했던" not in item["summary"] for item in insight["caution_signals"])
        )
        scenario = insight["financial_scenario"]
        self.assertNotIn("나올 가능성", scenario["summary"])
        self.assertIn("재무 체질과의 뚜렷한 일치 여부", scenario["summary"])
        self.assertTrue(
            {
                "weak_krw_rising_rate_days",
                "weak_krw_rising_rate_sample_quality",
                "weak_krw_rising_rate_excess_return",
                "financial_trend.debt_ratio",
                "financial_trend.interest_coverage_ratio",
            }.issubset(scenario["evidence_keys"])
        )

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_retries_invalid_single_company_response_and_accepts_correction(self, _api_key):
        corrected = self.parsed()
        invalid = corrected.model_copy(deep=True)
        invalid.analyses[0].relationships_and_mismatches[0].summary = (
            "ROE는 99.9%입니다."
        )
        client = Mock()
        client.responses.parse.side_effect = [
            SimpleNamespace(output_parsed=invalid, output=[]),
            SimpleNamespace(output_parsed=corrected, output=[]),
        ]

        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(self.payload(), Path("."))

        self.assertEqual(result["analyses"][0]["company"], "테스트전자")
        self.assertEqual(result["comparisons"], [])
        self.assertEqual(client.responses.parse.call_count, 2)
        retry_kwargs = client.responses.parse.call_args_list[1].kwargs
        self.assertEqual(retry_kwargs["max_output_tokens"], 8_000)
        self.assertIn("내부 검증을 통과하지 못했습니다", retry_kwargs["input"])
        self.assertIn("comparisons는 빈 배열", retry_kwargs["input"])

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_single_company_can_recover_on_third_validation_attempt(self, _api_key):
        corrected = self.parsed()
        first_invalid = corrected.model_copy(deep=True)
        first_invalid.analyses[0].relationships_and_mismatches[0].summary = (
            "ROE는 99.9%입니다."
        )
        second_invalid = corrected.model_copy(deep=True)
        second_invalid.analyses[0].profitability.summary = "ROE는 88.8%입니다."
        client = Mock()
        client.responses.parse.side_effect = [
            SimpleNamespace(output_parsed=first_invalid, output=[]),
            SimpleNamespace(output_parsed=second_invalid, output=[]),
            SimpleNamespace(output_parsed=corrected, output=[]),
        ]

        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(self.payload(), Path("."))

        self.assertEqual(result["analyses"][0]["company"], "테스트전자")
        self.assertEqual(client.responses.parse.call_count, 3)
        final_retry_input = client.responses.parse.call_args_list[2].kwargs["input"]
        self.assertIn("일치하지 않는 숫자", final_retry_input)

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_retries_invalid_multi_company_response_and_accepts_correction(self, _api_key):
        payload = self.payload()
        second = {
            **payload["companies"][0],
            "company": "비교전자",
            "financial_kpi": {
                **payload["companies"][0]["financial_kpi"],
                "roe": {"value": 8.1, "unit": "%", "status": "available", "reason": None},
            },
        }
        payload["companies"].append(second)
        first_section = InsightSection(summary="수익성 KPI를 확인했습니다.", evidence_keys=["roe"])
        second_section = InsightSection(summary="비교 가능한 KPI가 있습니다.", evidence_keys=["roe"])
        parsed = KPIInsightResponse(
            analyses=[
                CompanyInsight(
                    company="테스트전자", one_line_summary=first_section,
                    data_basis="2025년 재무 데이터 기준", growth=first_section,
                    profitability=first_section, stability=first_section,
                    efficiency=first_section, market=first_section, financial_scenario=first_section,
                    relationships_and_mismatches=[first_section], positive_signals=[first_section],
                    caution_signals=[], additional_checks=[], overall_summary=first_section,
                ),
                CompanyInsight(
                    company="비교전자", one_line_summary=second_section,
                    data_basis="2025년 재무 데이터 기준", growth=second_section,
                    profitability=second_section, stability=second_section,
                    efficiency=second_section, market=second_section, financial_scenario=second_section,
                    relationships_and_mismatches=[second_section], positive_signals=[second_section],
                    caution_signals=[], additional_checks=[], overall_summary=second_section,
                ),
            ],
            comparisons=[
                ComparisonInsight(
                    summary="두 기업의 ROE 차이를 확인할 수 있습니다.",
                    evidence=[
                        MetricReference(company="테스트전자", metric_key="roe"),
                        MetricReference(company="비교전자", metric_key="roe"),
                    ],
                )
            ],
        )
        invalid = parsed.model_copy(deep=True)
        invalid.analyses[0].profitability.summary = "ROE는 99.9%입니다."
        client = Mock()
        client.responses.parse.side_effect = [
            SimpleNamespace(output_parsed=invalid, output=[]),
            SimpleNamespace(output_parsed=parsed, output=[]),
        ]
        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(payload, Path("."))

        self.assertEqual(len(result["comparisons"]), 1)
        self.assertEqual(client.responses.parse.call_count, 2)
        retry_kwargs = client.responses.parse.call_args_list[1].kwargs
        self.assertEqual(retry_kwargs["max_output_tokens"], 12_000)
        self.assertIn("내부 검증을 통과하지 못했습니다", retry_kwargs["input"])

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_repairs_missing_multi_company_comparison_after_retries(self, _api_key):
        payload = self.payload()
        second = {
            **payload["companies"][0],
            "company": "비교전자",
            "financial_kpi": {
                **payload["companies"][0]["financial_kpi"],
                "roe": {"value": 8.1, "unit": "%", "status": "available", "reason": None},
            },
        }
        payload["companies"].append(second)
        first = self.parsed().analyses[0]
        section = InsightSection(summary="비교 가능한 KPI가 있습니다.", evidence_keys=["roe"])
        second_analysis = first.model_copy(deep=True)
        second_analysis.company = "비교전자"
        second_analysis.one_line_summary = section
        invalid = KPIInsightResponse(
            analyses=[first, second_analysis],
            comparisons=[],
        )
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            output_parsed=invalid, output=[]
        )

        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(payload, Path("."))

        self.assertEqual(client.responses.parse.call_count, 3)
        self.assertEqual(len(result["analyses"]), 2)
        self.assertGreaterEqual(len(result["comparisons"]), 1)
        self.assertTrue(
            all(
                {item["company"] for item in comparison["evidence"]}
                == {"테스트전자", "비교전자"}
                for comparison in result["comparisons"]
            )
        )

    @patch("src.gpt_analysis.get_openai_api_key", return_value="test-key")
    def test_repairs_company_omitted_from_three_company_response(self, _api_key):
        payload = self.payload()
        for company_name, roe in (("비교전자", 8.1), ("누락전자", 6.2)):
            payload["companies"].append(
                {
                    **payload["companies"][0],
                    "company": company_name,
                    "financial_kpi": {
                        **payload["companies"][0]["financial_kpi"],
                        "roe": {
                            "value": roe,
                            "unit": "%",
                            "status": "available",
                            "reason": None,
                        },
                    },
                }
            )
        first = self.parsed().analyses[0]
        second = first.model_copy(deep=True)
        second.company = "비교전자"
        incomplete = KPIInsightResponse(analyses=[first, second], comparisons=[])
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            output_parsed=incomplete, output=[]
        )

        with patch("openai.OpenAI", return_value=client):
            result = analyze_kpis(payload, Path("."))

        self.assertEqual(client.responses.parse.call_count, 3)
        self.assertEqual(
            [analysis["company"] for analysis in result["analyses"]],
            ["테스트전자", "비교전자", "누락전자"],
        )
        fallback = result["analyses"][2]
        self.assertEqual(fallback["profitability"]["evidence_keys"], ["roe"])
        self.assertGreaterEqual(len(result["comparisons"]), 1)


if __name__ == "__main__":
    unittest.main()
