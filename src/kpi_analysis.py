"""재무·시장 데이터프레임을 GPT 입력용 KPI 계약으로 변환한다."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

if __package__:
    from .data_quality import daily_change, pair_valid
    from .macro_analysis import (
        FX_CHANGE_COLUMN,
        FX_COLUMN,
        PRICE_CHANGE_COLUMN,
        RATE_CHANGE_PP_COLUMN,
        FX_FILLED_COLUMN,
        FX_OUTLIER_COLUMN,
        PRICE_OUTLIER_COLUMN,
        RATE_COLUMN,
        RATE_FILLED_COLUMN,
        RATE_OUTLIER_COLUMN,
    )
    from .stock_analysis import add_bollinger_bands, add_moving_averages
else:
    from data_quality import daily_change, pair_valid
    from macro_analysis import (
        FX_CHANGE_COLUMN,
        FX_COLUMN,
        PRICE_CHANGE_COLUMN,
        RATE_CHANGE_PP_COLUMN,
        FX_FILLED_COLUMN,
        FX_OUTLIER_COLUMN,
        PRICE_OUTLIER_COLUMN,
        RATE_COLUMN,
        RATE_FILLED_COLUMN,
        RATE_OUTLIER_COLUMN,
    )
    from stock_analysis import add_bollinger_bands, add_moving_averages


MIN_CORRELATION_OBSERVATIONS = 20
MACRO_KPI_UNITS = {
    "usd_krw_latest": "원",
    "usd_krw_change": "%",
    "treasury_3y_latest": "%",
    "treasury_3y_change_bp": "bp",
    "corr_return_usd_krw": "",
    "corr_return_treasury_3y": "",
    "macro_filled_days": "일",
    "price_outlier_days": "일",
    "usd_krw_outlier_days": "일",
    "treasury_3y_outlier_days": "일",
}
OUTLIER_KPI_COLUMNS = {
    "price_outlier_days": PRICE_OUTLIER_COLUMN,
    "usd_krw_outlier_days": FX_OUTLIER_COLUMN,
    "treasury_3y_outlier_days": RATE_OUTLIER_COLUMN,
}


def _number(value: Any, digits: int = 2) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def _metric(
    value: Any,
    unit: str,
    *,
    digits: int = 2,
    status: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    number = _number(value, digits=digits)
    resolved_status = status or ("available" if number is not None else "missing")
    resolved_reason = reason
    if resolved_status != "available" and not resolved_reason:
        resolved_reason = "출처 데이터 없음"
    return {
        "value": number,
        "unit": unit,
        "status": resolved_status,
        "reason": resolved_reason if resolved_status != "available" else None,
    }


def _text_metric(value: Any, *, reason: str | None = None) -> dict[str, Any]:
    """날짜처럼 숫자가 아닌 원천값도 KPI 상태 계약에 맞춰 반환한다."""
    available = value is not None and not pd.isna(value) and str(value).strip() != ""
    return {
        "value": str(value) if available else None,
        "unit": "",
        "status": "available" if available else "missing",
        "reason": None if available else (reason or "출처 데이터 없음"),
    }


def _safe_ratio(numerator: Any, denominator: Any) -> float | None:
    if pd.isna(numerator) or pd.isna(denominator) or float(denominator) == 0:
        return None
    return float(numerator) / float(denominator) * 100


def _financial_kpis(company_rows: pd.DataFrame) -> tuple[int, str, dict[str, dict]]:
    ordered = company_rows.sort_values("연도")
    latest = ordered.iloc[-1]
    previous = ordered.iloc[-2] if len(ordered) >= 2 else None
    analysis_type = str(latest["분석유형"])

    net_margin = _safe_ratio(latest["당기순이익"], latest["매출"])
    previous_assets = previous["총자산"] if previous is not None else pd.NA
    average_assets = (
        (float(latest["총자산"]) + float(previous_assets)) / 2
        if pd.notna(latest["총자산"]) and pd.notna(previous_assets)
        else pd.NA
    )
    stored_roa = latest.get("ROA", pd.NA)
    roa = stored_roa if pd.notna(stored_roa) else _safe_ratio(
        latest["당기순이익"], average_assets
    )
    roa_status = (
        "no_comparison_period"
        if pd.isna(roa) and previous is None
        else None
    )

    general_company = analysis_type == "일반기업"
    not_applicable = {
        "status": "not_applicable",
        "reason": f"{analysis_type}에는 일반기업 매출 기반 지표를 적용하지 않음",
    }
    general_options = {} if general_company else not_applicable

    financial_company = analysis_type == "금융업"
    insurance_company = analysis_type == "보험업"

    def industry_options(applies: bool, label: str) -> dict[str, str]:
        if applies:
            return {}
        return {
            "status": "not_applicable",
            "reason": f"{analysis_type}에는 {label} 지표를 적용하지 않음",
        }

    return int(latest["연도"]), analysis_type, {
        "revenue_growth": _metric(latest["매출성장"], "%", **general_options),
        "operating_profit_growth": _metric(latest["영업이익성장"], "%"),
        "net_income_growth": _metric(latest["당기순이익성장"], "%"),
        "operating_margin": _metric(latest["영업이익률"], "%", **general_options),
        "net_margin": _metric(net_margin, "%", **general_options),
        "roe": _metric(latest["ROE"], "%"),
        "roa": _metric(
            roa,
            "%",
            status=roa_status,
            reason=(
                "평균자산 계산에 필요한 비교연도가 없음"
                if roa_status == "no_comparison_period"
                else None
            ),
        ),
        "debt_ratio": _metric(latest["부채비율"], "%", **general_options),
        "interest_coverage_ratio": _metric(
            latest["이자보상배율"], "배", **general_options
        ),
        "accounts_receivable_days": _metric(
            latest["매출채권회전일수"], "일", **general_options
        ),
        "net_interest_income": _metric(
            latest.get("순이자손익", pd.NA),
            "원",
            digits=0,
            **industry_options(financial_company, "금융업"),
        ),
        "net_fee_income": _metric(
            latest.get("순수수료손익", pd.NA),
            "원",
            digits=0,
            **industry_options(financial_company, "금융업"),
        ),
        "insurance_service_revenue": _metric(
            latest.get("보험서비스수익", pd.NA),
            "원",
            digits=0,
            **industry_options(insurance_company, "보험업"),
        ),
        "insurance_service_profit": _metric(
            latest.get("보험서비스손익", pd.NA),
            "원",
            digits=0,
            **industry_options(insurance_company, "보험업"),
        ),
        "insurance_margin": _metric(
            latest.get("보험서비스마진", pd.NA),
            "%",
            **industry_options(insurance_company, "보험업"),
        ),
        "insurance_revenue_growth": _metric(
            latest.get("보험서비스수익성장", pd.NA),
            "%",
            **industry_options(insurance_company, "보험업"),
        ),
        "investment_profit": _metric(
            latest.get("투자손익", pd.NA),
            "원",
            digits=0,
            **industry_options(insurance_company, "보험업"),
        ),
    }


def _market_kpis(company_prices: pd.DataFrame) -> dict[str, dict]:
    if company_prices.empty:
        missing = {
            "status": "missing",
            "reason": "주식시세 원천 데이터 없음",
        }
        return {
            name: _metric(None, unit, **missing)
            for name, unit in {
                "start_date": "",
                "latest_date": "",
                "latest_close": "원",
                "average_close": "원",
                "period_high": "원",
                "period_low": "원",
                "period_return": "%",
                "daily_volatility": "%",
                "average_volume": "주",
                "average_trading_value": "원",
                "recent_volume_change": "%",
                "price_to_ma20": "%",
                "bollinger_position": "%",
            }.items()
        }

    prices = company_prices.sort_values("기준일").copy()
    first_close = prices["종가"].iloc[0]
    last_close = prices["종가"].iloc[-1]
    period_return = _safe_ratio(last_close - first_close, first_close)
    daily_returns = prices["종가"].pct_change().dropna()
    volatility = daily_returns.std(ddof=1) * 100 if len(daily_returns) >= 2 else None

    volume_change = None
    volume_status = None
    volume_reason = None
    if len(prices) >= 40:
        recent_average = prices["거래량"].tail(20).mean()
        previous_average = prices["거래량"].iloc[-40:-20].mean()
        volume_change = _safe_ratio(recent_average - previous_average, previous_average)
    else:
        volume_status = "no_comparison_period"
        volume_reason = "최근 20일과 직전 20일을 비교할 거래일이 부족함"

    technical = add_bollinger_bands(add_moving_averages(prices, windows=(20,)))
    last = technical.iloc[-1]
    price_to_ma20 = _safe_ratio(last["종가"] - last["이동평균20일"], last["이동평균20일"])
    band_width = last["BB상한"] - last["BB하한"]
    bollinger_position = _safe_ratio(last["종가"] - last["BB하한"], band_width)

    period_high = prices["고가"].max() if "고가" in prices else None
    period_low = prices["저가"].min() if "저가" in prices else None

    return {
        "start_date": _text_metric(
            prices["기준일"].iloc[0].date().isoformat(),
            reason="주식시세 시작일 없음",
        ),
        "latest_date": _text_metric(
            prices["기준일"].iloc[-1].date().isoformat(),
            reason="주식시세 기준일 없음",
        ),
        "latest_close": _metric(last_close, "원", digits=0),
        "average_close": _metric(prices["종가"].mean(), "원", digits=0),
        "period_high": _metric(period_high, "원", digits=0),
        "period_low": _metric(period_low, "원", digits=0),
        "period_return": _metric(period_return, "%"),
        "daily_volatility": _metric(volatility, "%"),
        "average_volume": _metric(prices["거래량"].mean(), "주", digits=0),
        "average_trading_value": _metric(
            prices["거래대금"].mean(), "원", digits=0
        ),
        "recent_volume_change": _metric(
            volume_change,
            "%",
            status=volume_status,
            reason=volume_reason,
        ),
        "price_to_ma20": _metric(price_to_ma20, "%"),
        "bollinger_position": _metric(bollinger_position, "%"),
    }


def _correlation(
    returns: pd.Series, changes: pd.Series, valid: pd.Series
) -> tuple[float | None, str | None, str | None]:
    """보간하지 않은 연속 관측일의 일간 수익률·매크로 변화 상관계수."""
    pairs = pd.DataFrame({"returns": returns, "changes": changes})[valid].dropna()
    if len(pairs) < MIN_CORRELATION_OBSERVATIONS:
        return (
            None,
            "no_comparison_period",
            f"상관계수 계산에 필요한 관측일({MIN_CORRELATION_OBSERVATIONS}일)이 부족함",
        )
    if pairs["returns"].std() == 0 or pairs["changes"].std() == 0:
        return None, "missing", "변동이 없어 상관계수를 계산할 수 없음"
    return float(pairs["returns"].corr(pairs["changes"])), None, None


def _change_column(data: pd.DataFrame, column: str, source: str, kind: str) -> pd.Series:
    """저장된 하루 변화 열을 쓰고, 없으면(이전 형식 데이터) 원천 값으로 계산한다."""
    if column in data:
        return pd.to_numeric(data[column], errors="coerce")
    return daily_change(data[source], kind)


def _macro_kpis(company_macro: pd.DataFrame | None) -> dict[str, dict]:
    """주식 거래일 기준으로 맞춘 환율·금리의 기간 변화와 주가 연관성."""
    missing_reason = "환율/금리 원천 데이터 없음"
    if company_macro is None or company_macro.empty:
        return {
            name: _metric(None, unit, status="missing", reason=missing_reason)
            for name, unit in MACRO_KPI_UNITS.items()
        }

    data = company_macro.sort_values("기준일").reset_index(drop=True)
    fx = pd.to_numeric(data[FX_COLUMN], errors="coerce")
    rate = pd.to_numeric(data[RATE_COLUMN], errors="coerce")
    fx_filled = data[FX_FILLED_COLUMN].fillna(False).astype(bool)
    rate_filled = data[RATE_FILLED_COLUMN].fillna(False).astype(bool)
    fx_valid = fx.dropna()
    rate_valid = rate.dropna()

    fx_change = (
        _safe_ratio(fx_valid.iloc[-1] - fx_valid.iloc[0], fx_valid.iloc[0])
        if len(fx_valid) >= 2
        else None
    )
    rate_change_bp = (
        (rate_valid.iloc[-1] - rate_valid.iloc[0]) * 100 if len(rate_valid) >= 2 else None
    )

    # 병합 단계에서 만든 하루 변화 열(등락률·변화율·변화폭)을 그대로 쓴다.
    returns = _change_column(data, PRICE_CHANGE_COLUMN, "종가", "pct")
    # ffill한 날의 변화량은 0으로 보여 상관을 왜곡하므로 당일·전일 모두 실제 관측일만 쓴다.
    fx_pair_valid = pair_valid(fx_filled)
    rate_pair_valid = pair_valid(rate_filled)
    fx_corr, fx_corr_status, fx_corr_reason = _correlation(
        returns, _change_column(data, FX_CHANGE_COLUMN, FX_COLUMN, "pct"), fx_pair_valid
    )
    rate_corr, rate_corr_status, rate_corr_reason = _correlation(
        returns,
        _change_column(data, RATE_CHANGE_PP_COLUMN, RATE_COLUMN, "diff"),
        rate_pair_valid,
    )

    def series_metric(series: pd.Series, value, unit: str, **options) -> dict[str, Any]:
        if series.empty:
            return _metric(None, unit, status="missing", reason=missing_reason)
        return _metric(value, unit, **options)

    return {
        "usd_krw_latest": series_metric(
            fx_valid, fx_valid.iloc[-1] if not fx_valid.empty else None, "원"
        ),
        "usd_krw_change": series_metric(fx_valid, fx_change, "%"),
        "treasury_3y_latest": series_metric(
            rate_valid,
            rate_valid.iloc[-1] if not rate_valid.empty else None,
            "%",
            digits=3,
        ),
        "treasury_3y_change_bp": series_metric(rate_valid, rate_change_bp, "bp", digits=1),
        "corr_return_usd_krw": series_metric(
            fx_valid, fx_corr, "", status=fx_corr_status, reason=fx_corr_reason
        ),
        "corr_return_treasury_3y": series_metric(
            rate_valid, rate_corr, "", status=rate_corr_status, reason=rate_corr_reason
        ),
        "macro_filled_days": _metric(
            int((fx_filled | rate_filled).sum()), "일", digits=0
        ),
        **{
            name: _outlier_days(data, column, source)
            for (name, column), source in zip(
                OUTLIER_KPI_COLUMNS.items(),
                (data["종가"].dropna(), fx_valid, rate_valid),
            )
        },
    }


def _outlier_days(data: pd.DataFrame, column: str, source: pd.Series) -> dict[str, Any]:
    """하루 변화 IQR 밖으로 표시된 거래일 수. 원천 값이 없으면 missing."""
    if column not in data or source.empty:
        return _metric(None, "일", status="missing", reason="이상치 판정 데이터 없음")
    return _metric(int(data[column].fillna(False).astype(bool).sum()), "일", digits=0)


def build_kpi_payload(
    financial: pd.DataFrame,
    stock_prices: pd.DataFrame,
    stock_period: str,
    market_macro: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """기업별 최신 재무연도와 선택 주가기간의 KPI JSON을 만든다."""
    companies = []
    for company_name, rows in financial.groupby("기업명", sort=False):
        period, analysis_type, financial_kpi = _financial_kpis(rows)
        ordered_rows = rows.sort_values("연도").reset_index(drop=True)
        financial_history = []
        for index in range(len(ordered_rows)):
            history_period, _, history_kpis = _financial_kpis(
                ordered_rows.iloc[: index + 1]
            )
            financial_history.append(
                {"period": str(history_period), "financial_kpi": history_kpis}
            )
        company_prices = (
            stock_prices[stock_prices["기업명"] == company_name]
            if not stock_prices.empty
            else stock_prices
        )
        companies.append(
            {
                "company": company_name,
                "analysis_type": analysis_type,
                "financial_period": str(period),
                "financial_periods": [
                    str(int(value)) for value in ordered_rows["연도"].tolist()
                ],
                "financial_history": financial_history,
                "stock_period": stock_period,
                "financial_kpi": financial_kpi,
                "market_kpi": _market_kpis(company_prices),
                "macro_kpi": _macro_kpis(
                    market_macro[market_macro["기업명"] == company_name]
                    if market_macro is not None and not market_macro.empty
                    else None
                ),
            }
        )
    return {
        "schema_version": "1.1",
        "generated_on": date.today().isoformat(),
        "companies": companies,
    }
