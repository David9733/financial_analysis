from __future__ import annotations

import os
import tempfile
import unittest
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
        self.assertEqual(result["comparisons"], [])
        kwargs = client.responses.parse.call_args.kwargs
        self.assertFalse(kwargs["store"])
        self.assertIs(kwargs["text_format"], KPIInsightResponse)
        self.assertIn("15년 이상의 실무 경험", kwargs["instructions"])
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

        self.assertEqual(client.responses.parse.call_count, 1)
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
                    efficiency=first_section, market=first_section,
                    relationships_and_mismatches=[first_section], positive_signals=[first_section],
                    caution_signals=[], additional_checks=[], overall_summary=first_section,
                ),
                CompanyInsight(
                    company="비교전자", one_line_summary=second_section,
                    data_basis="2025년 재무 데이터 기준", growth=second_section,
                    profitability=second_section, stability=second_section,
                    efficiency=second_section, market=second_section,
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
        self.assertEqual(len(result["comparisons"]), 1)
        self.assertEqual(
            {item["company"] for item in result["comparisons"][0]["evidence"]},
            {"테스트전자", "비교전자"},
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
        self.assertEqual(len(result["comparisons"]), 1)


if __name__ == "__main__":
    unittest.main()
