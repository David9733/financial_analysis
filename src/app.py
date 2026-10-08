"""기업명을 입력해 재무분석 표와 차트를 보여주는 로컬 웹 애플리케이션."""

from __future__ import annotations

import logging
import re
import shutil
import threading
import time
from pathlib import Path
from uuid import uuid4

import pandas as pd
from flask import Flask, abort, jsonify, render_template, request, send_from_directory, url_for

if __package__:  # ``python -m src.app`` 또는 패키지 import
    from .correlation_insight import build_company_correlation_insights
    from .dart_api import CompanyNotFoundError, DartAPIError
    from .financial_analysis import FINAL_COLUMNS, format_result_for_csv
    from .main import (
        ENABLE_GPT_INSIGHTS,
        OUTPUT_DIR,
        STOCK_PERIOD_DAYS,
        run_integrated_analysis,
    )
else:  # ``python src/app.py``로 직접 실행
    from correlation_insight import build_company_correlation_insights
    from dart_api import CompanyNotFoundError, DartAPIError
    from financial_analysis import FINAL_COLUMNS, format_result_for_csv
    from main import (
        ENABLE_GPT_INSIGHTS,
        OUTPUT_DIR,
        STOCK_PERIOD_DAYS,
        run_integrated_analysis,
    )


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
WEB_RUNS_DIR = OUTPUT_DIR / "web_runs"
WEB_RUN_RETENTION_SECONDS = 60 * 60
COMPLETED_MARKER_NAME = ".completed"
STOCK_PERIOD_LABELS = {
    "1m": "1개월",
    "3m": "3개월",
    "6m": "6개월",
    "1y": "1년",
    "3y": "3년",
}
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
    "market_index_name": "비교 시장지수",
    "market_index_latest": "시장지수(최근)",
    "market_index_change": "시장지수 기간 수익률",
    "treasury_3y_latest": "금리(최근)",
    "treasury_3y_change_bp": "금리 기간 변화폭",
    "credit_spread_latest": "신용 스프레드(최근)",
    "credit_spread_change_bp": "신용 스프레드 기간 변화폭",
    "corr_return_usd_krw": "주가 수익률-환율 변화율 상관계수",
    "corr_return_market_index": "주가 수익률-시장지수 수익률 상관계수",
    "corr_return_treasury_3y": "주가 수익률-금리 변화폭 상관계수",
    "corr_return_credit_spread": "주가 수익률-신용 스프레드 변화폭 상관계수",
    "radar_usd_krw_market_corr": "시장지수 수익률-환율 변화율 상관계수",
    "radar_usd_krw_excess_corr": "환율 시장 대비 상관 차이",
    "radar_usd_krw_sign_persistence": "환율 이동상관 부호 유지율",
    "radar_usd_krw_sign_switches": "환율 이동상관 부호 전환",
    "radar_usd_krw_sign_switch_rate": "환율 이동상관 부호 전환율",
    "radar_usd_krw_judgement": "환율 매크로 레이더 판정",
    "radar_treasury_3y_market_corr": "시장지수 수익률-금리 변화폭 상관계수",
    "radar_treasury_3y_excess_corr": "금리 시장 대비 상관 차이",
    "radar_treasury_3y_sign_persistence": "금리 이동상관 부호 유지율",
    "radar_treasury_3y_sign_switches": "금리 이동상관 부호 전환",
    "radar_treasury_3y_sign_switch_rate": "금리 이동상관 부호 전환율",
    "radar_treasury_3y_judgement": "금리 매크로 레이더 판정",
    "radar_credit_spread_market_corr": "시장지수 수익률-신용 스프레드 상관계수",
    "radar_credit_spread_excess_corr": "신용 스프레드 시장 대비 상관 차이",
    "radar_credit_spread_sign_persistence": "신용 스프레드 이동상관 부호 유지율",
    "radar_credit_spread_sign_switches": "신용 스프레드 이동상관 부호 전환",
    "radar_credit_spread_sign_switch_rate": "신용 스프레드 이동상관 부호 전환율",
    "radar_credit_spread_judgement": "신용 스프레드 매크로 레이더 판정",
    "corr_usd_krw_treasury_3y_level": "환율값-금리값 상관계수",
    "corr_usd_krw_treasury_3y_change": "환율 변화율-금리 변화폭 상관계수",
    "macro_filled_days": "외부 요인 보간 거래일",
    "price_outlier_days": "종가 하루 변화 이상치",
    "usd_krw_outlier_days": "환율 하루 변화 이상치",
    "market_index_outlier_days": "시장지수 하루 변화 이상치",
    "treasury_3y_outlier_days": "금리 하루 변화 이상치",
    "credit_spread_outlier_days": "신용 스프레드 하루 변화 이상치",
}
KPI_HELP_TEXT = {
    "revenue_growth": (
        "전년 매출 대비 당해 매출의 증감률입니다. 계산식은 "
        "(당해 매출 ÷ 전년 매출 - 1) × 100입니다."
    ),
    "operating_profit_growth": (
        "전년 영업이익 대비 당해 영업이익의 증감률입니다. 계산식은 "
        "(당해 영업이익 ÷ 전년 영업이익 - 1) × 100입니다."
    ),
    "net_income_growth": (
        "전년 당기순이익 대비 당해 당기순이익의 증감률입니다. 계산식은 "
        "(당해 순이익 ÷ 전년 순이익 - 1) × 100입니다."
    ),
    "operating_margin": "매출 중 영업이익이 차지하는 비율로, 영업이익 ÷ 매출 × 100입니다.",
    "net_margin": "매출 중 당기순이익이 차지하는 비율로, 당기순이익 ÷ 매출 × 100입니다.",
    "roe": (
        "자기자본으로 당기순이익을 얼마나 냈는지 나타냅니다. "
        "당기순이익 ÷ 전년과 당년 평균자본 × 100입니다."
    ),
    "roa": (
        "총자산으로 당기순이익을 얼마나 냈는지 나타냅니다. "
        "당기순이익 ÷ 전년과 당년 평균자산 × 100입니다."
    ),
    "debt_ratio": "자기자본 대비 부채 비율로, 부채총계 ÷ 자본총계 × 100입니다.",
    "interest_coverage_ratio": (
        "영업이익으로 실제 지급한 이자를 감당하는 정도입니다. "
        "영업이익 ÷ 현금흐름표상 이자지급액이며 단위는 배입니다."
    ),
    "accounts_receivable_days": (
        "매출채권이 매출로 회수되는 데 걸리는 기간을 단순 환산한 값입니다. "
        "기말 매출채권 ÷ 매출 × 365일입니다."
    ),
    "period_return": (
        "선택한 주가 조회기간의 첫 종가와 마지막 종가를 비교한 수익률입니다. "
        "계산식은 (마지막 종가 ÷ 첫 종가 - 1) × 100입니다."
    ),
    "daily_volatility": (
        "선택 기간의 일간 종가 수익률이 얼마나 흩어져 있는지 나타내는 표준편차입니다. "
        "값이 클수록 하루 가격 변동이 컸다는 뜻입니다."
    ),
    "average_volume": "선택한 주가 조회기간에 거래된 일평균 주식 수입니다.",
    "average_trading_value": "선택한 주가 조회기간의 일별 거래대금을 평균한 값입니다.",
    "recent_volume_change": (
        "최근 20거래일 평균 거래량을 그 직전 20거래일 평균과 비교한 변화율입니다. "
        "계산하려면 최소 40거래일이 필요하며, 1개월 조회에서는 계산에만 선택기간 "
        "이전 시세를 추가로 사용합니다."
    ),
    "price_to_ma20": (
        "최근 종가가 20일 이동평균보다 얼마나 높거나 낮은지 나타냅니다. "
        "양수는 이동평균 위, 음수는 이동평균 아래를 뜻합니다."
    ),
    "bollinger_position": (
        "최근 종가의 볼린저밴드 내 상대 위치입니다. 하단은 0%, 중간선은 50%, "
        "상단은 100%이며 밴드 밖이면 0% 미만 또는 100% 초과가 될 수 있습니다."
    ),
    "usd_krw_change": (
        "선택한 주가 조회기간의 첫 원/달러 환율과 마지막 환율을 비교한 값입니다. "
        "계산식은 (마지막 환율 ÷ 첫 환율 - 1) × 100이며 단위는 %입니다."
    ),
    "market_index_change": (
        "선택한 주가 조회기간의 첫 시장지수 종가와 마지막 종가를 비교한 "
        "수익률입니다. 기업과 같은 시장 전체의 흐름을 보여 줍니다."
    ),
    "corr_return_market_index": (
        "기업의 일간 주가 수익률과 해당 기업이 상장된 시장지수의 일간 수익률 간 "
        "Pearson 상관계수입니다. 시장 영향을 제거한 값은 아닙니다."
    ),
    "treasury_3y_change_bp": (
        "선택한 주가 조회기간의 마지막 국고채 3년 금리에서 첫 금리를 뺀 값입니다. "
        "금리 변화율이 아니라 변화폭이며, 1bp는 0.01%p입니다."
    ),
    "credit_spread_latest": (
        "같은 날의 회사채 3년 AA- 금리에서 국고채 3년 금리를 뺀 값입니다. "
        "기업 신용위험에 대해 시장이 추가로 요구하는 금리 차이를 나타내며, "
        "1bp는 0.01%p입니다."
    ),
    "credit_spread_change_bp": (
        "선택한 주가 조회기간의 마지막 신용 스프레드에서 첫 신용 스프레드를 "
        "뺀 값입니다. 양수는 스프레드 확대, 음수는 축소를 뜻합니다."
    ),
    "corr_return_credit_spread": (
        "일간 주가 수익률과 신용 스프레드 일간 변화폭의 Pearson 상관계수입니다. "
        "기업의 실제 차입금리나 인과관계를 뜻하지 않습니다."
    ),
    "radar_usd_krw_excess_corr": (
        "기업 주가-환율 상관에서 해당 시장지수-환율 상관을 뺀 값입니다. "
        "절댓값 0.15 미만은 노출 약, 0.15 이상 0.30 미만은 중, 0.30 이상은 강으로 판정합니다."
    ),
    "radar_usd_krw_sign_persistence": (
        "환율 이동상관 중 전체 조회기간의 기업-환율 상관과 같은 부호를 유지한 비율입니다. "
        "-0.1~+0.1의 중립 이동상관도 전체 관측치에는 포함되며, 80% 이상을 안정 판정 기준으로 사용합니다."
    ),
    "radar_usd_krw_sign_switches": (
        "-0.1~+0.1의 중립 구간을 제외한 환율 이동상관이 양수에서 음수 또는 음수에서 "
        "양수로 바뀐 횟수입니다. 전환이 많을수록 조회기간 내 관계 방향이 자주 달라졌다는 뜻입니다."
    ),
    "radar_treasury_3y_excess_corr": (
        "기업 주가-금리 상관에서 해당 시장지수-금리 상관을 뺀 값입니다. "
        "시장과 구별되는 과거 동행성의 크기이며 인과관계나 실제 금리 노출액은 아닙니다."
    ),
    "radar_credit_spread_excess_corr": (
        "기업 주가-신용 스프레드 상관에서 해당 시장지수-신용 스프레드 상관을 뺀 값입니다. "
        "시장과 구별되는 과거 동행성의 크기이며 기업 고유 신용위험을 직접 측정하지 않습니다."
    ),
    "radar_usd_krw_judgement": (
        "시장 대비 상관 차이로 노출 강, 중 및 약을 판정합니다. 이동상관 창은 1개월 10일, "
        "3개월 20일, 6개월과 1년 및 3년은 60일이며, 부호 유지율 80% 이상과 전환율 5% 이하를 "
        "안정으로 판정합니다. 1개월과 3개월은 단기 참고값입니다."
    ),
    "radar_treasury_3y_judgement": (
        "시장 대비 상관 차이와 기간별 이동상관 안정성을 결합한 금리 레이더 판정입니다. "
        "1개월과 3개월 판정은 단기 참고값이며 장기적인 노출을 뜻하지 않습니다."
    ),
    "radar_credit_spread_judgement": (
        "시장 대비 상관 차이와 기간별 이동상관 안정성을 결합한 신용 스프레드 레이더 판정입니다. "
        "강하고 안정적이면 구조적 노출 후보, 강하지만 흔들리면 사건성 노출 후보로 해석합니다."
    ),
    "radar_usd_krw_sign_switch_rate": (
        "중립 구간(-0.1~+0.1)을 제외한 이동상관 부호가 바뀐 횟수를 "
        "전환 가능한 구간 수로 나눈 값입니다. 5% 이하를 안정 기준으로 사용합니다."
    ),
    "radar_treasury_3y_sign_switch_rate": (
        "금리 이동상관의 부호 전환 횟수 ÷ 전환 가능한 구간 수 × 100입니다."
    ),
    "radar_credit_spread_sign_switch_rate": (
        "신용 스프레드 이동상관의 부호 전환 횟수 ÷ 전환 가능한 구간 수 × 100입니다."
    ),
    "corr_usd_krw_treasury_3y_level": (
        "주의: 수준값 상관계수는 환율과 금리의 공통 추세만으로도 높게 나타날 수 "
        "있습니다. 직접적인 관계나 인과관계로 해석하지 말고 변화량 상관계수와 함께 "
        "확인하세요."
    ),
    "macro_filled_days": (
        "주식 거래일에 시장지수, 환율, 국고채 및 회사채 관측값이 없어 직전 값(첫 구간은 다음 값)으로 "
        "채운 날짜 수입니다. 보간된 구간은 상관계수와 이상치 계산에서 제외됩니다."
    ),
}
KPI_WARNING_KEYS = {"corr_usd_krw_treasury_3y_level"}
MACRO_RADAR_TABLE_KEYS = (
    "radar_usd_krw_excess_corr",
    "radar_usd_krw_sign_persistence",
    "radar_usd_krw_sign_switches",
    "radar_usd_krw_sign_switch_rate",
    "radar_treasury_3y_excess_corr",
    "radar_treasury_3y_sign_persistence",
    "radar_treasury_3y_sign_switches",
    "radar_treasury_3y_sign_switch_rate",
    "radar_credit_spread_excess_corr",
    "radar_credit_spread_sign_persistence",
    "radar_credit_spread_sign_switches",
    "radar_credit_spread_sign_switch_rate",
)
MACRO_RADAR_JUDGEMENT_KEYS = (
    ("환율", "radar_usd_krw_judgement"),
    ("금리", "radar_treasury_3y_judgement"),
    ("신용 스프레드", "radar_credit_spread_judgement"),
)
MACRO_TABLE_HIDDEN_KEYS = {
    "corr_return_usd_krw",
    "corr_return_treasury_3y",
    "corr_return_market_index",
    "corr_return_credit_spread",
    "corr_usd_krw_treasury_3y_level",
    "corr_usd_krw_treasury_3y_change",
    "macro_filled_days",
    "radar_usd_krw_market_corr",
    "radar_treasury_3y_market_corr",
    "radar_credit_spread_market_corr",
} | set(MACRO_RADAR_TABLE_KEYS) | {
    key for _, key in MACRO_RADAR_JUDGEMENT_KEYS
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
            "neutral_direction": "방향성 없음",
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
    display_digits = int(metric.get("display_digits", 2))
    return f"{value:,.{display_digits}f}".rstrip("0").rstrip(".") + unit


def build_kpi_card_metric(name: str, metric: dict) -> dict:
    """KPI 표시값과 마우스·키보드 도움말을 하나의 화면 항목으로 만든다."""
    return {
        "label": KPI_LABELS.get(name, name),
        "value": format_kpi_metric(metric),
        "reason": metric.get("reason"),
        "help_text": KPI_HELP_TEXT.get(name),
        "help_kind": "warning" if name in KPI_WARNING_KEYS else "info",
    }


def build_kpi_cards(payload: dict) -> list[dict]:
    cards = []
    for company in payload.get("companies", []):
        cards.append(
            {
                "company": company["company"],
                "analysis_type": company["analysis_type"],
                "financial_period": company["financial_period"],
                "financial": [
                    build_kpi_card_metric(name, metric)
                    for name, metric in company["financial_kpi"].items()
                    if metric.get("status") != "not_applicable"
                ],
                "market": [
                    build_kpi_card_metric(name, metric)
                    for name, metric in company["market_kpi"].items()
                ],
                "macro": [
                    build_kpi_card_metric(name, metric)
                    for name, metric in company.get("macro_kpi", {}).items()
                ],
            }
        )
    return cards


HEADLINE_KPI_KEYS = {
    "일반기업": ("revenue_growth", "operating_margin", "roe", "debt_ratio"),
    "금융업": ("net_interest_income", "net_fee_income", "roe", "roa"),
    "보험업": (
        "insurance_revenue_growth",
        "insurance_margin",
        "roe",
        "investment_profit",
    ),
}


def _missing_metric(status: str = "missing") -> dict:
    return {"value": None, "unit": "", "status": status, "reason": None}


def build_headline_kpi_cards(payload: dict) -> list[dict]:
    """업종별 대표 KPI 네 개를 기존 계산 결과에서 고른다."""
    cards = []
    for company in payload.get("companies", []):
        keys = HEADLINE_KPI_KEYS.get(
            company.get("analysis_type"), HEADLINE_KPI_KEYS["일반기업"]
        )
        financial = company.get("financial_kpi", {})
        cards.append(
            {
                "company": company.get("company", ""),
                "analysis_type": company.get("analysis_type", ""),
                "metrics": [
                    build_kpi_card_metric(key, financial.get(key, _missing_metric()))
                    for key in keys
                ],
            }
        )
    return cards


def build_kpi_matrix(
    payload: dict,
    section: str,
    keys: list[str] | tuple[str, ...] | None = None,
    hide_not_applicable: bool = False,
    exclude_keys: set[str] | frozenset[str] | None = None,
) -> dict:
    """지표를 행, 기업을 열로 배치할 비교용 화면 모델을 만든다."""
    companies = payload.get("companies", [])
    if keys is None:
        ordered_keys = []
        for company in companies:
            for key in company.get(section, {}):
                if key not in ordered_keys:
                    ordered_keys.append(key)
    else:
        ordered_keys = list(dict.fromkeys(keys))

    rows = []
    for key in ordered_keys:
        if exclude_keys and key in exclude_keys:
            continue
        values = []
        for company in companies:
            metric = company.get(section, {}).get(key, _missing_metric("not_applicable"))
            if hide_not_applicable and metric.get("status") == "not_applicable":
                values.append("")
            else:
                values.append(format_kpi_metric(metric))
        if hide_not_applicable and not any(values):
            continue
        rows.append(
            {
                "key": key,
                "label": KPI_LABELS.get(key, key),
                "values": values,
                "help_text": KPI_HELP_TEXT.get(key),
                "help_kind": "warning" if key in KPI_WARNING_KEYS else "info",
            }
        )
    return {
        "companies": [company.get("company", "") for company in companies],
        "rows": rows,
    }


def build_headline_kpi_matrix(payload: dict) -> dict:
    keys = []
    for company in payload.get("companies", []):
        for key in HEADLINE_KPI_KEYS.get(
            company.get("analysis_type"), HEADLINE_KPI_KEYS["일반기업"]
        ):
            if key not in keys:
                keys.append(key)
    return build_kpi_matrix(payload, "financial_kpi", keys)


def build_macro_radar_matrix(payload: dict) -> dict:
    """화면에 실제 존재하는 매크로 레이더 KPI만 고정 순서로 묶는다."""
    companies = payload.get("companies", [])
    keys = [
        key
        for key in MACRO_RADAR_TABLE_KEYS
        if any(key in company.get("macro_kpi", {}) for company in companies)
    ]
    return build_kpi_matrix(payload, "macro_kpi", keys)


def build_macro_radar_summaries(payload: dict) -> list[dict]:
    """레이더 최종 판정을 표 행 대신 제목 옆 요약으로 만든다."""
    companies = payload.get("companies", [])
    multiple_companies = len(companies) > 1
    summaries = []
    for company in companies:
        company_name = company.get("company", "")
        macro_kpis = company.get("macro_kpi", {})
        for factor, key in MACRO_RADAR_JUDGEMENT_KEYS:
            if key not in macro_kpis:
                continue
            value = format_kpi_metric(macro_kpis[key]).replace(" × ", " + ")
            summaries.append(
                {
                    "label": (
                        f"{company_name}, {factor}"
                        if multiple_companies
                        else factor
                    ),
                    "value": value,
                }
            )
    return summaries


def build_market_overview_cards(items: list[dict]) -> list[dict]:
    cards = []
    for item in items:
        available = item.get("status") == "available"
        value = item.get("latest_value")
        unit = item.get("unit", "")
        if not available or value is None:
            value_text = "자료 없음"
            change_text = "기간 변화 확인 불가"
        else:
            digits = 2 if unit in {"p", "%"} else 1
            value_text = f"{value:,.{digits}f}{unit}"
            change = item.get("change")
            if change is None:
                change_text = "기간 변화 확인 불가"
            else:
                change_unit = item.get("change_unit", "%")
                change_text = f"기간 변화 {change:+,.2f}{change_unit}"
        cards.append(
            {
                "key": item.get("key", ""),
                "label": item.get("label", ""),
                "date": item.get("latest_date") or "기준일 없음",
                "value": value_text,
                "change": change_text,
                "available": available,
            }
        )
    return cards


def company_market_name(company: dict) -> str:
    metric = company.get("macro_kpi", {}).get("market_index_name", {})
    if metric.get("status") == "available" and metric.get("value"):
        return str(metric["value"])
    return "시장 확인 불가"


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
        "observations": metric.get("observations"),
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


HEATMAP_FILENAME_PATTERN = re.compile(r"^market_correlation_heatmap_(.+)\.png$")

STOCK_CHART_GROUPS = (
    ("price", "주가"),
    ("volume", "거래량"),
    ("investor", "투자자"),
    ("macro", "외부요인"),
    ("correlation", "상관관계"),
)


def _stock_chart_group(filename: str) -> str:
    if filename == "stock_comparison.png":
        return "comparison"
    if filename.startswith("stock_price"):
        return "price"
    if filename.startswith("stock_volume"):
        return "volume"
    if filename.startswith("stock_investor"):
        return "investor"
    if filename.startswith(("macro_", "daily_change_")):
        return "macro"
    return "correlation"


def build_correlation_insight_sections(insight: str | None) -> dict | None:
    """긴 상관관계 인사이트 문장을 화면에서 읽기 좋은 구역으로 나눈다."""
    if not insight:
        return None
    main_text, notice_marker, notice = insight.partition(" 해석 유의: ")
    environment, radar_marker, radar_text = main_text.partition(" 매크로 레이더: ")
    if radar_marker:
        evidence_text, conclusion_marker, conclusion = radar_text.partition(
            ". 핵심 판정: "
        )
        evidence = [item.strip().rstrip(".") for item in evidence_text.split(";")]
        return {
            "environment": environment.strip(),
            "evidence": [item for item in evidence if item],
            "conclusion": conclusion.strip() if conclusion_marker else "",
            "notice": notice.strip() if notice_marker else "",
        }

    environment, separator, conclusion = main_text.partition(". ")
    return {
        "environment": environment.strip() + ("." if separator else ""),
        "evidence": [],
        "conclusion": conclusion.strip(),
        "notice": notice.strip() if notice_marker else "",
    }


def build_csv_preview(
    key: str, label: str, frame: pd.DataFrame, download_url: str | None
) -> dict:
    """CSV와 같은 열 순서로 상위 5행을 보여 주는 화면 모델을 만든다."""
    columns = list(frame.columns)
    rows = []
    for _, row in frame.head(5).iterrows():
        formatted = []
        for column in columns:
            value = row[column]
            if pd.isna(value):
                formatted.append("")
            elif isinstance(value, pd.Timestamp):
                formatted.append(value.strftime("%Y-%m-%d"))
            else:
                formatted.append(str(value))
        rows.append(formatted)
    return {
        "key": key,
        "label": label,
        "columns": columns,
        "rows": rows,
        "download_url": download_url,
    }


def build_stock_chart_items(
    chart_paths: list[Path], run_id: str, stock_summary, payload: dict
) -> list[dict]:
    """차트 URL에 기업별 히트맵 인사이트를 연결한다."""
    insight_by_company = build_company_correlation_insights(payload)
    insight_by_code = {
        str(row["종목코드"]): insight_by_company.get(row["기업명"])
        for _, row in stock_summary.iterrows()
    }
    company_by_code = {
        str(row["종목코드"]): row["기업명"] for _, row in stock_summary.iterrows()
    }
    only_company = next(iter(company_by_code.values()), None) if len(company_by_code) == 1 else None
    items = []
    for path in chart_paths:
        match = HEATMAP_FILENAME_PATTERN.fullmatch(path.name)
        insight = insight_by_code.get(match.group(1)) if match else None
        company = only_company
        for code, company_name in company_by_code.items():
            if path.stem.endswith(f"_{code}"):
                company = company_name
                break
        items.append(
            {
                "url": url_for(
                    "run_file", run_id=run_id, filename=f"stock_charts/{path.name}"
                ),
                "filename": path.name,
                "insight": insight,
                "insight_sections": build_correlation_insight_sections(insight),
                "company": company,
                "group": _stock_chart_group(path.name),
            }
        )
    return items


def group_stock_chart_items(items: list[dict]) -> list[dict]:
    groups = []
    for key, label in STOCK_CHART_GROUPS:
        charts = [item for item in items if item.get("group") == key]
        if charts:
            groups.append({"key": key, "label": label, "charts": charts})
    return groups


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
    stock_chart_items = build_stock_chart_items(
        sorted(stock_charts_dir.glob("*.png")),
        run_id,
        integrated.stock_summary,
        integrated.kpi_payload,
    )
    stock_comparison_charts = [
        item for item in stock_chart_items if item.get("group") == "comparison"
    ]
    stock_chart_groups = group_stock_chart_items(stock_chart_items)
    stock_price_chart_groups = [
        group
        for group in stock_chart_groups
        if group["key"] in {"price", "volume", "investor"}
    ]
    macro_chart_groups = [
        group
        for group in stock_chart_groups
        if group["key"] in {"macro", "correlation"}
    ]
    stock_columns = list(integrated.stock_summary.columns)
    stock_rows = [
        [format_stock_value(column, row[column]) for column in stock_columns]
        for _, row in integrated.stock_summary.iterrows()
    ]
    payload_companies = {
        company.get("company"): company
        for company in integrated.kpi_payload.get("companies", [])
    }
    headline_kpi_cards = build_headline_kpi_cards(integrated.kpi_payload)
    headline_kpis_by_company = {
        card["company"]: card["metrics"] for card in headline_kpi_cards
    }
    stock_cards = [
        {
            "company": row["기업명"],
            "code": row["종목코드"],
            "date": format_stock_value("기준일", row["기준일"]),
            "close": format_stock_value("최근종가", row["최근종가"]),
            "return": format_stock_value("기간수익률", row["기간수익률"]),
            "market_cap": format_stock_value("시가총액", row["시가총액"]),
            "market": company_market_name(
                payload_companies.get(row["기업명"], {})
            ),
            "headline_kpis": headline_kpis_by_company.get(row["기업명"], []),
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
    data_previews = [
        build_csv_preview("financial", "재무 요약", display, csv_url),
        build_csv_preview(
            "stock-summary", "주가 요약", integrated.stock_summary, stock_summary_csv_url
        ),
        build_csv_preview(
            "investor", "투자자 요약", integrated.investor_summary, investor_summary_csv_url
        ),
        build_csv_preview(
            "daily-prices", "일별 시세 요약", integrated.stock_prices, stock_prices_csv_url
        ),
        build_csv_preview(
            "market-macro",
            "주가, 시장지수 및 외부요인 요약",
            integrated.market_macro,
            market_macro_csv_url,
        ),
        build_csv_preview(
            "data-quality", "데이터 처리 요약", integrated.quality_log, data_quality_csv_url
        ),
    ]
    if ENABLE_GPT_INSIGHTS:
        gpt_insight_cards, gpt_comparison_cards = build_gpt_cards(
            integrated.gpt_insights,
            integrated.gpt_comparisons,
            integrated.kpi_payload,
        )
    else:
        gpt_insight_cards, gpt_comparison_cards = [], []
    companies = display["기업명"].drop_duplicates().tolist()
    analysis_mode = "single" if len(companies) == 1 else "comparison"
    kpi_cards = build_kpi_cards(integrated.kpi_payload)
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
        "result_dashboard.html",
        companies=companies,
        analysis_mode=analysis_mode,
        columns=visible_columns,
        rows=rows,
        chart_urls=chart_urls,
        stock_chart_items=stock_chart_items,
        stock_comparison_charts=stock_comparison_charts,
        stock_chart_groups=stock_chart_groups,
        stock_price_chart_groups=stock_price_chart_groups,
        macro_chart_groups=macro_chart_groups,
        stock_columns=stock_columns,
        stock_rows=stock_rows,
        stock_cards=stock_cards,
        stock_period_label=STOCK_PERIOD_LABELS[stock_period],
        kpi_cards=kpi_cards,
        headline_kpi_cards=headline_kpi_cards,
        headline_kpi_matrix=build_headline_kpi_matrix(integrated.kpi_payload),
        financial_kpi_matrix=build_kpi_matrix(
            integrated.kpi_payload, "financial_kpi", hide_not_applicable=True
        ),
        market_kpi_matrix=build_kpi_matrix(
            integrated.kpi_payload, "market_kpi"
        ),
        macro_kpi_matrix=build_kpi_matrix(
            integrated.kpi_payload,
            "macro_kpi",
            exclude_keys=MACRO_TABLE_HIDDEN_KEYS,
        ),
        macro_radar_matrix=build_macro_radar_matrix(integrated.kpi_payload),
        macro_radar_summaries=build_macro_radar_summaries(
            integrated.kpi_payload
        ),
        market_overview=build_market_overview_cards(integrated.market_overview),
        gpt_insights=gpt_insight_cards,
        gpt_comparisons=gpt_comparison_cards,
        gpt_enabled=ENABLE_GPT_INSIGHTS,
        warnings=integrated.warnings,
        csv_url=csv_url,
        stock_prices_csv_url=stock_prices_csv_url,
        stock_summary_csv_url=stock_summary_csv_url,
        investor_summary_csv_url=investor_summary_csv_url,
        market_macro_csv_url=market_macro_csv_url,
        data_quality_csv_url=data_quality_csv_url,
        data_previews=data_previews,
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
