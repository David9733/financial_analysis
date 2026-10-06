from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from src.app import app
from src.financial_analysis import FINAL_COLUMNS
from src.main import IntegratedAnalysisResult
from src.stock_analysis import STOCK_PRICE_COLUMNS, STOCK_SUMMARY_COLUMNS


class AppStockIntegrationTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()

    @staticmethod
    def fake_result() -> IntegratedAnalysisResult:
        financial_row = {column: "해당 없음(업종)" for column in FINAL_COLUMNS}
        financial_row.update({"기업명": "삼성전자", "분석유형": "일반기업", "연도": 2025})
        financial = pd.DataFrame([financial_row], columns=FINAL_COLUMNS)
        summary = pd.DataFrame(
            [["삼성전자", "005930", pd.Timestamp("2026-09-30"), 268500, 12.5, 276000, 250000, 1000, 2000, 3000]],
            columns=STOCK_SUMMARY_COLUMNS,
        )
        return IntegratedAnalysisResult(
            financial=financial,
            stock_prices=pd.DataFrame(columns=STOCK_PRICE_COLUMNS),
            stock_summary=summary,
            warnings=[],
            kpi_payload={
                "companies": [
                    {
                        "company": "삼성전자",
                        "analysis_type": "일반기업",
                        "financial_period": "2025",
                        "financial_kpi": {
                            "roe": {
                                "value": 10.2,
                                "unit": "%",
                                "status": "available",
                                "reason": None,
                            }
                        },
                        "market_kpi": {
                            "period_return": {
                                "value": 12.5,
                                "unit": "%",
                                "status": "available",
                                "reason": None,
                            }
                        },
                    }
                ]
            },
            gpt_insights=[
                {
                    "company": "삼성전자",
                    "one_line_summary": {"summary": "한줄 핵심 요약", "evidence_keys": ["roe"]},
                    "data_basis": "2025년 재무 데이터와 2026년 시장 데이터 기준",
                    "growth": {"summary": "성장성 요약", "evidence_keys": ["roe"]},
                    "profitability": {"summary": "수익성 요약", "evidence_keys": ["roe"]},
                    "stability": {"summary": "안정성 요약", "evidence_keys": ["roe"]},
                    "efficiency": {"summary": "효율성 요약", "evidence_keys": ["roe"]},
                    "market": {"summary": "시장 요약", "evidence_keys": ["period_return"]},
                    "relationships_and_mismatches": [
                        {"summary": "KPI 관계 요약", "evidence_keys": ["roe", "period_return"]}
                    ],
                    "positive_signals": [
                        {"summary": "긍정 데이터 요약", "evidence_keys": ["roe"]}
                    ],
                    "caution_signals": [
                        {"summary": "주의 데이터 요약", "evidence_keys": ["period_return"]}
                    ],
                    "additional_checks": [
                        {"summary": "추가 공시 확인", "evidence_keys": ["roe"]}
                    ],
                    "overall_summary": {"summary": "종합 분석 요약", "evidence_keys": ["roe"]},
                }
            ],
            gpt_comparisons=[
                {
                    "summary": "기업별 KPI 차이 요약",
                    "evidence": [
                        {"company": "삼성전자", "metric_key": "roe"},
                        {"company": "삼성전자", "metric_key": "period_return"},
                    ],
                }
            ],
        )

    @patch("src.app.run_integrated_analysis")
    def test_result_page_renders_stock_and_financial_sections(self, run_analysis):
        run_analysis.return_value = self.fake_result()

        response = self.client.post(
            "/analyze",
            data={"company": "삼성전자", "number_of_years": "5", "stock_period": "1y"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("주식시장 분석", response.get_data(as_text=True))
        self.assertIn("재무 분석", response.get_data(as_text=True))
        self.assertIn("핵심 성과지표", response.get_data(as_text=True))
        self.assertIn("GPT 자동 인사이트", response.get_data(as_text=True))
        self.assertIn("성장성 요약", response.get_data(as_text=True))
        self.assertIn("한줄 핵심 요약", response.get_data(as_text=True))
        self.assertIn("효율성 요약", response.get_data(as_text=True))
        self.assertIn("KPI 관계 요약", response.get_data(as_text=True))
        self.assertIn("종합 분석 요약", response.get_data(as_text=True))
        self.assertIn("ROE 10.2%", response.get_data(as_text=True))
        self.assertIn("기업 간 차이", response.get_data(as_text=True))
        self.assertIn("기업별 KPI 차이 요약", response.get_data(as_text=True))
        self.assertNotIn("외부 요인 (환율, 금리)", response.get_data(as_text=True))
        run_analysis.assert_called_once()

    @patch("src.app.run_integrated_analysis")
    def test_result_page_renders_macro_kpis(self, run_analysis):
        result = self.fake_result()
        result.kpi_payload["companies"][0]["macro_kpi"] = {
            "usd_krw_latest": {
                "value": 1358.4,
                "unit": "원",
                "status": "available",
                "reason": None,
            },
            "corr_return_usd_krw": {
                "value": None,
                "unit": "",
                "status": "no_comparison_period",
                "reason": "관측일 부족",
            },
        }
        run_analysis.return_value = result

        response = self.client.post(
            "/analyze",
            data={"company": "삼성전자", "number_of_years": "5", "stock_period": "1y"},
        )
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("외부 요인 (환율, 금리)", html)
        self.assertIn("1,358원", html)
        self.assertIn("주가 수익률-환율 상관계수", html)

    def test_invalid_stock_period_returns_400(self):
        response = self.client.post(
            "/analyze",
            data={"company": "삼성전자", "number_of_years": "5", "stock_period": "all"},
        )
        self.assertEqual(response.status_code, 400)

    @patch("src.app.run_integrated_analysis")
    def test_analysis_progress_reports_real_pipeline_stage(self, run_analysis):
        run_id = "a" * 32

        def complete_with_progress(*args, **kwargs):
            kwargs["progress_callback"](
                "market", 55, "삼성전자 주가를 수집하고 있습니다."
            )
            return self.fake_result()

        run_analysis.side_effect = complete_with_progress
        response = self.client.post(
            "/analyze",
            data={
                "run_id": run_id,
                "company": "삼성전자",
                "number_of_years": "5",
                "stock_period": "1y",
            },
        )
        progress = self.client.get(f"/analysis-progress/{run_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(progress.status_code, 200)
        self.assertEqual(progress.get_json()["stage"], "complete")
        self.assertEqual(progress.get_json()["percent"], 100)


if __name__ == "__main__":
    unittest.main()
