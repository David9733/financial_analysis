"""기업명을 입력해 재무분석 표와 차트를 보여주는 로컬 웹 애플리케이션."""

from __future__ import annotations

import logging
import re
import shutil
import threading
import time
from pathlib import Path
from uuid import uuid4

from flask import Flask, abort, jsonify, render_template, request, send_from_directory, url_for

if __package__:  # ``python -m src.app`` 또는 패키지 import
    from .dart_api import CompanyNotFoundError, DartAPIError
    from .financial_analysis import FINAL_COLUMNS, format_result_for_csv
    from .main import (
        OUTPUT_DIR,
        STOCK_PERIOD_DAYS,
        run_integrated_analysis,
    )
else:  # ``python src/app.py``로 직접 실행
    from dart_api import CompanyNotFoundError, DartAPIError
    from financial_analysis import FINAL_COLUMNS, format_result_for_csv
    from main import (
        OUTPUT_DIR,
        STOCK_PERIOD_DAYS,
        run_integrated_analysis,
    )


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
WEB_RUNS_DIR = OUTPUT_DIR / "web_runs"
WEB_RUN_RETENTION_SECONDS = 60 * 60
COMPLETED_MARKER_NAME = ".completed"
STOCK_PERIOD_LABELS = {"1m": "1개월", "3m": "3개월", "1y": "1년", "3y": "3년"}
AMOUNT_COLUMNS = {
    "매출",
    "보험서비스수익",
    "순이자손익",
    "순수수료손익",
    "영업이익",
    "당기순이익",
    "보험서비스손익",
    "투자손익",
    "총자산",
    "부채총계",
    "자본총계",
}

KPI_LABELS = {
    "revenue_growth": "매출 성장률",
    "operating_profit_growth": "영업이익 성장률",
    "net_income_growth": "당기순이익 성장률",
    "operating_margin": "영업이익률",
    "net_margin": "순이익률",
    "roe": "ROE",
    "roa": "ROA",
    "debt_ratio": "부채비율",
    "interest_coverage_ratio": "이자보상배율",
    "accounts_receivable_days": "매출채권 회전일수",
    "net_interest_income": "순이자손익",
    "net_fee_income": "순수수료손익",
    "insurance_service_revenue": "보험서비스수익",
    "insurance_service_profit": "보험서비스손익",
    "insurance_margin": "보험서비스마진",
    "insurance_revenue_growth": "보험서비스수익 성장률",
    "investment_profit": "투자손익",
    "start_date": "주가 조회 시작일",
    "latest_date": "주가 최신 기준일",
    "latest_close": "최근 종가",
    "average_close": "평균 종가",
    "period_high": "기간 최고가",
    "period_low": "기간 최저가",
    "period_return": "기간 수익률",
    "daily_volatility": "일간 변동성",
    "average_volume": "평균 거래량",
    "average_trading_value": "평균 거래대금",
    "recent_volume_change": "최근 거래량 변화율",
    "price_to_ma20": "20일 이동평균 대비",
    "bollinger_position": "볼린저밴드 내 위치",
    "usd_krw_latest": "원/달러 환율(최근)",
    "usd_krw_change": "원/달러 환율 기간 변화율",
    "treasury_3y_latest": "국고채 3년 금리(최근)",
    "treasury_3y_change_bp": "국고채 3년 금리 기간 변화폭",
    "corr_return_usd_krw": "주가 수익률-환율 상관계수",
    "corr_return_treasury_3y": "주가 수익률-금리 상관계수",
    "macro_filled_days": "환율, 금리 보간 거래일",
    "price_outlier_days": "종가 하루 변화 이상치",
    "usd_krw_outlier_days": "환율 하루 변화 이상치",
    "treasury_3y_outlier_days": "금리 하루 변화 이상치",
}

app = Flask(
    __name__,
    template_folder=str(PROJECT_ROOT / "templates"),
    static_folder=str(PROJECT_ROOT / "static"),
)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024
LOGGER = logging.getLogger(__name__)
PROGRESS_LOCK = threading.Lock()
ANALYSIS_PROGRESS: dict[str, dict] = {}
ACTIVE_RUN_IDS: set[str] = set()


