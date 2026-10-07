from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src.app import KPI_HELP_TEXT, app, build_stock_chart_items
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
        self.assertNotIn("환율·금리 시나리오 인사이트", response.get_data(as_text=True))
        self.assertNotIn("재무 완충력 판정", response.get_data(as_text=True))
        self.assertIn("성장성 요약", response.get_data(as_text=True))
        self.assertIn("한줄 핵심 요약", response.get_data(as_text=True))
        self.assertIn("효율성 요약", response.get_data(as_text=True))
        self.assertIn("KPI 관계 요약", response.get_data(as_text=True))
        self.assertIn("종합 분석 요약", response.get_data(as_text=True))
        self.assertIn("ROE 10.2%", response.get_data(as_text=True))
        self.assertIn("기업 간 차이", response.get_data(as_text=True))
        self.assertIn("기업별 KPI 차이 요약", response.get_data(as_text=True))
        self.assertIn("전년·당년 평균자본", response.get_data(as_text=True))
        self.assertIn("마지막 종가 ÷ 첫 종가", response.get_data(as_text=True))
        self.assertIn("kpi-help-item", response.get_data(as_text=True))
        self.assertIn(
            "선택기간 과거 동행성을 설명", response.get_data(as_text=True)
        )
        self.assertNotIn("외부 요인 (환율, 금리)", response.get_data(as_text=True))
        run_analysis.assert_called_once()

    def test_requested_financial_and_market_kpis_have_help_text(self):
        requested = {
            "revenue_growth",
            "operating_profit_growth",
            "net_income_growth",
            "operating_margin",
            "net_margin",
            "roe",
            "roa",
            "debt_ratio",
            "interest_coverage_ratio",
            "accounts_receivable_days",
            "period_return",
            "daily_volatility",
            "average_volume",
            "average_trading_value",
            "recent_volume_change",
            "price_to_ma20",
            "bollinger_position",
            "market_index_name",
            "market_index_latest",
            "market_index_change",
            "corr_return_market_index",
            "market_index_outlier_days",
            "credit_spread_latest",
            "credit_spread_change_bp",
            "corr_return_credit_spread",
        }

        self.assertTrue(requested.issubset(KPI_HELP_TEXT))
        self.assertTrue(all(KPI_HELP_TEXT[name] for name in requested))

    def test_heatmap_insight_is_matched_by_company_code_only(self):
        payload = {
            "companies": [
                {
                    "company": "첫째",
                    "macro_kpi": {
                        "corr_return_usd_krw": {
                            "value": 0.4,
                            "status": "available",
                        },
                        "corr_return_treasury_3y": {
                            "value": 0.5,
                            "status": "available",
                        },
                        "usd_krw_change": {"value": 2.0, "status": "available"},
                        "treasury_3y_change_bp": {"value": 10.0, "status": "available"},
                    },
                },
                {
                    "company": "둘째",
                    "macro_kpi": {
                        "corr_return_usd_krw": {
                            "value": -0.6,
                            "status": "available",
                        },
                        "corr_return_treasury_3y": {
                            "value": -0.7,
                            "status": "available",
                        },
                        "usd_krw_change": {"value": 2.0, "status": "available"},
                        "treasury_3y_change_bp": {"value": 10.0, "status": "available"},
                    },
                },
            ]
        }
        summary = pd.DataFrame(
            [{"기업명": "첫째", "종목코드": "000001"}, {"기업명": "둘째", "종목코드": "000002"}]
        )
        paths = [
            Path("market_correlation_heatmap_000002.png"),
            Path("price_000001.png"),
            Path("market_correlation_heatmap_000001.png"),
        ]

        with app.test_request_context():
            items = build_stock_chart_items(paths, "a" * 32, summary, payload)

        self.assertIn("주가 하락 방향", items[0]["insight"])
        self.assertIsNone(items[1]["insight"])
        self.assertIn("모두 과거 주가 상승 방향", items[2]["insight"])

    @patch("src.app.run_integrated_analysis")
    def test_heatmap_renders_one_line_insight_below_chart(self, run_analysis):
        result = self.fake_result()
        result.kpi_payload["companies"][0]["macro_kpi"] = {
            "corr_return_usd_krw": {"value": -0.48, "status": "available"},
            "corr_return_treasury_3y": {"value": -0.36, "status": "available"},
            "usd_krw_change": {"value": 2.4, "status": "available"},
            "treasury_3y_change_bp": {"value": 16.1, "status": "available"},
        }

        def create_heatmap(*args, **kwargs):
            chart_dir = kwargs["output_dir"] / "stock_charts"
            chart_dir.mkdir(parents=True, exist_ok=True)
            (chart_dir / "market_correlation_heatmap_005930.png").write_bytes(b"png")
            (chart_dir / "price_005930.png").write_bytes(b"png")
            return result

        run_analysis.side_effect = create_heatmap
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.app.WEB_RUNS_DIR", Path(directory)
        ):
            response = self.client.post(
                "/analyze",
                data={
                    "run_id": "b" * 32,
                    "company": "삼성전자",
                    "number_of_years": "5",
                    "stock_period": "1y",
                },
            )

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(html.count("<h3>종합 인사이트</h3>"), 1)
        self.assertIn("금리 상승(+16.1bp)·원화 약세(환율 +2.4%)", html)
        self.assertIn("주가 하락 방향", html)
        self.assertIn("주가–환율 r=-0.48(중간)", html)
        self.assertIn("주가–금리 r=-0.36(중간)", html)

    @patch("src.app.run_integrated_analysis")
    def test_result_page_renders_macro_kpis(self, run_analysis):
        result = self.fake_result()
        result.kpi_payload["companies"][0]["macro_kpi"] = {
            "market_index_name": {
                "value": "KOSPI",
                "unit": "",
                "status": "available",
                "reason": None,
            },
            "market_index_latest": {
                "value": 6941.39,
                "unit": "p",
                "status": "available",
                "reason": None,
            },
            "market_index_change": {
                "value": 4.2,
                "unit": "%",
                "status": "available",
                "reason": None,
            },
            "corr_return_market_index": {
                "value": 0.81,
                "unit": "",
                "status": "available",
                "reason": None,
            },
            "usd_krw_latest": {
                "value": 1358.4,
                "unit": "원",
                "status": "available",
                "reason": None,
            },
            "usd_krw_change": {
                "value": 2.4,
                "unit": "%",
                "status": "available",
                "reason": None,
            },
            "corr_return_usd_krw": {
                "value": None,
                "unit": "",
                "status": "no_comparison_period",
                "reason": "관측일 부족",
            },
            "corr_return_treasury_3y": {
                "value": 0.18,
                "unit": "",
                "status": "available",
                "reason": None,
            },
            "treasury_3y_change_bp": {
                "value": 16.1,
                "unit": "bp",
                "status": "available",
                "reason": None,
            },
            "credit_spread_latest": {
                "value": 121.5,
                "unit": "bp",
                "status": "available",
                "reason": None,
            },
            "credit_spread_change_bp": {
                "value": 8.2,
                "unit": "bp",
                "status": "available",
                "reason": None,
            },
            "corr_return_credit_spread": {
                "value": -0.44,
                "unit": "",
                "status": "available",
                "reason": None,
            },
            "corr_usd_krw_treasury_3y_level": {
                "value": 0.72,
                "unit": "",
                "status": "available",
                "reason": None,
            },
            "corr_usd_krw_treasury_3y_change": {
                "value": -0.35,
                "unit": "",
                "status": "available",
                "reason": None,
            },
            "macro_filled_days": {
                "value": 2,
                "unit": "일",
                "status": "available",
                "reason": None,
            },
        }
        run_analysis.return_value = result

        response = self.client.post(
            "/analyze",
            data={"company": "삼성전자", "number_of_years": "5", "stock_period": "1y"},
        )
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("시장 및 외부 요인 (KOSPI/KOSDAQ, 환율, 금리, 신용 스프레드)", html)
        self.assertIn("비교 시장지수", html)
        self.assertIn("KOSPI", html)
        self.assertIn("주가 수익률-시장지수 수익률 상관계수", html)
        self.assertIn("1,358원", html)
        self.assertIn("주가 수익률-환율 변화율 상관계수", html)
        self.assertIn("주가 수익률-금리 변화폭 상관계수", html)
        self.assertIn("주가 수익률-신용 스프레드 변화폭 상관계수", html)
        self.assertIn("신용 스프레드(최근)", html)
        self.assertIn("+16.1bp (+0.161%p)", html)
        self.assertIn("환율값-금리값 상관계수", html)
        self.assertIn("환율 변화율-금리 변화폭 상관계수", html)
        self.assertIn("0.72", html)
        self.assertIn("-0.35", html)
        self.assertIn("kpi-warning-item", html)
        self.assertIn("공통 추세만으로도 높게 나타날 수 있습니다", html)
        self.assertIn("직전 값(첫 구간은 다음 값)으로", html)
        self.assertIn("보간된 구간은 상관계수와 이상치 계산에서 제외됩니다", html)
        self.assertIn("마지막 환율 ÷ 첫 환율", html)
        self.assertIn("금리 변화율이 아니라 변화폭", html)

    def test_invalid_stock_period_returns_400(self):
        response = self.client.post(
            "/analyze",
            data={"company": "삼성전자", "number_of_years": "5", "stock_period": "all"},
        )
        self.assertEqual(response.status_code, 400)

    @patch("src.app.run_integrated_analysis")
    def test_six_month_stock_period_is_available(self, run_analysis):
        run_analysis.return_value = self.fake_result()

        response = self.client.post(
            "/analyze",
            data={"company": "삼성전자", "number_of_years": "5", "stock_period": "6m"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("6개월", response.get_data(as_text=True))
        self.assertEqual(run_analysis.call_args.kwargs["stock_period"], "6m")

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
