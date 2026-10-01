"""기업명을 입력해 재무분석 표와 차트를 보여주는 로컬 웹 애플리케이션."""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from flask import Flask, abort, render_template, request, send_from_directory, url_for

try:  # src.app 모듈로 import하는 경우
    from .dart_api import CompanyNotFoundError, DartAPIError
    from .financial_analysis import FINAL_COLUMNS, format_result_for_csv
    from .main import OUTPUT_DIR, run_analysis
except ImportError:  # src/app.py를 직접 실행하는 경우
    from dart_api import CompanyNotFoundError, DartAPIError
    from financial_analysis import FINAL_COLUMNS, format_result_for_csv
    from main import OUTPUT_DIR, run_analysis


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
WEB_RUNS_DIR = OUTPUT_DIR / "web_runs"
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

app = Flask(
    __name__,
    template_folder=str(PROJECT_ROOT / "templates"),
    static_folder=str(PROJECT_ROOT / "static"),
)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024


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


@app.get("/")
def index():
    return render_template("index.html", company_values=[""], number_of_years=5)


@app.post("/analyze")
def analyze():
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

    if not companies:
        return render_template(
            "index.html",
            error="기업명을 한 개 이상 입력해 주세요.",
            company_values=retained_values,
            number_of_years=number_of_years,
        ), 400
    if len(companies) > 10:
        return render_template(
            "index.html",
            error="한 번에 최대 10개 기업까지 분석할 수 있습니다.",
            company_values=retained_values,
            number_of_years=number_of_years,
        ), 400
    if not 1 <= number_of_years <= 10:
        return render_template(
            "index.html",
            error="분석 기간은 1~10년으로 입력해 주세요.",
            company_values=retained_values,
            number_of_years=number_of_years,
        ), 400

    run_id = uuid4().hex
    run_dir = WEB_RUNS_DIR / run_id
    try:
        result = run_analysis(
            companies,
            number_of_years=number_of_years,
            show_charts=False,
            output_dir=run_dir,
        )
    except (DartAPIError, CompanyNotFoundError, ValueError) as error:
        return render_template(
            "index.html",
            error=str(error),
            company_values=retained_values,
            number_of_years=number_of_years,
        ), 400

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
    csv_url = url_for(
        "run_file", run_id=run_id, filename="financial_analysis.csv"
    )
    return render_template(
        "result.html",
        companies=display["기업명"].drop_duplicates().tolist(),
        columns=visible_columns,
        rows=rows,
        chart_urls=chart_urls,
        csv_url=csv_url,
    )


@app.get("/results/<run_id>/<path:filename>")
def run_file(run_id: str, filename: str):
    if not re.fullmatch(r"[0-9a-f]{32}", run_id):
        abort(404)
    return send_from_directory(WEB_RUNS_DIR / run_id, filename, as_attachment=False)


if __name__ == "__main__":
    WEB_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    app.run(host="127.0.0.1", port=5000, debug=False)