def update_analysis_progress(
    run_id: str,
    stage: str,
    percent: int,
    message: str,
) -> None:
    """브라우저 진행 화면과 운영 로그에 동일한 분석 단계를 기록한다."""
    now = time.time()
    with PROGRESS_LOCK:
        previous_stage = ANALYSIS_PROGRESS.get(run_id, {}).get("stage")
        ANALYSIS_PROGRESS[run_id] = {
            "run_id": run_id,
            "stage": stage,
            "percent": max(0, min(int(percent), 100)),
            "message": message,
            "updated_at": now,
        }
        if len(ANALYSIS_PROGRESS) > 100:
            oldest_ids = sorted(
                ANALYSIS_PROGRESS,
                key=lambda item: ANALYSIS_PROGRESS[item]["updated_at"],
            )[:-100]
            for old_run_id in oldest_ids:
                ANALYSIS_PROGRESS.pop(old_run_id, None)
    if stage != previous_stage:
        LOGGER.info(
            "analysis_progress run_id=%s stage=%s percent=%d message=%s",
            run_id,
            stage,
            percent,
            message,
        )


def cleanup_expired_web_runs(now: float | None = None) -> None:
    """1시간이 지난 완료 결과만 삭제하고 진행 중인 실행은 보존한다."""
    if not WEB_RUNS_DIR.exists():
        return

    cutoff = (time.time() if now is None else now) - WEB_RUN_RETENTION_SECONDS
    with PROGRESS_LOCK:
        active_run_ids = ACTIVE_RUN_IDS.copy()

    for path in WEB_RUNS_DIR.iterdir():
        if (
            path.name in active_run_ids
            or not path.is_dir()
            or not re.fullmatch(r"[0-9a-f]{32}", path.name)
        ):
            continue
        completed_marker = path / COMPLETED_MARKER_NAME
        try:
            if completed_marker.is_file() and completed_marker.stat().st_mtime <= cutoff:
                shutil.rmtree(path)
        except FileNotFoundError:
            # 다른 요청이 같은 만료 폴더를 먼저 정리한 경우다.
            continue
        except OSError as error:
            LOGGER.warning("expired_web_run_cleanup_failed path=%s error=%s", path, error)


def parse_company_names(raw_value: str) -> list[str]:
    """쉼표·줄바꿈·세미콜론으로 입력된 기업명을 중복 없이 분리한다."""
    names = [name.strip() for name in re.split(r"[,;\n\r]+", raw_value)]
    return list(dict.fromkeys(name for name in names if name))


def format_table_value(column: str, value) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if column in AMOUNT_COLUMNS:
        return f"{int(value):,}"
    if column == "연도":
        return str(int(value))
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return str(value)


def visible_result_columns(display) -> list[str]:
    """선택된 모든 기업에 업종상 적용되지 않는 지표 열을 숨긴다."""
    identity_columns = {"기업명", "분석유형", "연도"}
    visible = []
    for column in FINAL_COLUMNS:
        if column in identity_columns:
            visible.append(column)
            continue
        unavailable_for_all = display[column].astype(str).str.startswith(
            "해당 없음("
        ).all()
        if not unavailable_for_all:
            visible.append(column)
    return visible


def format_stock_value(column: str, value) -> str:
    """주식시장 요약표 값을 단위에 맞게 표시한다."""
    if value is None or str(value) in {"<NA>", "nan", "NaT"}:
        return "-"
    if column == "기준일":
        return value.strftime("%Y-%m-%d") if hasattr(value, "strftime") else str(value)
    if column == "기간수익률":
        return f"{float(value):,.2f}%"
    if column in {"최근종가", "기간최고가", "기간최저가"}:
        return f"{int(value):,}원"
    if column == "평균거래량":
        return f"{int(value):,}주"
    if column in {"평균거래대금", "시가총액"}:
        return f"{int(value):,}원"
    return str(value)


def format_kpi_metric(metric: dict) -> str:
    if metric.get("status") != "available" or metric.get("value") is None:
        status_labels = {
            "missing": "출처 데이터 없음",
            "not_applicable": "해당 없음",
            "no_comparison_period": "비교기간 없음",
        }
        return status_labels.get(metric.get("status"), "확인 불가")
    value = metric["value"]
    unit = metric.get("unit", "")
    if isinstance(value, str):
        return value + unit
    if unit in {"원", "주"}:
        return f"{value:,.0f}{unit}"
    if unit == "bp":
        # 금리 변화폭은 bp와 %p를 함께 보여 준다(1bp = 0.01%p).
        bp_text = f"{value:+,.2f}".rstrip("0").rstrip(".")
        pp_text = f"{value / 100:+.4f}".rstrip("0").rstrip(".")
        return f"{bp_text}bp ({pp_text}%p)"
    return f"{value:,.2f}".rstrip("0").rstrip(".") + unit


