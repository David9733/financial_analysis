"""기업명 입력부터 CSV와 차트 생성까지 전체 분석을 실행한다."""

from __future__ import annotations

import logging
import json
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

import pandas as pd

if __package__:  # ``python -m src.main`` 또는 패키지 import
    from .dart_api import CompanyNotFoundError, DartAPIError, DartClient, get_api_key
    from .financial_analysis import (
        RAW_COLUMNS,
        calculate_metrics,
        extract_source_accounts,
        format_result_for_csv,
        select_output_periods,
    )
    from .visualization import create_visualizations
    from .investor_analysis import (
        InvestorDataError,
        empty_investor_summary,
        get_investor_trading,
    )
    from .data_quality import (
        ACTION_SCALE_FIX,
        LOG_COLUMNS,
        QualityLog,
        correct_scale_errors,
    )
    from .gpt_analysis import GPTAnalysisError, analyze_kpis
    from .kpi_analysis import build_kpi_payload
    from .macro_analysis import (
        FX_COLUMN,
        MACRO_LOOKBACK_DAYS,
        MARKET_MACRO_COLUMNS,
        RATE_COLUMN,
        merge_macro_with_prices,
        prepare_macro_series,
    )
    from .macro_api import (
        ExchangeRateClient,
        InterestRateClient,
        MacroAPIError,
        get_ecos_api_key,
        get_exim_api_key,
    )
    from .stock_analysis import prepare_stock_prices, summarize_stock_prices
    from .stock_api import StockAPIError, StockClient, get_stock_api_key
    from .stock_visualization import (
        create_daily_change_visualizations,
        create_macro_visualizations,
        create_stock_visualizations,
    )
else:  # ``python src/main.py``로 직접 실행
    from dart_api import CompanyNotFoundError, DartAPIError, DartClient, get_api_key
    from financial_analysis import (
        RAW_COLUMNS,
        calculate_metrics,
        extract_source_accounts,
        format_result_for_csv,
        select_output_periods,
    )
    from visualization import create_visualizations
    from investor_analysis import (
        InvestorDataError,
        empty_investor_summary,
        get_investor_trading,
    )
    from data_quality import (
        ACTION_SCALE_FIX,
        LOG_COLUMNS,
        QualityLog,
        correct_scale_errors,
    )
    from gpt_analysis import GPTAnalysisError, analyze_kpis
    from kpi_analysis import build_kpi_payload
    from macro_analysis import (
        FX_COLUMN,
        MACRO_LOOKBACK_DAYS,
        MARKET_MACRO_COLUMNS,
        RATE_COLUMN,
        merge_macro_with_prices,
        prepare_macro_series,
    )
    from macro_api import (
        ExchangeRateClient,
        InterestRateClient,
        MacroAPIError,
        get_ecos_api_key,
        get_exim_api_key,
    )
    from stock_analysis import prepare_stock_prices, summarize_stock_prices
    from stock_api import StockAPIError, StockClient, get_stock_api_key
    from stock_visualization import (
        create_daily_change_visualizations,
        create_macro_visualizations,
        create_stock_visualizations,
    )


# 초보 사용자는 아래 기업명과 기간만 수정하면 된다.
COMPANIES = ["CJ프레시웨이", "롯데웰푸드"]
START_YEAR = None
END_YEAR = None
NUMBER_OF_YEARS = 5

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
CLI_OUTPUT_DIR = OUTPUT_DIR / "cli"
CACHE_DIR = PROJECT_ROOT / ".cache"
STOCK_PERIOD_DAYS = {"1m": 31, "3m": 92, "1y": 366, "3y": 1096}
LOGGER = logging.getLogger(__name__)
ProgressCallback = Callable[[str, int, str], None]


def _notify_progress(
    callback: ProgressCallback | None,
    stage: str,
    percent: int,
    message: str,
) -> None:
    if callback is not None:
        callback(stage, percent, message)


def reset_output_directory(output_dir: Path) -> Path:
    """Remove results from earlier runs and recreate an empty output directory."""
    target = Path(output_dir)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    return target


@dataclass
class IntegratedAnalysisResult:
    """기존 재무분석과 선택적으로 수집한 주식시장 분석 결과."""

    financial: pd.DataFrame
    stock_prices: pd.DataFrame
    stock_summary: pd.DataFrame
    warnings: list[str]
    investor_summary: pd.DataFrame = field(default_factory=empty_investor_summary)
    kpi_payload: dict = field(default_factory=dict)
    gpt_insights: list[dict] = field(default_factory=list)
    gpt_comparisons: list[dict] = field(default_factory=list)
    market_macro: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(columns=MARKET_MACRO_COLUMNS)
    )
    quality_log: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(columns=LOG_COLUMNS)
    )


