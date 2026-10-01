"""DART 원천 계정을 선택하고 재무지표를 계산한다."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd


LOGGER = logging.getLogger(__name__)

# 계정 ID를 우선 사용하고, 기업별 사용자 계정에 대비해 계정명은 보조로 사용한다.
# 이자보상배율은 비교 화면과 동일하게 현금흐름표의 실제 이자지급액을 사용한다.
# 이는 손익계산서의 발생주의 이자비용과 다른 현금 기준 지표다.
ACCOUNT_RULES = {
    "revenue": {
        "label": "매출",
        "statements": ("IS", "CIS"),
        "ids": (
            "ifrs-full_Revenue",
            "ifrs-full_RevenueFromContractsWithCustomers",
        ),
        "names": ("매출액", "수익(매출액)", "영업수익"),
    },
    "operating_profit": {
        "label": "영업이익",
        "statements": ("IS", "CIS"),
        "ids": (
            "dart_OperatingIncomeLoss",
            "ifrs-full_ProfitLossFromOperatingActivities",
        ),
        "names": ("영업이익", "영업이익(손실)", "영업손익"),
    },
    "net_income": {
        "label": "당기순이익",
        "statements": ("IS", "CIS"),
        "ids": ("ifrs-full_ProfitLoss",),
        "names": (
            "당기순이익",
            "당기순이익(손실)",
            "당기순손익",
            "연결당기순이익",
            "연결당기순이익(손실)",
            "연결당기순손익",
        ),
    },
    "assets": {
        "label": "자산",
        "statements": ("BS",),
        "ids": ("ifrs-full_Assets",),
        "names": ("자산총계",),
    },
    "liabilities": {
        "label": "부채",
        "statements": ("BS",),
        "ids": ("ifrs-full_Liabilities",),
        "names": ("부채총계",),
    },
    "equity": {
        "label": "자본",
        "statements": ("BS",),
        "ids": ("ifrs-full_Equity",),
        "names": ("자본총계",),
    },
    "interest_paid": {
        "label": "이자지급액",
        "statements": ("CF",),
        "ids": ("ifrs-full_InterestPaidClassifiedAsOperatingActivities",),
        "names": ("이자의 지급", "이자지급"),
    },
    "trade_receivables": {
        "label": "매출채권",
        "statements": ("BS",),
        "ids": (
            "ifrs-full_CurrentTradeReceivables",
            "dart_ShortTermTradeReceivable",
            "dart_ShortTermTradeReceivables",
            "ifrs-full_TradeAndOtherCurrentReceivables",
        ),
        "names": ("매출채권", "매출채권 및 기타채권", "매출채권및기타채권"),
    },
    "net_interest_income": {
        "label": "순이자손익",
        "statements": ("IS", "CIS"),
        "ids": ("ifrs-full_InterestRevenueExpense",),
        "names": ("순이자손익", "이자손익"),
    },
    "net_fee_income": {
        "label": "순수수료손익",
        "statements": ("IS", "CIS"),
        "ids": ("ifrs-full_FeeAndCommissionIncomeExpense",),
        "names": ("순수수료손익", "수수료손익"),
    },
    # 일부 증권사는 순액 대신 수익과 비용을 각각 공시한다. 아래 네 계정은
    # 순이자손익·순수수료손익이 없을 때 순액을 계산하기 위한 보조 원천이다.
    "interest_income": {
        "label": "이자수익",
        "statements": ("IS", "CIS"),
        "ids": ("ifrs-full_RevenueFromInterest",),
        "names": ("이자수익",),
    },
    "interest_expense": {
        "label": "이자비용",
        "statements": ("IS", "CIS"),
        "ids": ("ifrs-full_InterestExpense",),
        "names": ("이자비용",),
    },
    "fee_income": {
        "label": "수수료수익",
        "statements": ("IS", "CIS"),
        "ids": ("ifrs-full_FeeAndCommissionIncome",),
        "names": ("수수료수익",),
    },
    "fee_expense": {
        "label": "수수료비용",
        "statements": ("IS", "CIS"),
        "ids": ("ifrs-full_FeeAndCommissionExpense",),
        "names": ("수수료비용",),
    },
    "insurance_revenue": {
        "label": "보험서비스수익",
        "statements": ("IS", "CIS"),
        "ids": (
            "dart_OperatingIncomeInsurance",
            "ifrs-full_InsuranceRevenue",
        ),
        "names": (
            "보험서비스수익",
            "보험영업수익",
            "보험수익",
            "일반보험서비스수익",
        ),
    },
    "insurance_service_result": {
        "label": "보험서비스손익",
        "statements": ("IS", "CIS"),
        "ids": ("ifrs-full_InsuranceServiceResult",),
        "names": ("보험서비스손익", "보험서비스결과", "보험손익"),
    },
    "investment_result": {
        "label": "투자손익",
        "statements": ("IS", "CIS"),
        "ids": ("dart_InvestmentIncomeExpenses",),
        "names": ("투자손익",),
    },
}

RAW_COLUMNS = [
    "기업명",
    "연도",
    "재무제표구분",
    "원천항목",
    "계정ID",
    "계정명",
    "재무제표종류",
    "금액",
    "통화",
    "접수번호",
]

FINAL_COLUMNS = [
    "기업명",
    "분석유형",
    "연도",
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
    "영업이익률",
    "보험서비스마진",
    "부채비율",
    "이자보상배율",
    "ROE",
    "매출성장",
    "보험서비스수익성장",
    "총자산성장",
    "영업이익성장",
    "당기순이익성장",
    "매출채권회전일수",
]

GROWTH_COLUMNS = [
    "매출성장",
    "보험서비스수익성장",
    "총자산성장",
    "영업이익성장",
    "당기순이익성장",
]

GENERAL_ONLY_COLUMNS = ["매출", "영업이익률", "부채비율", "이자보상배율", "매출성장", "매출채권회전일수"]
FINANCIAL_ONLY_COLUMNS = ["순이자손익", "순수수료손익"]
INSURANCE_ONLY_COLUMNS = ["보험서비스수익", "보험서비스손익", "보험서비스마진", "보험서비스수익성장", "투자손익"]

REQUIRED_ACCOUNT_KEYS = {
    "일반기업": {
        "revenue",
        "operating_profit",
        "net_income",
        "assets",
        "liabilities",
        "equity",
        "interest_paid",
        "trade_receivables",
    },
    "금융업": {
        "operating_profit",
        "net_income",
        "assets",
        "liabilities",
        "equity",
        "net_interest_income",
        "net_fee_income",
    },
    "보험업": {
        "operating_profit",
        "net_income",
        "assets",
        "liabilities",
        "equity",
        "insurance_revenue",
        "insurance_service_result",
        "investment_result",
    },
}


def _normalize_name(value: str) -> str:
    return "".join(value.split()).replace("（", "(").replace("）", ")")


def _to_number(value) -> float:
    """DART의 쉼표, 빈 문자열, '-'를 숫자 또는 NaN으로 변환한다."""
    if value is None:
        return np.nan
    text = str(value).strip().replace(",", "")
    if text in {"", "-"}:
        return np.nan
    try:
        return float(text)
    except ValueError:
        return np.nan


def _select_account(rows: list[dict], rule: dict) -> dict | None:
    """재무제표 종류 → 계정 ID → 계정명 우선순위로 한 계정을 선택한다."""
    for statement in rule["statements"]:
        candidates = [row for row in rows if row.get("sj_div") == statement]
        for account_id in rule["ids"]:
            match = next(
                (row for row in candidates if row.get("account_id") == account_id),
                None,
            )
            if match is not None:
                return match

        normalized_names = {_normalize_name(name) for name in rule["names"]}
        match = next(
            (
                row
                for row in candidates
                if _normalize_name(row.get("account_nm", "")) in normalized_names
            ),
            None,
        )
        if match is not None:
            return match
    return None


def _detect_analysis_type_from_rows(rows: list[dict]) -> str:
    """한 연도의 원본 계정 ID로 분석유형을 빠르게 판별한다."""
    account_ids = {row.get("account_id", "") for row in rows}
    # 금융지주는 보험 계정도 포함할 수 있으므로 직접 공시된 순이자·순수수료
    # 계정을 가장 강한 금융업 신호로 사용한다.
    if account_ids.intersection(
        {"ifrs-full_InterestRevenueExpense", "ifrs-full_FeeAndCommissionIncomeExpense"}
    ):
        return "금융업"
    if account_ids.intersection(
        {
            "dart_OperatingIncomeInsurance",
            "ifrs-full_InsuranceRevenue",
            "ifrs-full_InsuranceServiceResult",
        }
    ):
        return "보험업"
    gross_financial_ids = {
        "ifrs-full_RevenueFromInterest",
        "ifrs-full_InterestExpense",
        "ifrs-full_FeeAndCommissionIncome",
        "ifrs-full_FeeAndCommissionExpense",
    }
    if gross_financial_ids.issubset(account_ids):
        return "금융업"
    return "일반기업"


def extract_source_accounts(
    company_name: str,
    year: int,
    fs_div: str,
    statement_rows: list[dict],
) -> list[dict]:
    """한 기업·연도의 분석용 원천 계정과 출처 정보를 추출한다."""
    records = []
    analysis_type = _detect_analysis_type_from_rows(statement_rows)
    selected_accounts = {
        key: _select_account(statement_rows, rule)
        for key, rule in ACCOUNT_RULES.items()
    }
    derived_fallbacks = {
        "net_interest_income": ("interest_income", "interest_expense"),
        "net_fee_income": ("fee_income", "fee_expense"),
    }
    for key, rule in ACCOUNT_RULES.items():
        account = selected_accounts[key]
        if account is None:
            fallback_keys = derived_fallbacks.get(key, ())
            has_fallback = bool(fallback_keys) and all(
                selected_accounts[fallback_key] is not None
                for fallback_key in fallback_keys
            )
            required = key in REQUIRED_ACCOUNT_KEYS[analysis_type] and not has_fallback
            log = LOGGER.warning if required else LOGGER.debug
            log("%s %s년: '%s' 계정을 찾지 못했습니다.", company_name, year, rule["label"])
            records.append(
                {
                    "기업명": company_name,
                    "연도": year,
                    "재무제표구분": fs_div,
                    "원천항목": key,
                    "계정ID": "",
                    "계정명": "",
                    "재무제표종류": "",
                    "금액": np.nan,
                    "통화": "",
                    "접수번호": "",
                }
            )
            continue

        records.append(
            {
                "기업명": company_name,
                "연도": year,
                "재무제표구분": fs_div,
                "원천항목": key,
                "계정ID": account.get("account_id", ""),
                "계정명": account.get("account_nm", ""),
                "재무제표종류": account.get("sj_div", ""),
                "금액": _to_number(account.get("thstrm_amount")),
                "통화": account.get("currency", ""),
                "접수번호": account.get("rcept_no", ""),
            }
        )
    return records


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """결측치와 0 분모를 NaN으로 유지하는 나눗셈."""
    valid = numerator.notna() & denominator.notna() & denominator.ne(0)
    result = pd.Series(np.nan, index=numerator.index, dtype="float64")
    result.loc[valid] = numerator.loc[valid] / denominator.loc[valid]
    return result


def _company_analysis_types(values: pd.DataFrame) -> pd.Series:
    """기업 전체 연도의 계정 구성을 바탕으로 일반·금융·보험 유형을 판별한다."""
    # 일반기업도 이자수익·비용 일부를 공시할 수 있으므로, 분리 공시에서
    # 계산된 금융업 신호는 순이자와 순수수료가 모두 있을 때만 인정한다.
    financial_row = values[["net_interest_income", "net_fee_income"]].notna().all(axis=1)
    insurance_row = values[["insurance_revenue", "insurance_service_result"]].notna().any(axis=1)
    direct_financial_company = values["_direct_financial"].groupby(values["기업명"]).transform("max")
    financial_company = financial_row.groupby(values["기업명"]).transform("max")
    insurance_company = insurance_row.groupby(values["기업명"]).transform("max")
    return pd.Series(
        np.select(
            [direct_financial_company, insurance_company, financial_company],
            ["금융업", "보험업", "금융업"],
            default="일반기업",
        ),
        index=values.index,
        dtype="string",
    )


def calculate_metrics(raw_accounts: pd.DataFrame) -> pd.DataFrame:
    """원천 계정을 연도별로 정리하고 업종별 재무지표를 계산한다."""
    if raw_accounts.empty:
        return pd.DataFrame(columns=FINAL_COLUMNS)

    # pivot_table(dropna=False)는 여러 기업을 함께 처리할 때 실제로 존재하지 않는
    # 기업×연도 조합까지 생성한다. 실제 수집된 조합을 기준으로 다시 결합해
    # 데이터가 없는 가짜 연도 행이 생기지 않도록 한다.
    company_years = raw_accounts[["기업명", "연도"]].drop_duplicates()
    values = raw_accounts.pivot_table(
        index=["기업명", "연도"],
        columns="원천항목",
        values="금액",
        aggfunc="first",
        dropna=True,
    ).reset_index()
    values = company_years.merge(values, on=["기업명", "연도"], how="left")
    for key in ACCOUNT_RULES:
        if key not in values:
            values[key] = np.nan

    values["_direct_financial"] = values[
        ["net_interest_income", "net_fee_income"]
    ].notna().any(axis=1)
    values["net_interest_income"] = values["net_interest_income"].combine_first(
        values["interest_income"] - values["interest_expense"]
    )
    values["net_fee_income"] = values["net_fee_income"].combine_first(
        values["fee_income"] - values["fee_expense"]
    )

    values = values.sort_values(["기업명", "연도"]).reset_index(drop=True)
    grouped = values.groupby("기업명", sort=False)
    previous_year = grouped["연도"].shift(1)
    consecutive = values["연도"].sub(previous_year).eq(1)

    previous_revenue = grouped["revenue"].shift(1).where(consecutive)
    previous_equity = grouped["equity"].shift(1).where(consecutive)
    previous_insurance_revenue = grouped["insurance_revenue"].shift(1).where(consecutive)
    previous_assets = grouped["assets"].shift(1).where(consecutive)
    previous_operating_profit = grouped["operating_profit"].shift(1).where(consecutive)
    previous_net_income = grouped["net_income"].shift(1).where(consecutive)

    average_equity = (values["equity"] + previous_equity) / 2
    analysis_type = _company_analysis_types(values)
    general_mask = analysis_type.eq("일반기업")
    financial_mask = analysis_type.eq("금융업")
    insurance_mask = analysis_type.eq("보험업")

    operating_margin = _safe_ratio(values["operating_profit"], values["revenue"]) * 100
    debt_ratio = _safe_ratio(values["liabilities"], values["equity"]) * 100
    interest_coverage = _safe_ratio(values["operating_profit"], values["interest_paid"])
    revenue_growth = _safe_ratio(values["revenue"] - previous_revenue, previous_revenue) * 100
    receivables_days = _safe_ratio(values["trade_receivables"], values["revenue"]) * 365
    insurance_margin = _safe_ratio(values["insurance_service_result"], values["insurance_revenue"]) * 100
    insurance_revenue_growth = (
        _safe_ratio(
            values["insurance_revenue"] - previous_insurance_revenue,
            previous_insurance_revenue,
        )
        * 100
    )

    result = pd.DataFrame(
        {
            "기업명": values["기업명"],
            "분석유형": analysis_type,
            "연도": values["연도"].astype("int64"),
            "매출": values["revenue"].where(general_mask),
            "보험서비스수익": values["insurance_revenue"].where(insurance_mask),
            "순이자손익": values["net_interest_income"].where(financial_mask),
            "순수수료손익": values["net_fee_income"].where(financial_mask),
            "영업이익": values["operating_profit"],
            "당기순이익": values["net_income"],
            "보험서비스손익": values["insurance_service_result"].where(insurance_mask),
            "투자손익": values["investment_result"].where(insurance_mask),
            "총자산": values["assets"],
            "부채총계": values["liabilities"],
            "자본총계": values["equity"],
            "영업이익률": operating_margin.where(general_mask),
            "보험서비스마진": insurance_margin.where(insurance_mask),
            "부채비율": debt_ratio.where(general_mask),
            # 현금흐름표상 실제 이자지급액 기준이다. 발생주의 이자비용 기준과 다를 수 있다.
            "이자보상배율": interest_coverage.where(general_mask),
            # 평균자본을 사용한다. 기말자본만 쓰는 방식보다 기간 중 자본 변화를 반영한다.
            "ROE": _safe_ratio(values["net_income"], average_equity) * 100,
            "매출성장": revenue_growth.where(general_mask),
            "보험서비스수익성장": insurance_revenue_growth.where(insurance_mask),
            "총자산성장": _safe_ratio(values["assets"] - previous_assets, previous_assets) * 100,
            "영업이익성장": _safe_ratio(
                values["operating_profit"] - previous_operating_profit,
                previous_operating_profit,
            )
            * 100,
            "당기순이익성장": _safe_ratio(
                values["net_income"] - previous_net_income,
                previous_net_income,
            )
            * 100,
            # 사이트 표시 방식에 맞춰 기말 매출채권 잔액을 사용한다.
            # 별도 매출채권이 없으면 매출채권 및 기타채권 통합 계정을 사용한다.
            "매출채권회전일수": receivables_days.where(general_mask),
        }
    )

    amount_columns = [
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
    ]
    result[amount_columns] = result[amount_columns].round().astype("Int64")
    ratio_columns = [
        column
        for column in FINAL_COLUMNS
        if column not in {"기업명", "분석유형", "연도", *amount_columns}
    ]
    result[ratio_columns] = result[ratio_columns].round(2)
    return result[FINAL_COLUMNS]


def format_result_for_csv(result: pd.DataFrame) -> pd.DataFrame:
    """숫자 계산 결과를 유지하면서 CSV에는 미적용·결측 사유를 표시한다."""
    display = result.copy()
    metric_columns = [column for column in FINAL_COLUMNS if column not in {"기업명", "분석유형", "연도"}]
    display[metric_columns] = display[metric_columns].astype(object)

    unavailable_by_type = {
        "일반기업": FINANCIAL_ONLY_COLUMNS + INSURANCE_ONLY_COLUMNS,
        "금융업": GENERAL_ONLY_COLUMNS + INSURANCE_ONLY_COLUMNS,
        "보험업": GENERAL_ONLY_COLUMNS + FINANCIAL_ONLY_COLUMNS,
    }
    for analysis_type, columns in unavailable_by_type.items():
        mask = display["분석유형"].eq(analysis_type)
        display.loc[mask, columns] = f"해당 없음({analysis_type})"

    first_rows = display.groupby("기업명", sort=False).head(1).index
    for column in GROWTH_COLUMNS:
        missing = display.index.isin(first_rows) & pd.isna(display[column])
        display.loc[missing, column] = "비교연도 없음"

    missing_roe = pd.isna(display["ROE"])
    display.loc[missing_roe, "ROE"] = "직전연도 자본 또는 당기순이익 없음"
    display[metric_columns] = display[metric_columns].fillna("원천 데이터 없음")
    return display[FINAL_COLUMNS]


def select_output_periods(
    metrics: pd.DataFrame,
    number_of_years: int,
    start_year: int | None = None,
    end_year: int | None = None,
) -> pd.DataFrame:
    """사용자가 요청한 기간 또는 기업별 최근 N개년만 선택한다."""
    selected_parts = []
    for _, company_data in metrics.groupby("기업명", sort=False):
        company_data = company_data.sort_values("연도")
        if start_year is not None or end_year is not None:
            lower = start_year if start_year is not None else int(company_data["연도"].min())
            upper = end_year if end_year is not None else int(company_data["연도"].max())
            company_data = company_data[
                company_data["연도"].between(lower, upper)
            ]
        else:
            company_data = company_data.tail(number_of_years)

        # 화면에 표시되는 첫 연도의 성장률은 비교 기준이 없으므로 NaN 처리한다.
        if not company_data.empty:
            company_data = company_data.copy()
            company_data.loc[company_data.index[0], GROWTH_COLUMNS] = np.nan
        selected_parts.append(company_data)

    if not selected_parts:
        return pd.DataFrame(columns=FINAL_COLUMNS)
    return pd.concat(selected_parts, ignore_index=True)[FINAL_COLUMNS]