def build_kpi_cards(payload: dict) -> list[dict]:
    cards = []
    for company in payload.get("companies", []):
        cards.append(
            {
                "company": company["company"],
                "analysis_type": company["analysis_type"],
                "financial_period": company["financial_period"],
                "financial": [
                    {
                        "label": KPI_LABELS.get(name, name),
                        "value": format_kpi_metric(metric),
                        "reason": metric.get("reason"),
                    }
                    for name, metric in company["financial_kpi"].items()
                    if metric.get("status") != "not_applicable"
                ],
                "market": [
                    {
                        "label": KPI_LABELS.get(name, name),
                        "value": format_kpi_metric(metric),
                        "reason": metric.get("reason"),
                    }
                    for name, metric in company["market_kpi"].items()
                ],
                "macro": [
                    {
                        "label": KPI_LABELS.get(name, name),
                        "value": format_kpi_metric(metric),
                        "reason": metric.get("reason"),
                    }
                    for name, metric in company.get("macro_kpi", {}).items()
                ],
            }
        )
    return cards


def _kpi_lookup(payload: dict) -> dict[str, dict[str, dict]]:
    lookup = {}
    for company in payload.get("companies", []):
        metrics = {}
        metrics.update(company.get("financial_kpi", {}))
        metrics.update(company.get("market_kpi", {}))
        metrics.update(company.get("macro_kpi", {}))
        for history in company.get("financial_history", []):
            period = history.get("period")
            for key, metric in history.get("financial_kpi", {}).items():
                metrics[f"financial_history.{period}.{key}"] = metric
        lookup[company["company"]] = metrics
    return lookup


def _kpi_label(metric_key: str) -> str:
    if metric_key.startswith("financial_history."):
        _, period, base_key = metric_key.split(".", 2)
        return f"{period}년 {KPI_LABELS.get(base_key, base_key)}"
    return KPI_LABELS.get(metric_key, metric_key)


def _format_evidence(company: str, metric_key: str, lookup: dict) -> dict:
    metric = lookup[company][metric_key]
    return {
        "key": metric_key,
        "label": _kpi_label(metric_key),
        "value": format_kpi_metric(metric),
    }


def build_gpt_cards(insights: list[dict], comparisons: list[dict], payload: dict):
    """GPT의 KPI 키 참조를 Python이 검증된 실제 값으로 치환한다."""
    lookup = _kpi_lookup(payload)
    cards = []
    for insight in insights:
        card = {**insight}

        def format_section(section: dict) -> dict:
            return {
                "summary": section["summary"],
                "evidence": [
                    _format_evidence(insight["company"], key, lookup)
                    for key in section.get("evidence_keys", [])
                ],
            }

        for section_name in (
            "one_line_summary",
            "growth",
            "profitability",
            "stability",
            "efficiency",
            "market",
            "overall_summary",
        ):
            section = insight[section_name]
            card[section_name] = format_section(section)
        for section_list_name in (
            "relationships_and_mismatches",
            "positive_signals",
            "caution_signals",
            "additional_checks",
        ):
            card[section_list_name] = [
                format_section(section) for section in insight[section_list_name]
            ]
        cards.append(card)

    comparison_cards = []
    for comparison in comparisons:
        comparison_cards.append(
            {
                "summary": comparison["summary"],
                "evidence": [
                    {
                        "company": reference["company"],
                        **_format_evidence(
                            reference["company"], reference["metric_key"], lookup
                        ),
                    }
                    for reference in comparison.get("evidence", [])
                ],
            }
        )
    return cards, comparison_cards


@app.get("/")
def index():
    return render_template(
        "index.html", company_values=[""], number_of_years=5, stock_period="1y"
    )