PRICE_LEVEL_COLUMNS = ("시가", "고가", "저가")


def correct_stock_price_errors(
    frame: pd.DataFrame, company_name: str, log: QualityLog
) -> pd.DataFrame:
    """종가의 소수점·단위 오류를 고치고 같은 배율로 튄 시가·고가·저가도 함께 고친다."""
    corrected, multiplier = correct_scale_errors(
        frame, "종가", log, target="종가", company=company_name
    )
    for index in multiplier[multiplier != 1].index:
        scale = multiplier.at[index]
        original_close = frame.at[index, "종가"]
        for column in PRICE_LEVEL_COLUMNS:
            value = corrected.at[index, column]
            if pd.isna(value) or value <= 0 or original_close <= 0:
                continue
            # 같은 날 시가·고가·저가는 종가와 비슷한 수준이므로, 원래 종가와 같은
            # 수준(±50%)이면 같은 배율로 잘못 입력된 것으로 본다.
            if 0.5 <= value / original_close <= 2:
                corrected.at[index, column] = value * scale
                log.add(
                    column,
                    corrected.at[index, "기준일"],
                    ACTION_SCALE_FIX,
                    value,
                    value * scale,
                    "종가와 같은 배율의 소수점 또는 단위 오류",
                    company_name,
                )
    if (multiplier != 1).any():
        first_close = corrected["종가"].iloc[0]
        corrected["정규화주가"] = (
            corrected["종가"] / first_close * 100 if first_close not in (None, 0) else pd.NA
        )
    return corrected.reset_index(drop=True)


def collect_market_macro(
    stock_prices: pd.DataFrame,
    warnings: list[str],
    progress_callback: ProgressCallback | None = None,
    log: QualityLog | None = None,
) -> pd.DataFrame:
    """주가 거래일 범위의 환율·금리를 수집해 거래일 기준으로 병합한다.

    API 키가 없거나 호출이 실패해도 경고만 남기고 빈 열로 계속 진행한다.
    """
    if stock_prices.empty:
        return pd.DataFrame(columns=MARKET_MACRO_COLUMNS)

    trading_start = stock_prices["기준일"].min().date()
    trading_end = stock_prices["기준일"].max().date()
    # 첫 거래일의 매크로 값이 비었을 때 ffill할 직전 값을 확보한다.
    fetch_start = trading_start - timedelta(days=MACRO_LOOKBACK_DAYS)

    _notify_progress(progress_callback, "macro", 71, "원/달러 환율을 수집하고 있습니다.")
    fx_rows: list = []
    try:
        fx_client = ExchangeRateClient(
            get_exim_api_key(PROJECT_ROOT), cache_path=CACHE_DIR / "exim_usd_krw.json"
        )
        fx_series = fx_client.get_usd_krw(fetch_start, trading_end)
        fx_rows = fx_series.rows
        if fx_series.failed_dates:
            warnings.append(
                f"환율: {len(fx_series.failed_dates)}개 날짜 조회에 실패해 직전 값으로 채웠습니다."
            )
    except (MacroAPIError, ValueError) as error:
        warnings.append(f"환율 데이터를 불러오지 못했습니다. ({error})")

    _notify_progress(progress_callback, "macro", 74, "국고채 3년 금리를 수집하고 있습니다.")
    rate_rows: list = []
    try:
        rate_client = InterestRateClient(get_ecos_api_key(PROJECT_ROOT))
        rate_rows = rate_client.get_treasury_3y(fetch_start, trading_end).rows
    except (MacroAPIError, ValueError) as error:
        warnings.append(f"금리 데이터를 불러오지 못했습니다. ({error})")

    # 환율·금리를 모두 못 받아도 종가 하루 변화 이상치는 표시한다.
    merged = merge_macro_with_prices(
        stock_prices,
        prepare_macro_series(fx_rows, FX_COLUMN),
        prepare_macro_series(rate_rows, RATE_COLUMN),
        log=log,
    )
    LOGGER.info(
        "macro_merged trading_rows=%d merged_rows=%d fx_rows=%d rate_rows=%d",
        len(stock_prices),
        len(merged),
        len(fx_rows),
        len(rate_rows),
    )
    return merged


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
    progress_callback: ProgressCallback | None = None,
) -> pd.DataFrame:
    """DART 수집 → 지표 계산 → CSV 저장 → 차트 생성을 실행한다."""
    configure_console()
    target_output_dir = reset_output_directory(
        Path(output_dir) if output_dir is not None else CLI_OUTPUT_DIR
    )
    if not companies:
        raise ValueError("기업명을 1개 이상 입력해 주세요.")
    if number_of_years < 1:
        raise ValueError("number_of_years는 1 이상이어야 합니다.")
    if start_year is not None and end_year is not None and start_year > end_year:
        raise ValueError("START_YEAR는 END_YEAR보다 클 수 없습니다.")

    _notify_progress(progress_callback, "financial", 5, "DART 기업 정보를 확인하고 있습니다.")
    api_key = get_api_key(PROJECT_ROOT)
    client = DartClient(api_key, data_dir=CACHE_DIR)
    raw_records = []
    resolved_companies = []

    for index, input_name in enumerate(companies):
        progress = 8 + int(index / max(len(companies), 1) * 32)
        _notify_progress(
            progress_callback,
            "financial",
            progress,
            f"{input_name} 재무제표를 수집하고 있습니다.",
        )
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
        resolved_companies.append(company)
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

    # 통합 분석이 DART 기업 목록을 다시 받지 않고 종목코드를 재사용한다.
    result.attrs["resolved_companies"] = resolved_companies

    result_path = target_output_dir / "financial_analysis.csv"
    # utf-8-sig는 Excel에서도 한글 CSV가 깨지지 않도록 BOM을 포함한다.
    format_result_for_csv(result).to_csv(result_path, index=False, encoding="utf-8-sig")
    create_visualizations(result, target_output_dir / "charts", show_charts=show_charts)
    _notify_progress(progress_callback, "financial", 42, "재무지표와 차트를 생성했습니다.")

    print(f"분석 CSV: {result_path}")
    print(f"차트 폴더: {target_output_dir / 'charts'}")
    return result


