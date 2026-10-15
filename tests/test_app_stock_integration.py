from __future__ import annotations

import os
import unittest
import tempfile
import time
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from PIL import Image

from src.app import (
    ACTIVE_RUN_IDS,
    GPT_RUNS,
    KPI_HELP_TEXT,
    app,
    build_chart_url,
    build_stock_chart_items,
    format_korean_won,
    format_kpi_metric,
    run_gpt_analysis_with_timeout,
    start_async_gpt_analysis,
)
from src.financial_analysis import FINAL_COLUMNS
from src.main import IntegratedAnalysisResult
from src.stock_analysis import STOCK_PRICE_COLUMNS, STOCK_SUMMARY_COLUMNS


class AppStockIntegrationTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def test_search_page_uses_compact_intro_copy(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "기업명만 입력하면 재무와 주식시장 데이터를 한 번에 분석합니다.",
            response.get_data(as_text=True),
        )

    def test_neutral_direction_kpi_has_distinct_display_label(self):
        self.assertEqual(
            format_kpi_metric(
                {
                    "value": None,
                    "unit": "%",
                    "status": "neutral_direction",
                    "reason": "기준 방향 없음",
                }
            ),
            "방향성 없음",
        )

    def test_no_comparison_period_kpi_uses_hyphen_in_tables(self):
        self.assertEqual(
            format_kpi_metric(
                {
                    "value": None,
                    "unit": "%",
                    "status": "no_comparison_period",
                    "reason": "비교기간 부족",
                }
            ),
            "-",
        )

    def test_kpi_metric_honors_display_precision(self):
        self.assertEqual(
            format_kpi_metric(
                {
                    "value": 0.018,
                    "unit": "",
                    "status": "available",
                    "reason": None,
                    "display_digits": 3,
                }
            ),
            "0.018",
        )

    def test_market_cap_uses_readable_korean_won_units(self):
        self.assertEqual(format_korean_won(10_000), "1만원")
        self.assertEqual(
            format_korean_won(442_046_607_000_000),
            "442조 466억 700만원",
        )

    @staticmethod
    def fake_result() -> IntegratedAnalysisResult:
        financial_row = {column: "해당 없음(업종)" for column in FINAL_COLUMNS}
        financial_row.update({"기업명": "삼성전자", "분석유형": "일반기업", "연도": 2025})
        financial = pd.DataFrame([financial_row], columns=FINAL_COLUMNS)
        summary = pd.DataFrame(
            [[
                "삼성전자",
                "005930",
                pd.Timestamp("2026-09-30"),
                268500,
                12.5,
                276000,
                250000,
                1000,
                2000,
                442_046_607_000_000,
            ]],
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
                        "star_score": [
                            {
                                "key": key,
                                "label": label,
                                "score": score,
                                "status": "available",
                                "evidence": [{"label": "ROE", "value": "10.2%"}],
                                "is_proxy": False,
                                "reason": None,
                            }
                            for key, label, score in (
                                ("growth", "성장성", 72),
                                ("profitability", "수익성", 68),
                                ("stability", "재무 안정성", 74),
                                ("efficiency", "효율성", 65),
                                ("market", "시장흐름", 70),
                            )
                        ],
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

    @patch("src.app.ENABLE_GPT_INSIGHTS", False)
    @patch("src.app.run_integrated_analysis")
    def test_result_page_renders_stock_and_financial_sections(self, run_analysis):
        run_analysis.return_value = self.fake_result()

        response = self.client.post(
            "/analyze",
            data={"company": "삼성전자", "number_of_years": "5", "stock_period": "1y"},
        )
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("주식시장 분석", html)
        self.assertIn("<dt>시가총액</dt><dd>442조 466억 700만원</dd>", html)
        self.assertIn('class="single-kpi-table"', html)
        self.assertNotIn("<th>지표</th><th>삼성전자</th>", html)
        self.assertIn("재무 분석", response.get_data(as_text=True))
        self.assertIn("핵심 성과지표", response.get_data(as_text=True))
        self.assertEqual(response.get_data(as_text=True).count("data-preview-tab="), 6)
        self.assertIn("주가, 시장지수 및 외부요인 요약", response.get_data(as_text=True))
        self.assertNotIn("GPT 자동 인사이트", response.get_data(as_text=True))
        self.assertNotIn("환율·금리 시나리오 인사이트", response.get_data(as_text=True))
        self.assertNotIn("재무 완충력 판정", response.get_data(as_text=True))
        self.assertNotIn("성장성 요약", response.get_data(as_text=True))
        self.assertNotIn("한줄 핵심 요약", response.get_data(as_text=True))
        self.assertNotIn("효율성 요약", response.get_data(as_text=True))
        self.assertNotIn("KPI 관계 요약", response.get_data(as_text=True))
        self.assertNotIn("종합 분석 요약", response.get_data(as_text=True))
        self.assertIn("<dt>ROE</dt><dd>10.2%</dd>", html)
        self.assertNotIn("기업 간 차이", response.get_data(as_text=True))
        self.assertNotIn("기업별 KPI 차이 요약", response.get_data(as_text=True))
        self.assertIn("기업 역량 스타차트", html)
        self.assertIn('id="company-star-chart"', html)
        self.assertIn('data-star-toggle="0" aria-pressed="true"', html)
        self.assertNotIn("star-evidence-card", html)
        self.assertIn("업종별 평가 기준", html)
        self.assertIn("순이자손익", html)
        self.assertIn("보험서비스마진", html)
        self.assertIn("전년과 당년 평균자본", response.get_data(as_text=True))
        self.assertIn("마지막 종가 ÷ 첫 종가", response.get_data(as_text=True))
        self.assertIn("kpi-help-item", response.get_data(as_text=True))
        self.assertNotIn("외부 요인 (환율, 금리)", response.get_data(as_text=True))
        run_analysis.assert_called_once()

    @patch("src.app.ENABLE_GPT_INSIGHTS", False)
    @patch("src.app.run_integrated_analysis")
    def test_data_quality_warning_uses_collapsible_notice(self, run_analysis):
        result = self.fake_result()
        result.warnings = ["데이터 처리: 직전 값 채움 3건, 하루 변화 이상치 표시 1건"]
        run_analysis.return_value = result

        response = self.client.post(
            "/analyze",
            data={"company": "삼성전자", "number_of_years": "5", "stock_period": "1y"},
        )
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('<p class="data-quality-desktop">', html)
        self.assertIn('<details class="data-quality-notice">', html)
        self.assertIn("<summary>데이터 처리 내역</summary>", html)

    @patch("src.app.ENABLE_GPT_INSIGHTS", True)
    @patch("src.app.run_integrated_analysis")
    def test_result_page_renders_enabled_gpt_insights(self, run_analysis):
        run_analysis.return_value = self.fake_result()

        response = self.client.post(
            "/analyze",
            data={"company": "삼성전자", "number_of_years": "5", "stock_period": "1y"},
        )
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("종합 인사이트", html)
        self.assertIn("GPT 기업 분석", html)
        self.assertIn("한줄 핵심 요약", html)
        self.assertIn("재무 체질과 시나리오 반응", html)
        self.assertIn("종합 분석 요약", html)

    @patch("src.app.ENABLE_GPT_INSIGHTS", True)
    @patch("src.app.start_async_gpt_analysis")
    @patch("src.app.run_integrated_analysis")
    def test_result_opens_financial_tab_while_gpt_loads_in_background(
        self, run_analysis, start_gpt
    ):
        result = self.fake_result()
        result.gpt_insights = []
        result.gpt_comparisons = []
        run_analysis.return_value = result
        run_id = "c" * 32

        response = self.client.post(
            "/analyze",
            data={
                "run_id": run_id,
                "company": "삼성전자",
                "number_of_years": "5",
                "stock_period": "1y",
            },
        )
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="tab-financial" aria-controls="panel-financial" aria-selected="true"', html)
        self.assertIn('id="panel-summary" class="tab-panel" role="tabpanel" aria-labelledby="tab-summary" data-panel="summary" hidden', html)
        self.assertIn("GPT 기업 분석을 생성하고 있습니다.", html)
        self.assertIn("완료되면 자동으로 표시합니다.", html)
        self.assertNotIn("최대 10초", html)
        self.assertIn(f'data-gpt-status-url="/gpt-analysis/{run_id}"', html)
        self.assertFalse(run_analysis.call_args.kwargs["include_gpt"])
        start_gpt.assert_called_once()

    @patch.dict(os.environ, {"VERCEL": "1"})
    @patch("src.app.run_integrated_analysis")
    def test_vercel_returns_page_before_requesting_gpt(self, run_analysis):
        result = self.fake_result()
        result.gpt_insights = []
        result.gpt_comparisons = []
        run_analysis.return_value = result

        response = self.client.post(
            "/analyze",
            data={"company": "삼성전자", "number_of_years": "5", "stock_period": "1y"},
        )
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('data-gpt-status-url="/gpt-analysis/', html)
        self.assertIn('id="gpt-request-data"', html)
        self.assertIn('"encoding": "zlib-base64"', html)
        self.assertIn("GPT 기업 분석을 생성하고 있습니다.", html)
        self.assertIn("method: 'POST'", html)

    @patch("src.app.run_gpt_analysis_with_timeout")
    def test_compressed_stateless_gpt_post_returns_completed_fragment(self, run_gpt):
        from src.app import encode_gpt_request_data

        result = self.fake_result()
        run_gpt.return_value = ([], [], "KPI 기반 대체 분석입니다.")
        run_id = "f" * 32
        request_data = encode_gpt_request_data(
            {"payload": result.kpi_payload, "macro_chart_groups": []}, run_id
        )

        response = self.client.post(f"/gpt-analysis/{run_id}", json=request_data)

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "complete")
        self.assertIn("KPI 기반 대체 분석입니다.", payload["html"])
        run_gpt.assert_called_once_with(result.kpi_payload)

    @patch("src.app.run_gpt_analysis_with_timeout")
    def test_stateless_gpt_post_rejects_requests_not_issued_by_server(self, run_gpt):
        from src.app import encode_gpt_request_data

        data = {"payload": self.fake_result().kpi_payload, "macro_chart_groups": []}
        run_id = "f" * 32
        signed = encode_gpt_request_data(data, run_id)
        other = encode_gpt_request_data({**data, "macro_chart_groups": [{}]}, run_id)
        cases = {
            "평문 KPI": data,
            "서명 없음": {key: signed[key] for key in ("encoding", "data")},
            "다른 실행 ID": signed,
            "본문 변조": {**signed, "data": other["data"]},
            "만료 시각 변조": {**signed, "expires_at": signed["expires_at"] + 3600},
        }
        for label, body in cases.items():
            with self.subTest(label):
                target = "e" * 32 if label == "다른 실행 ID" else run_id
                response = self.client.post(f"/gpt-analysis/{target}", json=body)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.get_json()["status"], "failed")
        run_gpt.assert_not_called()

    @patch("src.app.run_gpt_analysis_with_timeout")
    def test_stateless_gpt_post_allows_body_above_form_limit(self, run_gpt):
        import secrets as secrets_module

        from src.app import encode_gpt_request_data

        run_gpt.return_value = ([], [], "")
        run_id = "f" * 32
        # 압축되지 않는 문자열로 앱 전체 폼 제한(32KB)을 넘는 요청을 만든다.
        groups = [{"key": "correlation", "note": secrets_module.token_hex(30_000)}]
        signed = encode_gpt_request_data(
            {"payload": self.fake_result().kpi_payload, "macro_chart_groups": groups},
            run_id,
        )

        response = self.client.post(f"/gpt-analysis/{run_id}", json=signed)
        form_response = self.client.post(
            "/analyze", data={"company": "가" * 40_000}
        )

        self.assertGreater(len(signed["data"]), app.config["MAX_CONTENT_LENGTH"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "complete")
        self.assertEqual(form_response.status_code, 413)

    def test_index_estimates_progress_when_server_progress_is_unavailable(self):
        html = self.client.get("/").get_data(as_text=True)

        self.assertIn("estimatedProgress", html)
        self.assertIn("(예상 진행률)", html)

    @patch("src.app.run_gpt_analysis_with_timeout")
    def test_stateless_gpt_post_rejects_expired_request(self, run_gpt):
        from src.app import GPT_REQUEST_TTL_SECONDS, encode_gpt_request_data

        run_id = "f" * 32
        signed = encode_gpt_request_data(
            {"payload": self.fake_result().kpi_payload, "macro_chart_groups": []},
            run_id,
        )
        with patch(
            "src.app.time.time",
            return_value=time.time() + GPT_REQUEST_TTL_SECONDS + 1,
        ):
            response = self.client.post(f"/gpt-analysis/{run_id}", json=signed)

        self.assertEqual(response.status_code, 403)
        self.assertIn("시간이 지났습니다", response.get_json()["message"])
        run_gpt.assert_not_called()

    def test_vercel_chart_is_embedded_as_webp_data_url(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chart.png"
            Image.new("RGB", (40, 30), "white").save(path)
            with patch.dict(os.environ, {"VERCEL": "1"}), app.test_request_context():
                chart_url = build_chart_url(path, "a" * 32, "charts")

        self.assertTrue(chart_url.startswith("data:image/webp;base64,"))

    def test_small_vercel_chart_skips_slow_reencoding(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chart.png"
            Image.new("RGB", (40, 30), "white").save(path)
            with patch.dict(os.environ, {"VERCEL": "1"}), app.test_request_context():
                chart_url = build_chart_url(
                    path,
                    "a" * 32,
                    "charts",
                    compress_inline=False,
                )

        self.assertTrue(chart_url.startswith("data:image/png;base64,"))

    @patch("src.app.analyze_kpis")
    def test_async_gpt_endpoint_returns_completed_fragment(self, analyze_kpis):
        result = self.fake_result()
        analyze_kpis.return_value = {
            "analyses": result.gpt_insights,
            "comparisons": result.gpt_comparisons,
        }
        run_id = "d" * 32
        try:
            with tempfile.TemporaryDirectory() as directory:
                start_async_gpt_analysis(
                    run_id,
                    result.kpi_payload,
                    [],
                    Path(directory),
                )
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    if GPT_RUNS.get(run_id, {}).get("status") == "complete":
                        break
                    time.sleep(0.01)

                response = self.client.get(f"/gpt-analysis/{run_id}")

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["status"], "complete")
            self.assertIn("한줄 핵심 요약", payload["html"])
            self.assertGreater(analyze_kpis.call_args.kwargs["timeout"], 10)
        finally:
            GPT_RUNS.pop(run_id, None)

    @patch("src.app.build_gpt_cards", side_effect=ValueError("unexpected"))
    @patch("src.app.analyze_kpis")
    def test_async_gpt_unexpected_error_marks_run_failed(
        self, analyze_kpis, _build_gpt_cards
    ):
        result = self.fake_result()
        analyze_kpis.return_value = {
            "analyses": result.gpt_insights,
            "comparisons": result.gpt_comparisons,
        }
        run_id = "e" * 32
        try:
            with tempfile.TemporaryDirectory() as directory:
                start_async_gpt_analysis(
                    run_id,
                    result.kpi_payload,
                    [],
                    Path(directory),
                )
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    if GPT_RUNS.get(run_id, {}).get("status") != "loading":
                        break
                    time.sleep(0.01)

                response = self.client.get(f"/gpt-analysis/{run_id}")

            self.assertEqual(response.get_json()["status"], "failed")
            self.assertNotIn(run_id, ACTIVE_RUN_IDS)
        finally:
            GPT_RUNS.pop(run_id, None)

    @patch("src.app.analyze_kpis")
    def test_stateless_gpt_request_uses_background_timeout(self, analyze_kpis):
        result = self.fake_result()
        analyze_kpis.return_value = {
            "analyses": result.gpt_insights,
            "comparisons": result.gpt_comparisons,
        }

        insight_cards, _, notice = run_gpt_analysis_with_timeout(result.kpi_payload)

        self.assertTrue(insight_cards)
        self.assertEqual(notice, "")
        self.assertGreater(analyze_kpis.call_args.kwargs["timeout"], 10)

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
            "market_index_change",
            "corr_return_market_index",
            "credit_spread_latest",
            "credit_spread_change_bp",
            "corr_return_credit_spread",
            "radar_usd_krw_sign_persistence",
            "radar_usd_krw_sign_switches",
        }

        self.assertTrue(requested.issubset(KPI_HELP_TEXT))
        self.assertTrue(all(KPI_HELP_TEXT[name] for name in requested))
        self.assertNotIn("market_index_name", KPI_HELP_TEXT)
        self.assertNotIn("market_index_latest", KPI_HELP_TEXT)
        self.assertNotIn("market_index_outlier_days", KPI_HELP_TEXT)

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
        self.assertIn('<h2 id="combined-insights-title">종합 인사이트</h2>', html)
        self.assertIn("상관관계 분석", html)
        self.assertEqual(html.count("상관관계 분석"), 1)
        details_start = html.index("삼성전자 세부 분석 펼치기")
        correlation_start = html.index("상관관계 분석", details_start)
        details_end = html.index("</details>", details_start)
        self.assertLess(correlation_start, details_end)
        self.assertIn("핵심 판정", html)
        self.assertNotIn("상관관계 판정 기준", html)
        self.assertNotIn("data-show-correlation-criteria", html)
        self.assertIn("금리 상승(+16.1bp), 원화 약세(환율 +2.4%)", html)
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
            "radar_usd_krw_market_corr": {
                "value": 0.41,
                "unit": "",
                "status": "available",
                "reason": None,
            },
            "radar_treasury_3y_market_corr": {
                "value": -0.22,
                "unit": "",
                "status": "available",
                "reason": None,
            },
            "radar_credit_spread_market_corr": {
                "value": 0.17,
                "unit": "",
                "status": "available",
                "reason": None,
            },
            "radar_usd_krw_excess_corr": {
                "value": 0.017,
                "unit": "",
                "status": "available",
                "reason": None,
                "display_digits": 3,
            },
            "radar_usd_krw_sign_persistence": {
                "value": None,
                "unit": "%",
                "status": "neutral_direction",
                "reason": "기준 방향 없음",
            },
            "radar_usd_krw_judgement": {
                "value": "노출 약 × 안정성 판정 불가 (기준 방향 없음)",
                "unit": "",
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
        self.assertIn("매크로 레이더", html)
        self.assertIn("환율 시장 대비 상관 차이", html)
        self.assertIn("환율 이동상관 부호 유지율", html)
        self.assertIn(
            'class="kpi-label-tail">유지율<span class="kpi-help-badge"',
            html,
        )
        self.assertIn("노출 약 + 안정성 판정 불가 (기준 방향 없음)", html)
        self.assertIn("비교 시장지수", html)
        self.assertIn("KOSPI", html)
        self.assertNotIn("주가 수익률-시장지수 수익률 상관계수", html)
        self.assertIn("1,358원", html)
        self.assertNotIn("주가 수익률-환율 변화율 상관계수", html)
        self.assertNotIn("주가 수익률-금리 변화폭 상관계수", html)
        self.assertNotIn("주가 수익률-신용 스프레드 변화폭 상관계수", html)
        self.assertNotIn("시장지수 수익률-환율 변화율 상관계수", html)
        self.assertNotIn("시장지수 수익률-금리 변화폭 상관계수", html)
        self.assertNotIn("시장지수 수익률-신용 스프레드 상관계수", html)
        self.assertIn("신용 스프레드(최근)", html)
        self.assertIn("+16.1bp (+0.161%p)", html)
        self.assertNotIn("환율값-금리값 상관계수", html)
        self.assertNotIn("환율 변화율-금리 변화폭 상관계수", html)
        self.assertNotIn("0.72", html)
        self.assertNotIn("-0.35", html)
        self.assertNotRegex(html, r'class="[^"]*\bkpi-warning-item\b')
        self.assertNotIn("공통 추세만으로도 높게 나타날 수 있습니다", html)
        self.assertNotIn("외부 요인 보간 거래일", html)
        self.assertNotIn("직전 값(첫 구간은 다음 값)으로", html)
        self.assertNotIn("보간된 구간은 상관계수와 이상치 계산에서 제외됩니다", html)
        self.assertIn("마지막 환율 ÷ 첫 환율", html)
        self.assertIn("금리 변화율이 아니라 변화폭", html)

    def test_invalid_stock_period_returns_400(self):
        response = self.client.post(
            "/analyze",
            data={"company": "삼성전자", "number_of_years": "5", "stock_period": "all"},
        )
        self.assertEqual(response.status_code, 400)

    def test_validation_error_is_hidden_when_analysis_is_resubmitted(self):
        response = self.client.post(
            "/analyze",
            data={"company": "", "number_of_years": "5", "stock_period": "1y"},
        )
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 400)
        self.assertIn('id="analysis-error"', html)
        self.assertIn('id="analysis-submit-status"', html)
        self.assertIn("onsubmit=\"var errorBox=", html)
        self.assertIn("loadingBox.hidden=false", html)
        self.assertIn("(() => {", html)
        self.assertIn("})();", html)
        self.assertIn("previousError.hidden = true", html)
        self.assertIn("showSubmitStatus();", html)
        self.assertIn("submitStatus.scrollIntoView", html)
        self.assertIn("minimumLoadingTime", html)
        self.assertIn("Promise.all([analysisRequest, minimumLoadingTime])", html)
        self.assertIn("response.status !== 400", html)
        self.assertIn("분석 요청이 중단되었습니다.", html)
        self.assertIn("highestProgressPercent", html)
        self.assertIn("incomingPercent < highestProgressPercent", html)
        self.assertIn("replacePageWithoutFlash", html)
        self.assertNotIn("document.open();", html)

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

    @patch("src.app.ENABLE_GPT_INSIGHTS", False)
    @patch("src.app.run_integrated_analysis")
    def test_multi_company_result_uses_comparison_dashboard(self, run_analysis):
        result = self.fake_result()
        second_financial = result.financial.iloc[0].copy()
        second_financial["기업명"] = "SK하이닉스"
        result.financial = pd.concat(
            [result.financial, second_financial.to_frame().T], ignore_index=True
        )
        second_summary = result.stock_summary.iloc[0].copy()
        second_summary["기업명"] = "SK하이닉스"
        second_summary["종목코드"] = "000660"
        result.stock_summary = pd.concat(
            [result.stock_summary, second_summary.to_frame().T], ignore_index=True
        )
        second_payload = deepcopy(result.kpi_payload["companies"][0])
        second_payload["company"] = "SK하이닉스"
        second_payload["financial_kpi"]["roe"]["value"] = 8.4
        result.kpi_payload["companies"].append(second_payload)
        run_analysis.return_value = result

        response = self.client.post(
            "/analyze",
            data={
                "company": ["삼성전자", "SK하이닉스"],
                "number_of_years": "5",
                "stock_period": "1y",
            },
        )
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("result-page-comparison", html)
        self.assertIn("2개 기업을 같은 지표 기준으로 비교합니다.", html)
        self.assertEqual(html.count('class="snapshot-kpi-section"'), 2)
        self.assertIn("핵심 성과지표", html)
        self.assertNotIn("삼성전자 세부 분석 펼치기", html)
        self.assertEqual(html.count('data-tab="'), 4)
        self.assertEqual(html.count('data-star-toggle='), 2)
        self.assertEqual(html.count('aria-pressed="true"'), 2)


if __name__ == "__main__":
    unittest.main()