@app.post("/analyze")
def analyze():
    requested_run_id = request.form.get("run_id", "")
    run_id = requested_run_id if re.fullmatch(r"[0-9a-f]{32}", requested_run_id) else uuid4().hex
    started_at = time.monotonic()
    update_analysis_progress(run_id, "validating", 2, "입력 내용을 확인하고 있습니다.")
    company_values = request.form.getlist("company")
    # 이전 단일 textarea 형식으로 전송된 요청도 계속 처리한다.
    if not company_values and request.form.get("companies"):
        company_values = [request.form.get("companies", "")]
    companies = parse_company_names("\n".join(company_values))
    retained_values = [value.strip() for value in company_values if value.strip()] or [""]
    try:
        number_of_years = int(request.form.get("number_of_years", "5"))
    except ValueError:
        number_of_years = 5
    stock_period = request.form.get("stock_period", "1y")

    if not companies:
        update_analysis_progress(run_id, "failed", 100, "기업명 입력을 확인해 주세요.")
        return render_template(
            "index.html",
            error="기업명을 한 개 이상 입력해 주세요.",
            company_values=retained_values,
            number_of_years=number_of_years,
            stock_period=stock_period,
        ), 400
    if len(companies) > 10:
        update_analysis_progress(run_id, "failed", 100, "기업 수 입력을 확인해 주세요.")
        return render_template(
            "index.html",
            error="한 번에 최대 10개 기업까지 분석할 수 있습니다.",
            company_values=retained_values,
            number_of_years=number_of_years,
            stock_period=stock_period,
        ), 400
    if not 1 <= number_of_years <= 10:
        update_analysis_progress(run_id, "failed", 100, "재무제표 조회기간을 확인해 주세요.")
        return render_template(
            "index.html",
            error="재무제표 조회기간은 1~10년으로 입력해 주세요.",
            company_values=retained_values,
            number_of_years=number_of_years,
            stock_period=stock_period,
        ), 400
    if stock_period not in STOCK_PERIOD_DAYS:
        update_analysis_progress(run_id, "failed", 100, "주가 조회 기간을 확인해 주세요.")
        return render_template(
            "index.html",
            error="주가 조회 기간을 다시 선택해 주세요.",
            company_values=retained_values,
            number_of_years=number_of_years,
            stock_period="1y",
        ), 400

    LOGGER.info(
        "analysis_started run_id=%s company_count=%d financial_years=%d stock_period=%s",
        run_id,
        len(companies),
        number_of_years,
        stock_period,
    )
    run_dir = WEB_RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    with PROGRESS_LOCK:
        ACTIVE_RUN_IDS.add(run_id)
    try:
        integrated = run_integrated_analysis(
            companies,
            number_of_years=number_of_years,
            stock_period=stock_period,
            show_charts=False,
            output_dir=run_dir,
            progress_callback=lambda stage, percent, message: update_analysis_progress(
                run_id, stage, percent, message
            ),
        )
    except (DartAPIError, CompanyNotFoundError, ValueError) as error:
        update_analysis_progress(run_id, "failed", 100, "분석을 완료하지 못했습니다.")
        LOGGER.warning(
            "analysis_failed run_id=%s elapsed_seconds=%.2f error=%s",
            run_id,
            time.monotonic() - started_at,
            error,
            exc_info=True,
        )
        if run_dir.exists():
            shutil.rmtree(run_dir)
        return render_template(
            "index.html",
            error=str(error),
            company_values=retained_values,
            number_of_years=number_of_years,
            stock_period=stock_period,
        ), 400
    except Exception:
        # 예상하지 못한 오류도 이 실행의 임시 결과만 정리한 뒤 원래 예외를 전달한다.
        if run_dir.exists():
            shutil.rmtree(run_dir)
        raise
    finally:
        with PROGRESS_LOCK:
            ACTIVE_RUN_IDS.discard(run_id)

    result = integrated.financial
    display = format_result_for_csv(result)
    visible_columns = visible_result_columns(display)
    rows = [
        [format_table_value(column, row[column]) for column in visible_columns]
        for _, row in display.iterrows()
    ]
    charts_dir = run_dir / "charts"
    chart_files = sorted(path.name for path in charts_dir.glob("*.png"))
    chart_urls = [
        url_for("run_file", run_id=run_id, filename=f"charts/{filename}")
        for filename in chart_files
    ]
    stock_charts_dir = run_dir / "stock_charts"
    stock_chart_urls = [
        url_for("run_file", run_id=run_id, filename=f"stock_charts/{path.name}")
        for path in sorted(stock_charts_dir.glob("*.png"))
    ]
    stock_columns = list(integrated.stock_summary.columns)
    stock_rows = [
        [format_stock_value(column, row[column]) for column in stock_columns]
        for _, row in integrated.stock_summary.iterrows()
    ]
    stock_cards = [
        {
            "company": row["기업명"],
            "code": row["종목코드"],
            "date": format_stock_value("기준일", row["기준일"]),
            "close": format_stock_value("최근종가", row["최근종가"]),
            "return": format_stock_value("기간수익률", row["기간수익률"]),
            "market_cap": format_stock_value("시가총액", row["시가총액"]),
        }
        for _, row in integrated.stock_summary.iterrows()
    ]
    csv_url = url_for(
        "run_file", run_id=run_id, filename="financial_analysis.csv"
    )
    stock_prices_csv_url = (
        url_for("run_file", run_id=run_id, filename="stock_prices.csv")
        if (run_dir / "stock_prices.csv").is_file()
        else None
    )
    stock_summary_csv_url = (
        url_for("run_file", run_id=run_id, filename="stock_summary.csv")
        if (run_dir / "stock_summary.csv").is_file()
        else None
    )
    investor_summary_csv_url = (
        url_for("run_file", run_id=run_id, filename="investor_summary.csv")
        if (run_dir / "investor_summary.csv").is_file()
        else None
    )
    market_macro_csv_url = (
        url_for("run_file", run_id=run_id, filename="market_macro.csv")
        if (run_dir / "market_macro.csv").is_file()
        else None
    )
    data_quality_csv_url = (
        url_for("run_file", run_id=run_id, filename="data_quality_log.csv")
        if (run_dir / "data_quality_log.csv").is_file()
        else None
    )
    gpt_insight_cards, gpt_comparison_cards = build_gpt_cards(
        integrated.gpt_insights,
        integrated.gpt_comparisons,
        integrated.kpi_payload,
    )
    update_analysis_progress(run_id, "complete", 100, "분석이 완료되었습니다.")
    (run_dir / COMPLETED_MARKER_NAME).touch()
    cleanup_expired_web_runs()
    LOGGER.info(
        "analysis_completed run_id=%s company_count=%d warning_count=%d elapsed_seconds=%.2f",
        run_id,
        integrated.financial["기업명"].nunique(),
        len(integrated.warnings),
        time.monotonic() - started_at,
    )
    return render_template(
        "result.html",
        companies=display["기업명"].drop_duplicates().tolist(),
        columns=visible_columns,
        rows=rows,
        chart_urls=chart_urls,
        stock_chart_urls=stock_chart_urls,
        stock_columns=stock_columns,
        stock_rows=stock_rows,
        stock_cards=stock_cards,
        stock_period_label=STOCK_PERIOD_LABELS[stock_period],
        kpi_cards=build_kpi_cards(integrated.kpi_payload),
        gpt_insights=gpt_insight_cards,
        gpt_comparisons=gpt_comparison_cards,
        warnings=integrated.warnings,
        csv_url=csv_url,
        stock_prices_csv_url=stock_prices_csv_url,
        stock_summary_csv_url=stock_summary_csv_url,
        investor_summary_csv_url=investor_summary_csv_url,
        market_macro_csv_url=market_macro_csv_url,
        data_quality_csv_url=data_quality_csv_url,
    )


@app.get("/analysis-progress/<run_id>")
def analysis_progress(run_id: str):
    if not re.fullmatch(r"[0-9a-f]{32}", run_id):
        abort(404)
    with PROGRESS_LOCK:
        progress = ANALYSIS_PROGRESS.get(run_id)
    if progress is None:
        return jsonify(
            {
                "run_id": run_id,
                "stage": "waiting",
                "percent": 0,
                "message": "분석 시작을 기다리고 있습니다.",
            }
        )
    return jsonify(progress)


@app.get("/results/<run_id>/<path:filename>")
def run_file(run_id: str, filename: str):
    if not re.fullmatch(r"[0-9a-f]{32}", run_id):
        abort(404)
    return send_from_directory(WEB_RUNS_DIR / run_id, filename, as_attachment=False)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    WEB_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    app.run(host="127.0.0.1", port=5000, debug=False)