def run_integrated_analysis(
    companies: list[str],
    start_year: int | None = None,
    end_year: int | None = None,
    number_of_years: int = 5,
    stock_period: str = "1y",
    show_charts: bool = True,
    output_dir: Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> IntegratedAnalysisResult:
    """재무분석 후 상장기업의 일별 주식시세를 결합한다."""
    if stock_period not in STOCK_PERIOD_DAYS:
        raise ValueError("주가 조회 기간은 1m, 3m, 1y, 3y 중 하나여야 합니다.")

    target_output_dir = Path(output_dir) if output_dir is not None else CLI_OUTPUT_DIR
    financial = run_analysis(
        companies,
        start_year=start_year,
        end_year=end_year,
        number_of_years=number_of_years,
        show_charts=show_charts,
        output_dir=target_output_dir,
        progress_callback=progress_callback,
    )
    resolved_companies = financial.attrs.get("resolved_companies", [])
    warnings: list[str] = []
    price_frames: list[pd.DataFrame] = []
    investor_frames: list[pd.DataFrame] = []
    quality_log = QualityLog()

    stock_client = None
    try:
        stock_client = StockClient(get_stock_api_key(PROJECT_ROOT))
    except StockAPIError as error:
        warnings.append(str(error))

    period_end = date.today()
    period_start = period_end - timedelta(days=STOCK_PERIOD_DAYS[stock_period])
    _notify_progress(progress_callback, "market", 46, "주식시장 데이터를 준비하고 있습니다.")
    for index, company in enumerate(resolved_companies):
        if stock_client is None:
            break
        company_name = company["corp_name"]
        market_progress = 48 + int(index / max(len(resolved_companies), 1) * 22)
        _notify_progress(
            progress_callback,
            "market",
            market_progress,
            f"{company_name} 주가와 투자자 동향을 수집하고 있습니다.",
        )
        stock_code = company.get("stock_code", "")
        if not stock_code:
            warnings.append(f"{company_name}: 상장 종목코드가 없어 재무분석만 제공합니다.")
            continue
        try:
            rows = stock_client.get_stock_prices(
                stock_code, start_date=period_start, end_date=period_end
            )
        except (StockAPIError, ValueError) as error:
            warnings.append(f"{company_name}: 주식시세 API 조회 실패 ({error})")
            continue
        frame = prepare_stock_prices(rows, company_name, stock_code)
        if frame.empty:
            warnings.append(f"{company_name}: 선택 기간의 주식시세 데이터가 없습니다.")
            continue
        frame = correct_stock_price_errors(frame, company_name, quality_log)
        price_frames.append(frame)
        actual_start = frame["기준일"].min().date()
        actual_end = frame["기준일"].max().date()
        try:
            investor_frame = get_investor_trading(
                company_name, stock_code, actual_start, actual_end
            )
        except InvestorDataError as error:
            warnings.append(f"{company_name}: 투자자별 수급 조회 실패 ({error})")
        else:
            if investor_frame.empty:
                warnings.append(f"{company_name}: 선택 기간의 투자자별 수급 데이터가 없습니다.")
            else:
                investor_frames.append(investor_frame)

    if price_frames:
        stock_prices = pd.concat(price_frames, ignore_index=True)
        stock_summary = summarize_stock_prices(stock_prices)
        investor_summary = (
            pd.concat(investor_frames, ignore_index=True)
            if investor_frames
            else empty_investor_summary()
        )
        stock_prices.to_csv(
            target_output_dir / "stock_prices.csv", index=False, encoding="utf-8-sig"
        )
        stock_summary.to_csv(
            target_output_dir / "stock_summary.csv", index=False, encoding="utf-8-sig"
        )
        if not investor_summary.empty:
            investor_summary.to_csv(
                target_output_dir / "investor_summary.csv",
                index=False,
                encoding="utf-8-sig",
            )
        create_stock_visualizations(
            stock_prices,
            target_output_dir / "stock_charts",
            investor_summary=investor_summary,
        )
    else:
        stock_prices = prepare_stock_prices([], "", "")
        stock_summary = summarize_stock_prices(stock_prices)
        investor_summary = empty_investor_summary()

    market_macro = collect_market_macro(
        stock_prices, warnings, progress_callback, log=quality_log
    )
    if not market_macro.empty:
        market_macro.to_csv(
            target_output_dir / "market_macro.csv", index=False, encoding="utf-8-sig"
        )
        create_macro_visualizations(market_macro, target_output_dir / "stock_charts")
        create_daily_change_visualizations(
            market_macro, target_output_dir / "stock_charts"
        )

    quality_frame = quality_log.to_frame()
    if not quality_frame.empty:
        quality_frame.to_csv(
            target_output_dir / "data_quality_log.csv", index=False, encoding="utf-8-sig"
        )
        warnings.append(quality_log.summary_text())
    LOGGER.info(
        "data_quality records=%d %s", len(quality_frame), quality_log.summary_text()
    )

    kpi_payload = build_kpi_payload(
        financial, stock_prices, stock_period, market_macro=market_macro
    )
    (target_output_dir / "kpi_analysis.json").write_text(
        json.dumps(kpi_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    gpt_insights: list[dict] = []
    gpt_comparisons: list[dict] = []
    _notify_progress(progress_callback, "gpt", 78, "GPT 자동 인사이트를 생성하고 있습니다.")
    gpt_started_at = time.monotonic()
    try:
        gpt_result = analyze_kpis(kpi_payload, PROJECT_ROOT)
        gpt_insights = gpt_result["analyses"]
        gpt_comparisons = gpt_result["comparisons"]
    except GPTAnalysisError as error:
        warnings.append(f"GPT 자동 분석을 불러오지 못했습니다. ({error})")
        LOGGER.warning(
            "gpt_analysis_failed company_count=%d elapsed_seconds=%.2f error=%s",
            len(kpi_payload.get("companies", [])),
            time.monotonic() - gpt_started_at,
            error,
        )
    else:
        LOGGER.info(
            "gpt_analysis_completed company_count=%d comparison_count=%d elapsed_seconds=%.2f",
            len(gpt_insights),
            len(gpt_comparisons),
            time.monotonic() - gpt_started_at,
        )
    if gpt_insights or gpt_comparisons:
        (target_output_dir / "gpt_insights.json").write_text(
            json.dumps(
                {"analyses": gpt_insights, "comparisons": gpt_comparisons},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    _notify_progress(progress_callback, "finalizing", 96, "결과 화면을 정리하고 있습니다.")

    return IntegratedAnalysisResult(
        financial=financial,
        stock_prices=stock_prices,
        stock_summary=stock_summary,
        warnings=warnings,
        investor_summary=investor_summary,
        kpi_payload=kpi_payload,
        gpt_insights=gpt_insights,
        gpt_comparisons=gpt_comparisons,
        market_macro=market_macro,
        quality_log=quality_frame,
    )


def main() -> int:
    configure_console()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        integrated = run_integrated_analysis(
            COMPANIES,
            start_year=START_YEAR,
            end_year=END_YEAR,
            number_of_years=NUMBER_OF_YEARS,
            stock_period="1y",
            show_charts=False,
        )
    except (DartAPIError, CompanyNotFoundError, ValueError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1

    print("\n분석 결과")
    print(integrated.financial.to_string(index=False))
    if not integrated.stock_summary.empty:
        print("\n주식시장 요약")
        print(integrated.stock_summary.to_string(index=False))
    for warning in integrated.warnings:
        print(f"주의: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
