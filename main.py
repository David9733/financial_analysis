"""기업명 입력부터 CSV와 차트 생성까지 전체 분석을 실행한다."""

from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path

import pandas as pd

try:  # 패키지로 import하는 경우
    from .dart_api import CompanyNotFoundError, DartAPIError, DartClient, get_api_key
    from .financial_analysis import (
        RAW_COLUMNS,
        calculate_metrics,
        extract_source_accounts,
        format_result_for_csv,
        select_output_periods,
    )
    from .visualization import create_visualizations
except ImportError:  # main.py를 직접 실행하는 경우
    from dart_api import CompanyNotFoundError, DartAPIError, DartClient, get_api_key
    from financial_analysis import (
        RAW_COLUMNS,
        calculate_metrics,
        extract_source_accounts,
        format_result_for_csv,
        select_output_periods,
    )
    from visualization import create_visualizations


# 초보 사용자는 아래 기업명과 기간만 수정하면 된다.
COMPANIES = ["CJ프레시웨이", "롯데웰푸드"]
START_YEAR = None
END_YEAR = None
NUMBER_OF_YEARS = 5

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR
OUTPUT_DIR = APP_DIR / "output"


def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def _query_years(
    client: DartClient,
    corp_code: str,
    company_name: str,
    start_year: int | None,
    end_year: int | None,
    number_of_years: int,
) -> list[tuple[int, list[dict], str]]:
    """명시 기간 또는 최근 공시 연도를 조회한다."""
    logger = logging.getLogger(__name__)
    collected = []

    if start_year is not None or end_year is not None:
        first = start_year if start_year is not None else max(2015, (end_year or date.today().year) - number_of_years + 1)
        last = end_year if end_year is not None else date.today().year
        # 평균자본과 평균매출채권 계산에 필요한 직전 연도도 내부적으로 조회한다.
        candidate_years = range(last, max(2014, first - 1) - 1, -1)
        required_count = None
    else:
        candidate_years = range(date.today().year, 2014, -1)
        required_count = number_of_years + 1

    for year in candidate_years:
        response = client.get_annual_financials(corp_code, year)
        if response is None:
            logger.info("%s %s년: 사업보고서 재무데이터가 없어 건너뜁니다.", company_name, year)
            continue
        rows, fs_div = response
        collected.append((year, rows, fs_div))
        logger.info("%s %s년 %s 재무데이터 수집 완료", company_name, year, fs_div)
        if required_count is not None and len(collected) >= required_count:
            break

    return sorted(collected, key=lambda item: item[0])


def run_analysis(
    companies: list[str],
    start_year: int | None = None,
    end_year: int | None = None,
    number_of_years: int = 5,
    show_charts: bool = True,
    output_dir: Path | None = None,
) -> pd.DataFrame:
    """DART 수집 → 지표 계산 → CSV 저장 → 차트 생성을 실행한다."""
    configure_console()
    if not companies:
        raise ValueError("기업명을 1개 이상 입력해 주세요.")
    if number_of_years < 1:
        raise ValueError("number_of_years는 1 이상이어야 합니다.")
    if start_year is not None and end_year is not None and start_year > end_year:
        raise ValueError("START_YEAR는 END_YEAR보다 클 수 없습니다.")

    api_key = get_api_key(PROJECT_ROOT)
    client = DartClient(api_key)
    raw_records = []

    for input_name in companies:
        company = client.find_company(input_name)
        company_name = company["corp_name"]
        yearly_data = _query_years(
            client,
            company["corp_code"],
            company_name,
            start_year,
            end_year,
            number_of_years,
        )
        if not yearly_data:
            logging.warning("%s: 분석 가능한 사업보고서가 없습니다.", company_name)
            continue
        for year, rows, fs_div in yearly_data:
            raw_records.extend(
                extract_source_accounts(company_name, year, fs_div, rows)
            )

    if not raw_records:
        raise DartAPIError("분석 가능한 재무 데이터를 가져오지 못했습니다.")

    raw_df = pd.DataFrame(raw_records, columns=RAW_COLUMNS)
    all_metrics = calculate_metrics(raw_df)
    result = select_output_periods(
        all_metrics,
        number_of_years=number_of_years,
        start_year=start_year,
        end_year=end_year,
    )
    if result.empty:
        raise DartAPIError("선택한 기간에 분석 가능한 재무 데이터가 없습니다.")

    target_output_dir = Path(output_dir) if output_dir is not None else OUTPUT_DIR
    target_output_dir.mkdir(parents=True, exist_ok=True)
    result_path = target_output_dir / "financial_analysis.csv"
    # utf-8-sig는 Excel에서도 한글 CSV가 깨지지 않도록 BOM을 포함한다.
    format_result_for_csv(result).to_csv(result_path, index=False, encoding="utf-8-sig")
    create_visualizations(result, target_output_dir / "charts", show_charts=show_charts)

    print(f"분석 CSV: {result_path}")
    print(f"차트 폴더: {target_output_dir / 'charts'}")
    return result


def main() -> int:
    configure_console()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        result = run_analysis(
            COMPANIES,
            start_year=START_YEAR,
            end_year=END_YEAR,
            number_of_years=NUMBER_OF_YEARS,
            show_charts=False,
        )
    except (DartAPIError, CompanyNotFoundError, ValueError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1

    print("\n분석 결과")
    print(result.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
