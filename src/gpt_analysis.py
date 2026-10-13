"""계산된 KPI만 OpenAI API에 전달해 구조화된 분석을 생성한다."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

if __package__:
    from .analysis_prompt import ANALYSIS_SYSTEM_PROMPT
    from .dart_api import load_env_file
else:
    from analysis_prompt import ANALYSIS_SYSTEM_PROMPT
    from dart_api import load_env_file


DEFAULT_MODEL = "gpt-4o-mini"
MAX_VALIDATION_ATTEMPTS = 3
KPI_GROUPS = ("financial_kpi", "market_kpi", "macro_kpi")
FIXED_METHOD_NUMBERS = (3.0, 4.0, 5.0, 9.0, 10.0, 20.0, 0.3)


class GPTAnalysisError(RuntimeError):
    """GPT 분석을 생성하지 못했지만 기본 분석은 계속할 수 있는 오류."""


class GPTNumericValidationError(GPTAnalysisError):
    """GPT 문장에 입력 KPI와 일치하지 않는 숫자가 포함된 오류."""


class InsightSection(BaseModel):
    summary: str
    evidence_keys: list[str]


class CompanyInsight(BaseModel):
    company: str
    one_line_summary: InsightSection
    data_basis: str
    growth: InsightSection
    profitability: InsightSection
    stability: InsightSection
    efficiency: InsightSection
    market: InsightSection
    financial_scenario: InsightSection
    relationships_and_mismatches: list[InsightSection]
    positive_signals: list[InsightSection] = Field(max_length=4)
    caution_signals: list[InsightSection] = Field(max_length=4)
    additional_checks: list[InsightSection]
    overall_summary: InsightSection


class MetricReference(BaseModel):
    company: str
    metric_key: str


class ComparisonInsight(BaseModel):
    summary: str
    evidence: list[MetricReference]


class KPIInsightResponse(BaseModel):
    analyses: list[CompanyInsight]
    comparisons: list[ComparisonInsight]


COMPARISON_GROUPS = (
    (
        "성장성",
        (
            ("revenue_growth", "매출 성장률", "higher"),
            ("operating_profit_growth", "영업이익 성장률", "higher"),
            ("net_income_growth", "당기순이익 성장률", "higher"),
            ("insurance_revenue_growth", "보험서비스수익 성장률", "higher"),
            ("total_assets_growth", "총자산 성장률", "higher"),
        ),
    ),
    (
        "수익성",
        (
            ("operating_margin", "영업이익률", "higher"),
            ("net_margin", "순이익률", "higher"),
            ("roe", "ROE", "higher"),
            ("roa", "ROA", "higher"),
            ("insurance_margin", "보험서비스마진", "higher"),
        ),
    ),
    (
        "재무 안정성",
        (
            ("debt_ratio", "부채비율", "lower"),
            ("interest_coverage_ratio", "이자보상배율", "higher"),
        ),
    ),
    (
        "효율성",
        (("accounts_receivable_days", "매출채권 회전일수", "lower"),),
    ),
    (
        "시장 흐름",
        (
            ("period_return", "조회기간 수익률", "higher"),
            ("daily_volatility", "일간 변동성", "lower"),
        ),
    ),
)


SECTIONS = (
    "one_line_summary",
    "growth",
    "profitability",
    "stability",
    "efficiency",
    "market",
    "financial_scenario",
    "overall_summary",
)
SECTION_LISTS = (
    "relationships_and_mismatches",
    "positive_signals",
    "caution_signals",
    "additional_checks",
)
NUMBER_PATTERN = re.compile(r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?")
FORBIDDEN_RECOMMENDATION_PATTERN = re.compile(
    r"매수(?:해야|하라|를\s*권|를\s*추천)|매도(?:해야|하라|를\s*권|를\s*추천)|"
    r"인수(?:해야|하라|를\s*권|를\s*추천)|합병(?:해야|하라|을\s*권|을\s*추천)|"
    r"사야\s*한다|팔아야\s*한다|목표\s*주가|우량주|부실주|종목\s*추천"
)
CHANGE_LANGUAGE_PATTERN = re.compile(
    r"증가|감소|개선|악화|향상|저하|상승|하락|유지|늘어|줄어"
)
FINANCIAL_CHANGE_CLAIM_PATTERN = re.compile(
    r"(?:영업이익률|운영\s*마진|순이익률|ROE|ROA|부채\s*비율|이자보상배율|"
    r"매출채권\s*회전\s*일수).{0,25}(?:증가|감소|개선|악화|향상|저하|상승|하락|유지|늘어|줄어)|"
    r"(?:증가|감소|개선|악화|향상|저하|상승|하락|유지|늘어|줄어).{0,25}"
    r"(?:영업이익률|운영\s*마진|순이익률|ROE|ROA|부채\s*비율|이자보상배율|"
    r"매출채권\s*회전\s*일수)"
)
RELATIVE_MARKET_PATTERN = re.compile(r"시장\s*대비")
RELATIVE_VOLATILITY_PATTERN = re.compile(
    r"상대적으로|변동성(?:이|은)?\s*(?:높|낮)|(?:높|낮)(?:은|은\s*편인|다).*변동성"
)
STABILITY_CONCERN_PATTERN = re.compile(
    r"재무\s*안정성.{0,50}(?:우려|취약|리스크|위험|유의|주의)|"
    r"(?:우려|취약|리스크|위험|유의|주의).{0,50}재무\s*안정성"
)
DEBT_RISK_PATTERN = re.compile(
    r"부채\s*비율.{0,40}(?:우려|리스크|위험)|"
    r"(?:우려|리스크|위험).{0,40}부채\s*비율"
)
MISMATCH_LANGUAGE_PATTERN = re.compile(r"상반|불일치|서로\s*다른\s*방향")
NOT_ALL_IMPROVED_PATTERN = re.compile(
    r"모든\s*(?:지표|항목)(?:가|은|는)?.{0,20}(?:개선|증가)(?:된|한)?\s*것은\s*아(?:니|닙)|"
    r"전부.{0,20}(?:개선|증가)(?:된|한)?\s*것은\s*아(?:니|닙)"
)
UNSUPPORTED_QUALITY_PATTERN = re.compile(
    r"강력한\s*성과|안정적인\s*(?:수준|수익성)|안정적으로|양호|긍정적|"
    r"급격히|급증|급락|크게|고무적|저조|다소|뛰어난|극대화"
)
FUTURE_GROWTH_PATTERN = re.compile(r"(?:새로운\s*)?(?:성장|회복)\s*가능성")
IMPROVEMENT_START_PATTERN = re.compile(
    r"(\d{4})년부터.{0,30}(?:개선|회복|반등)"
)
NEGATIVE_DECREASE_RATE_PATTERN = re.compile(
    r"감소율.{0,15}-\d|-\d[\d,.]*%.{0,15}(?:감소율|감소|하락)"
)
RAW_METRIC_KEY_PATTERN = re.compile(
    r"(?<![a-z0-9_])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![a-z0-9_])"
)
VAGUE_METRIC_PATTERN = re.compile(
    r"(?:여러|몇몇)\s*(?:재무\s*)?지표|제반\s*(?:지표|추세)"
)
WRONG_FINANCIAL_TERM_PATTERN = re.compile(r"운영\s*이익(?:률)?")
REVERSED_YEAR_COMPARISON_PATTERN = re.compile(
    r"(\d{4})년에?\s*비해\s*(\d{4})년에?"
)
INVENTED_COST_CAUSE_PATTERN = re.compile(
    r"원가\s*압박|원가.{0,15}(?:때문|인해|영향)"
)
UNSUPPORTED_CONCERN_PATTERN = re.compile(r"우려(?:가|를)?\s*(?:가중|높|커)")
TREND_RISK_PATTERN = re.compile(
    r"(?:성장률|재무\s*지표).{0,30}변동\s*(?:위험|리스크)|"
    r"변동\s*(?:위험|리스크).{0,30}(?:성장률|재무\s*지표)"
)
UNSUPPORTED_PEAK_PATTERN = re.compile(r"피크|정점")
CONSECUTIVE_DECLINE_PATTERN = re.compile(
    r"(?:두|2)\s*(?:해|년).{0,10}연속.{0,10}(?:감소|하락)|"
    r"연속.{0,10}(?:두|2)\s*(?:해|년).{0,10}(?:감소|하락)"
)
COLLECTIVE_GROWTH_TREND_PATTERN = re.compile(
    r"매출(?:과|,).{0,20}(?:이익|영업이익|당기순이익).{0,20}성장률.{0,30}"
    r"(?:변동|개선|악화|향상|저하)"
)
MIXED_PERIOD_SIMULTANEITY_PATTERN = re.compile(r"와중에|동시에|함께\s*나타")
OPERATIONAL_EFFICIENCY_IMPROVEMENT_PATTERN = re.compile(
    r"운영\s*효율성.{0,25}(?:개선|향상)|(?:개선|향상).{0,25}운영\s*효율성"
)
VOLUME_TREND_PATTERN = re.compile(
    r"거래량.{0,20}(?:증가세|감소세|상승세|하락세)"
)
COVERAGE_PROFITABILITY_PATTERN = re.compile(
    r"이자보상배율.{0,45}수익성|수익성.{0,45}이자보상배율"
)
FINANCIAL_GROWTH_VOLATILITY_PATTERN = re.compile(
    r"(?:성장률|성장성).{0,60}변동성|변동성.{0,60}(?:성장률|성장성)|"
    r"(?:매출|영업이익|당기순이익|순이익).{0,100}이전\s*연도.{0,40}변동성"
)
GROWTH_SUSTAINABILITY_ATTENTION_PATTERN = re.compile(
    r"성장\s*지속성.{0,25}(?:주목|유의|주의|확인\s*필요)|"
    r"(?:주목|유의|주의|확인\s*필요).{0,25}성장\s*지속성"
)
UNSUPPORTED_RECOVERY_TREND_PATTERN = re.compile(
    r"회복세.{0,20}(?:이어|지속)|(?:이어|지속).{0,20}회복세"
)
ENGLISH_FINANCIAL_DIRECTION_PATTERN = re.compile(
    r"(?<![A-Za-z])(?:Positive|Negative)(?![A-Za-z])",
    re.IGNORECASE,
)
CURRENT_PRICE_PATTERN = re.compile(r"현재\s*주가")
TREND_HEDGING_PATTERN = re.compile(
    r"(?:개선|악화|변동)(?:된)?\s*(?:것으로\s*)?보(?:입|였|인다)"
)
PRICE_RETURN_CONFLATION_PATTERN = re.compile(
    r"(?:최근\s*(?:주가|종가)|종가).{0,35}\d[\d,]*\s*원(?:으로|이고)?.{0,35}"
    r"\d[\d,.]*%.{0,20}(?:기간\s*)?수익률.{0,15}기록"
)
MIXED_LONG_TERM_SIGNAL_PATTERN = re.compile(
    r"최근\s*3년.{0,50}(?:혼재|엇갈린)|(?:혼재|엇갈린).{0,50}최근\s*3년"
)
PLAN_CLAIM_PATTERN = re.compile(r"계획(?:했던|한| 대비|보다)")
GROWTH_SLOWDOWN_PATTERN = re.compile(
    r"성장\s*속도.{0,20}(?:둔화|저하)|(?:둔화|저하).{0,20}성장\s*속도"
)
FINANCIAL_CONDITION_CHANGE_PATTERN = re.compile(
    r"재무\s*체질.{0,20}(?:개선|악화)|(?:개선|악화).{0,20}재무\s*체질"
)
SCENARIO_FUTURE_RESULT_PATTERN = re.compile(
    r"(?:결과|반응).{0,20}(?:나올|나타날)\s*가능성"
)
UNSUPPORTED_PROFIT_STATUS_PATTERN = re.compile(
    r"(?:운영|영업)?\s*적자.{0,20}(?:개선|악화|전환|지속)|"
    r"(?:개선|악화|전환|지속).{0,20}(?:운영|영업)?\s*적자|"
    r"(?:순손실|흑자).{0,20}(?:개선|악화|전환|지속)"
)
GROWTH_RATE_AS_CHANGING_PATTERN = re.compile(
    r"(?:매출|영업이익|당기순이익)\s*(?:의\s*)?성장률(?:은|이|도)?.{0,45}"
    r"(?:%|퍼센트)(?:로|만큼)?\s*"
    r"(?:증가|감소|성장|상승|하락|향상|개선|저하|악화)"
)
GROWTH_VALUE_AS_QUALITY_PATTERN = re.compile(
    r"(?:매출|영업이익|당기순이익)(?:은|는|이|가|도)?.{0,45}"
    r"\d[\d,.]*%(?:로|만큼|\s*및|\s*,|\s*){0,2}.{0,12}(?:개선|악화)"
)
GROWTH_TREND_CLAIM_PATTERN = re.compile(
    r"(?:성장률|성장성).{0,100}(?:최근\s*)?3년.{0,20}추세.{0,20}"
    r"(?:변동|개선|악화|향상|저하)|"
    r"(?:최근\s*)?3년.{0,20}추세.{0,20}(?:변동|개선|악화|향상|저하)"
    r".{0,100}(?:성장률|성장성)"
)
GROWTH_TREND_VOLATILITY_PATTERN = re.compile(
    r"(?:성장률|성장성).{0,100}(?:최근\s*)?3년.{0,20}추세.{0,20}변동성|"
    r"(?:최근\s*)?3년.{0,20}추세.{0,20}변동성.{0,100}(?:성장률|성장성)|"
    r"(?:최근\s*)?3년(?:간|\s*동안)?.{0,35}(?:성장률|성장성).{0,20}변동성"
)
YEAR_UNTIL_CONTINUING_TREND_PATTERN = re.compile(
    r"(?:부채\s*비율|영업이익률|순이익률|ROE|ROA|이자보상배율|"
    r"매출채권\s*회전\s*일수).{0,35}\d{4}년까지.{0,20}"
    r"지속적으로.{0,10}(?:개선|악화|증가|감소)"
)
YEAR_BY_YEAR_PATTERN = re.compile(r"연도별.{0,20}(?:성장률|매출|영업이익|당기순이익)")
UNSUPPORTED_LEVEL_COMPARISON_PATTERN = re.compile(
    r"(?:영업이익률|순이익률|ROE|ROA|부채\s*비율|이자보상배율|"
    r"매출채권\s*회전\s*일수)(?:이|가|은|는)?\s*.{0,15}(?:높|낮)"
)
CURRENT_LEVEL_AS_TREND_PATTERN = re.compile(
    r"(?:영업이익률|순이익률|ROE|ROA|부채\s*비율|이자보상배율|"
    r"매출채권\s*회전\s*일수)(?:이|가|은|는)?.{0,35}"
    r"\d[\d,.]*(?:%|배|일)(?:로)?\s*"
    r"(?:증가|감소|개선|악화|향상|저하|상승|하락|늘어|줄어)"
)
RECEIVABLE_MISINTERPRETATION_PATTERN = re.compile(
    r"(?:매출채권\s*회전\s*일수|accounts_receivable_days).{0,40}"
    r"(?:지급\s*기간|현금흐름.{0,15}효율성|"
    r"효율성.{0,15}(?:저하|악화)|"
    r"(?:비효율성|회수\s*효율성).{0,20}(?:우려|위험|유의|주의))|"
    r"(?:지급\s*기간|현금흐름.{0,15}효율성|"
    r"(?:저하|악화).{0,15}효율성|"
    r"(?:비효율성|회수\s*효율성).{0,20}(?:우려|위험|유의|주의)).{0,40}"
    r"(?:매출채권\s*회전\s*일수|accounts_receivable_days)"
)
PROFITABILITY_IMPROVEMENT_PATTERN = re.compile(
    r"수익성.{0,25}(?:개선|향상)|(?:개선|향상).{0,25}수익성"
)
GROWTH_IMPROVEMENT_PATTERN = re.compile(
    r"성장성.{0,20}(?:향상|개선)|(?:향상|개선).{0,20}성장성"
)
STABILITY_ASSURANCE_PATTERN = re.compile(
    r"재무(?:적\s*)?안정성.{0,30}(?:가지|확보|높|안정적|뒷받침|개선)|"
    r"(?:가지|확보|높|안정적|뒷받침|개선).{0,30}재무(?:적\s*)?안정성"
)
GENERIC_FINANCIAL_CHANGE_PATTERN = re.compile(
    r"일부\s*재무\s*지표.{0,25}(?:개선|악화|향상|저하)"
)
DIRECTIONAL_VALUE_PATTERN = re.compile(
    r"([-+]?\d[\d,]*(?:\.\d+)?)\s*(%p|%|bp).{0,12}(상승|증가|하락|감소)"
)
BOILERPLATE_SIGNAL_PATTERN = re.compile(r"제시된.{0,20}KPI")
NO_EVIDENCE_ALLOWED_PATTERN = re.compile(
    r"판단할\s*수\s*없|자료\s*부족|데이터.{0,10}부족|"
    r"제시된\s*(?:사용\s*가능한\s*)?KPI.{0,30}확인"
)
SCENARIO_VULNERABILITY_PATTERN = re.compile(r"취약")
SCENARIO_BUFFER_PATTERN = re.compile(r"완충")
SCENARIO_TREND_KEYS = (
    "financial_trend.debt_ratio",
    "financial_trend.interest_coverage_ratio",
    "financial_trend.operating_margin",
)
TREND_LABELS = {
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
}
METRIC_TERM_REQUIREMENTS = (
    (re.compile(r"매출(?!채권)"), {"revenue_growth"}),
    (re.compile(r"영업이익(?!률)"), {"operating_profit_growth"}),
    (re.compile(r"(?:당기)?순이익(?!률)"), {"net_income_growth"}),
    (re.compile(r"영업이익률"), {"operating_margin"}),
    (re.compile(r"순이익률"), {"net_margin"}),
    (re.compile(r"이자보상배율"), {"interest_coverage_ratio"}),
    (re.compile(r"매출채권\s*회전\s*일수"), {"accounts_receivable_days"}),
    (re.compile(r"시장\s*수익률"), {"market_index_change"}),
)
LEVEL_CHANGE_PATTERNS = (
    ("operating_margin", re.compile(r"영업이익률|(?<!순)이익률|운영\s*마진")),
    ("net_margin", re.compile(r"순이익률")),
    ("roe", re.compile(r"ROE")),
    ("roa", re.compile(r"ROA")),
    ("debt_ratio", re.compile(r"부채\s*비율")),
    ("interest_coverage_ratio", re.compile(r"이자보상배율")),
    ("accounts_receivable_days", re.compile(r"매출채권\s*회전\s*일수")),
)


def get_openai_api_key(project_root: Path) -> str:
    load_env_file(project_root / ".env")
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("GPT_KEY")
    if not api_key:
        raise GPTAnalysisError(
            "프로젝트 루트의 .env에 OPENAI_API_KEY를 설정해 주세요."
        )
    return api_key.strip()


def _payload_lookup(payload: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    lookup: dict[str, dict[str, dict[str, Any]]] = {}
    for company in payload.get("companies", []):
        metrics = {}
        for group_name in KPI_GROUPS:
            metrics.update(company.get(group_name, {}))
        for key, metric in company.get("financial_trend", {}).items():
            metrics[f"financial_trend.{key}"] = metric
        for history in company.get("financial_history", []):
            period = history.get("period")
            for key, metric in history.get("financial_kpi", {}).items():
                metrics[f"financial_history.{period}.{key}"] = metric
        lookup[company["company"]] = metrics
    return lookup


def _allowed_numbers(company: dict[str, Any]) -> list[float]:
    allowed = list(FIXED_METHOD_NUMBERS)
    if company.get("financial_periods"):
        allowed.append(float(len(company["financial_periods"])))
        allowed.extend(
            float(period)
            for period in company["financial_periods"]
            if str(period).isdigit()
        )
    period = company.get("financial_period")
    if period and str(period).isdigit():
        allowed.append(float(period))
    allowed.extend(float(item) for item in re.findall(r"\d+", str(company.get("stock_period", ""))))
    for group_name in KPI_GROUPS:
        for metric in company.get(group_name, {}).values():
            if metric.get("status") != "available":
                continue
            value = metric.get("value")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                allowed.append(float(value))
            elif isinstance(value, str):
                allowed.extend(float(item) for item in re.findall(r"\d+", value))
    for metric in company.get("financial_trend", {}).values():
        if metric.get("status") != "available":
            continue
        allowed.extend(
            float(item)
            for item in metric.get("periods", [])
            if str(item).isdigit()
        )
        allowed.extend(
            float(item)
            for item in metric.get("values", [])
            if isinstance(item, (int, float)) and not isinstance(item, bool)
        )
    for history in company.get("financial_history", []):
        allowed.extend(float(item) for item in re.findall(r"\d+", str(history.get("period", ""))))
        for metric in history.get("financial_kpi", {}).values():
            if metric.get("status") != "available":
                continue
            value = metric.get("value")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                allowed.append(float(value))
    return allowed


def _validate_numbers(text: str, allowed: list[float], context: str) -> None:
    for token in NUMBER_PATTERN.findall(text):
        number = float(token.replace(",", ""))
        if not any(
            abs(abs(number) - abs(value))
            <= max(0.011, abs(value) * 0.000001)
            for value in allowed
        ):
            raise GPTNumericValidationError(
                f"{context}에 입력 KPI와 일치하지 않는 숫자가 포함되어 있습니다."
            )


def _validate_language(text: str) -> None:
    if FORBIDDEN_RECOMMENDATION_PATTERN.search(text):
        raise GPTAnalysisError("GPT 분석에 허용되지 않는 투자 추천 표현이 포함되어 있습니다.")


def _canonical_metric_key(metric_key: str) -> str:
    """모델이 JSON 경로를 붙여 반환해도 내부 KPI 키로 정규화한다."""
    for prefix in (f"{group_name}." for group_name in KPI_GROUPS):
        if metric_key.startswith(prefix):
            return metric_key[len(prefix) :]
    return metric_key


def _section_numbers(
    evidence_keys: list[str],
    metrics: dict[str, dict[str, Any]],
    company: dict[str, Any],
) -> list[float]:
    """문장 숫자를 해당 근거 KPI와 기간 표현에만 대조한다."""
    allowed = list(FIXED_METHOD_NUMBERS)
    if company.get("financial_periods"):
        allowed.append(float(len(company["financial_periods"])))
        allowed.extend(
            float(period)
            for period in company["financial_periods"]
            if str(period).isdigit()
        )
    allowed.extend(
        float(item)
        for item in re.findall(r"\d+", str(company.get("financial_period", "")))
    )
    allowed.extend(
        float(item)
        for item in re.findall(r"\d+", str(company.get("stock_period", "")))
    )
    for key in evidence_keys:
        allowed.extend(float(item) for item in re.findall(r"\d+", key))
        metric = metrics.get(key)
        if not metric or metric.get("status") != "available":
            continue
        value = metric.get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            allowed.append(float(value))
        elif isinstance(value, str):
            allowed.extend(float(item) for item in re.findall(r"\d+", value))
        allowed.extend(
            float(item)
            for item in metric.get("periods", [])
            if str(item).isdigit()
        )
        allowed.extend(
            float(item)
            for item in metric.get("values", [])
            if isinstance(item, (int, float)) and not isinstance(item, bool)
        )
    return allowed


def _base_metric_key(metric_key: str) -> str:
    if metric_key.startswith("financial_trend."):
        return metric_key.removeprefix("financial_trend.")
    if metric_key.startswith("financial_history."):
        return metric_key.rsplit(".", 1)[-1]
    return metric_key


def _has_missing_period_metric_evidence(
    text: str,
    evidence_keys: list[str],
    metrics: dict[str, dict[str, Any]],
) -> bool:
    """특정 연도의 성장 수치를 말하면서 그 연도 KPI 근거를 빠뜨렸는지 확인한다."""
    metric_terms = (
        ("revenue_growth", re.compile(r"매출(?!채권)")),
        ("operating_profit_growth", re.compile(r"영업이익(?!률)")),
        ("net_income_growth", re.compile(r"(?:당기)?순이익(?!률)")),
    )
    for sentence in re.split(r"(?<!\d)[.!?](?!\d)|[;,]|(?:으나|지만)", text):
        years = re.findall(r"(\d{4})년", sentence)
        if not years or not re.search(r"\d[\d,.]*%", sentence):
            continue
        for base_key, term_pattern in metric_terms:
            if not term_pattern.search(sentence):
                continue
            for year in years:
                history_key = f"financial_history.{year}.{base_key}"
                if history_key in metrics:
                    if history_key not in evidence_keys:
                        return True
                elif base_key not in evidence_keys:
                    return True
    return False


def _level_change_claims(text: str) -> set[str]:
    """문장에서 변화가 언급된 수준 KPI를 지표별로 찾는다."""
    claims = set()
    change = CHANGE_LANGUAGE_PATTERN.pattern
    for base_key, term_pattern in LEVEL_CHANGE_PATTERNS:
        term = term_pattern.pattern
        if re.search(
            rf"(?:{term}).{{0,25}}(?:{change})|(?:{change}).{{0,25}}(?:{term})",
            text,
        ):
            claims.add(base_key)
    return claims


def _has_change_evidence(
    evidence_keys: list[str], claimed_level_keys: set[str]
) -> bool:
    """변화를 주장한 각 수준 KPI에 추세 또는 복수 연도 근거가 있는지 확인한다."""
    for base_key in claimed_level_keys:
        if f"financial_trend.{base_key}" in evidence_keys:
            continue
        history_periods = {
            key.split(".")[1]
            for key in evidence_keys
            if key.startswith("financial_history.")
            and _base_metric_key(key) == base_key
        }
        if len(history_periods) < 2:
            return False
    return True


def _direction_particle(text: str) -> str:
    """방향 판정 뒤에 붙는 조사 '로/으로'를 반환한다."""
    last_code = ord(text[-1])
    final_consonant = (
        (last_code - 0xAC00) % 28 if 0xAC00 <= last_code <= 0xD7A3 else 0
    )
    return "으로" if final_consonant not in (0, 8) else "로"


def _subject_particle(text: str) -> str:
    """명사 뒤에 붙는 주격 조사 '이/가'를 반환한다."""
    last_code = ord(text[-1])
    final_consonant = (
        (last_code - 0xAC00) % 28 if 0xAC00 <= last_code <= 0xD7A3 else 0
    )
    return "이" if final_consonant else "가"


def _evidence_directions(
    evidence_keys: list[str], metrics: dict[str, dict[str, Any]]
) -> set[int]:
    directions: set[int] = set()
    for key in evidence_keys:
        metric = metrics.get(key, {})
        if metric.get("status") != "available":
            continue
        value = metric.get("value")
        if value == "개선":
            directions.add(1)
        elif value == "악화":
            directions.add(-1)
        elif _base_metric_key(key).endswith("_growth") and isinstance(value, (int, float)):
            if value > 0:
                directions.add(1)
            elif value < 0:
                directions.add(-1)
    return directions


def _has_direction_mismatch(
    text: str,
    evidence_keys: list[str],
    metrics: dict[str, dict[str, Any]],
) -> bool:
    """문장 속 증감 방향이 근거 KPI의 부호와 반대인지 확인한다."""
    for number_text, unit, direction in DIRECTIONAL_VALUE_PATTERN.findall(text):
        number = abs(float(number_text.replace(",", "")))
        candidates = []
        for key in evidence_keys:
            metric = metrics.get(key, {})
            value = metric.get("value")
            if (
                metric.get("status") == "available"
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
                and metric.get("unit") == unit
                and abs(abs(float(value)) - number)
                <= max(0.011, abs(float(value)) * 0.000001)
            ):
                candidates.append(float(value))
        if not candidates:
            continue
        expected_sign = 1 if direction in {"상승", "증가"} else -1
        if not any(
            (value > 0 and expected_sign == 1)
            or (value < 0 and expected_sign == -1)
            or value == 0
            for value in candidates
        ):
            return True
    return False


def _has_trend_wording_mismatch(
    text: str,
    evidence_keys: list[str],
    metrics: dict[str, dict[str, Any]],
) -> bool:
    """수준 KPI의 증감 표현과 방향을 반영한 3년 추세 판정이 맞는지 확인한다."""
    change_words = re.compile(r"증가|상승|늘어|감소|하락|줄어|개선|향상|악화|저하")
    inverse_metrics = {"debt_ratio", "accounts_receivable_days"}
    positive_words = {"증가", "상승", "늘어", "개선", "향상"}

    for base_key, term_pattern in LEVEL_CHANGE_PATTERNS:
        trend_key = f"financial_trend.{base_key}"
        trend_value = metrics.get(trend_key, {}).get("value")
        if trend_key not in evidence_keys or trend_value not in {"개선", "악화"}:
            continue
        expected = 1 if trend_value == "개선" else -1
        for term_match in term_pattern.finditer(text):
            candidates = []
            for word_match in change_words.finditer(text):
                distance = min(
                    abs(word_match.start() - term_match.end()),
                    abs(term_match.start() - word_match.end()),
                )
                if distance <= 20:
                    candidates.append((distance, word_match.group()))
            if not candidates:
                continue
            word = min(candidates)[1]
            if word in {"개선", "향상"}:
                claimed = 1
            elif word in {"악화", "저하"}:
                claimed = -1
            else:
                claimed = 1 if word in positive_words else -1
                if base_key in inverse_metrics:
                    claimed *= -1
            if claimed != expected:
                return True
    return False


def _has_profitability_change_evidence(
    evidence_keys: list[str], metrics: dict[str, dict[str, Any]]
) -> bool:
    """수익성 개선 표현에 수익성 KPI의 추세 또는 복수 연도 근거가 있는지 확인한다."""
    profitability_keys = {"operating_margin", "net_margin", "roe", "roa"}
    for base_key in profitability_keys:
        trend_key = f"financial_trend.{base_key}"
        if (
            trend_key in evidence_keys
            and metrics.get(trend_key, {}).get("value") == "개선"
        ):
            return True
        history_periods = {
            key.split(".")[1]
            for key in evidence_keys
            if key.startswith("financial_history.")
            and _base_metric_key(key) == base_key
        }
        if len(history_periods) >= 2:
            return True
    return False


def _supports_growth_slowdown(
    evidence_keys: list[str], metrics: dict[str, dict[str, Any]]
) -> bool:
    """같은 성장률의 연속 연도 값이 실제로 낮아졌는지 확인한다."""
    histories: dict[str, list[tuple[int, float]]] = {}
    for key in evidence_keys:
        if not key.startswith("financial_history."):
            continue
        parts = key.split(".")
        if len(parts) != 3 or not parts[1].isdigit() or not parts[2].endswith("_growth"):
            continue
        value = metrics.get(key, {}).get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            histories.setdefault(parts[2], []).append((int(parts[1]), float(value)))
    return any(
        len(values) >= 2
        and sorted(values)[-1][1] < sorted(values)[-2][1]
        for values in histories.values()
    )


def _supports_consecutive_decline(
    text: str,
    evidence_keys: list[str],
    metrics: dict[str, dict[str, Any]],
) -> bool:
    """두 해 연속 감소 표현에 같은 성장률의 연속 음수 연도 근거가 있는지 확인한다."""
    target = None
    if "영업이익" in text:
        target = "operating_profit_growth"
    elif "당기순이익" in text or "순이익" in text:
        target = "net_income_growth"
    elif "매출" in text:
        target = "revenue_growth"
    if target is None:
        return False
    values = sorted(
        (
            int(key.split(".")[1]),
            float(metrics[key]["value"]),
        )
        for key in evidence_keys
        if key.startswith("financial_history.")
        and key.split(".")[1].isdigit()
        and _base_metric_key(key) == target
        and isinstance(metrics.get(key, {}).get("value"), (int, float))
        and not isinstance(metrics[key]["value"], bool)
    )
    return any(
        current_year == previous_year + 1
        and previous_value < 0
        and current_value < 0
        for (previous_year, previous_value), (current_year, current_value)
        in zip(values, values[1:])
    )


def _mixes_current_and_trend_without_periods(
    text: str, evidence_keys: list[str]
) -> bool:
    """단일 연도 성장률과 3년 추세를 같은 시점처럼 연결했는지 확인한다."""
    has_current_growth = any(
        not key.startswith("financial_") and _base_metric_key(key).endswith("_growth")
        for key in evidence_keys
    )
    has_trend = any(key.startswith("financial_trend.") for key in evidence_keys)
    if not (has_current_growth and has_trend):
        return False
    has_current_period = bool(re.search(r"\d{4}년|최근\s*연도", text))
    has_trend_period = bool(re.search(r"최근\s*3년|3년\s*추세", text))
    return not (has_current_period and has_trend_period)


def _normalize_no_scenario_days(
    analysis: CompanyInsight, metrics: dict[str, dict[str, Any]]
) -> None:
    """시나리오 발생일이 0일이면 모델 판단 대신 확정 문구를 사용한다."""
    days = metrics.get("weak_krw_rising_rate_days", {})
    if days.get("status") == "available" and days.get("value") == 0:
        analysis.financial_scenario = InsightSection(
            summary=(
                "조회기간에 금리 상승과 원화 약세 조건을 동시에 충족한 거래일이 "
                "없어 시장 대비 반응과 재무 체질의 일치 여부를 판단할 수 없습니다."
            ),
            evidence_keys=["weak_krw_rising_rate_days"],
        )


def _normalize_data_basis(analysis: CompanyInsight, company: dict[str, Any]) -> None:
    """모델 문장과 무관하게 실제 재무 및 시장 기준 기간을 표시한다."""
    financial_periods = [str(period) for period in company.get("financial_periods", [])]
    if not financial_periods and company.get("financial_period"):
        financial_periods = [str(company["financial_period"])]
    financial_text = (
        f"{financial_periods[0]}년 재무"
        if len(financial_periods) == 1
        else f"{financial_periods[0]}~{financial_periods[-1]}년 재무"
        if financial_periods
        else "재무 기간 확인 불가"
    )
    market_kpi = company.get("market_kpi", {})
    start = market_kpi.get("start_date", {})
    latest = market_kpi.get("latest_date", {})
    if (
        start.get("status") == "available"
        and start.get("value")
        and latest.get("status") == "available"
        and latest.get("value")
    ):
        analysis.data_basis = (
            f"{financial_text}, 시장 기준 기간: {start['value']} ~ {latest['value']}"
        )
    else:
        analysis.data_basis = financial_text


def _trend_section(
    metrics: dict[str, dict[str, Any]],
    keys: tuple[str, ...],
    category: str,
) -> InsightSection | None:
    evidence = [
        f"financial_trend.{key}"
        for key in keys
        if metrics.get(f"financial_trend.{key}", {}).get("status") == "available"
        and metrics[f"financial_trend.{key}"].get("value") is not None
    ]
    if not evidence:
        return None
    grouped: dict[str, list[str]] = {}
    for key in evidence:
        value = str(metrics[key]["value"])
        grouped.setdefault(value, []).append(TREND_LABELS[_base_metric_key(key)])
    parts = [f"{', '.join(labels)} {value}" for value, labels in grouped.items()]
    joined = " 및 ".join(parts)
    particle = _direction_particle(joined)
    return InsightSection(
        summary=f"최근 3년 {category} 추세는 {joined}{particle} 나타났습니다.",
        evidence_keys=evidence[:4],
    )


def _deterministic_section(
    section_name: str,
    company: dict[str, Any],
    metrics: dict[str, dict[str, Any]],
) -> InsightSection:
    """재시도 후에도 부적절한 문장은 실제 KPI 기반 문장으로 교체한다."""
    if section_name == "growth":
        keys = ("revenue_growth", "operating_profit_growth", "net_income_growth")
        available = [
            key
            for key in keys
            if metrics.get(key, {}).get("status") == "available"
            and isinstance(metrics[key].get("value"), (int, float))
        ]
        if available and all(metrics[key]["value"] > 0 for key in available):
            growth_labels = {
                "revenue_growth": "매출",
                "operating_profit_growth": "영업이익",
                "net_income_growth": "당기순이익",
            }
            labels = [growth_labels[key] for key in available]
            joined = (
                labels[0]
                if len(labels) == 1
                else f"{', '.join(labels[:-1])}과 {labels[-1]}"
            )
            return InsightSection(
                summary=f"최근 연도의 {joined} 성장률은 모두 양수입니다.",
                evidence_keys=available,
            )
        trend = _trend_section(metrics, keys, "성장성")
        if trend:
            return trend
    if section_name == "profitability":
        trend = _trend_section(
            metrics, ("operating_margin", "net_margin", "roe", "roa"), "수익성"
        )
        if trend:
            return trend
        evidence = [
            key
            for key in ("operating_margin", "net_margin", "roe", "roa")
            if metrics.get(key, {}).get("status") == "available"
            and metrics[key].get("value") is not None
        ]
        if evidence:
            return InsightSection(
                summary="최근 연도의 수익성 지표를 확인할 수 있습니다.",
                evidence_keys=evidence[:4],
            )
    if section_name == "stability":
        trend = _trend_section(
            metrics, ("debt_ratio", "interest_coverage_ratio"), "재무 안정성"
        )
        if trend:
            return trend
    if section_name == "efficiency":
        trend = _trend_section(metrics, ("accounts_receivable_days",), "효율성")
        if trend:
            return trend
    if section_name == "market":
        evidence = [
            key
            for key in ("period_return", "market_index_change")
            if metrics.get(key, {}).get("status") == "available"
            and isinstance(metrics[key].get("value"), (int, float))
        ]
        if len(evidence) == 2:
            company_direction = "상승" if metrics["period_return"]["value"] > 0 else "하락"
            market_direction = "상승" if metrics["market_index_change"]["value"] > 0 else "하락"
            relation = "같은 방향" if company_direction == market_direction else "서로 다른 방향"
            relative = (
                "높았습니다"
                if metrics["period_return"]["value"] > metrics["market_index_change"]["value"]
                else "낮았습니다"
                if metrics["period_return"]["value"] < metrics["market_index_change"]["value"]
                else "같았습니다"
            )
            return InsightSection(
                summary=(
                    f"조회기간 주가는 {company_direction}, 비교 시장지수는 "
                    f"{market_direction}해 {relation}으로 움직였습니다. 기업 수익률은 "
                    f"비교 시장지수보다 {relative}."
                ),
                evidence_keys=evidence,
            )
    if section_name == "financial_scenario":
        evidence = [
            key
            for key in (
                "weak_krw_rising_rate_days",
                "weak_krw_rising_rate_sample_quality",
                "weak_krw_rising_rate_excess_return",
            )
            if metrics.get(key, {}).get("status") == "available"
            and metrics[key].get("value") is not None
        ]
        if evidence:
            debt_key = "financial_trend.debt_ratio"
            coverage_key = "financial_trend.interest_coverage_ratio"
            mixed_stability = (
                metrics.get(debt_key, {}).get("status") == "available"
                and metrics.get(debt_key, {}).get("value") == "악화"
                and metrics.get(coverage_key, {}).get("status") == "available"
                and metrics.get(coverage_key, {}).get("value") == "개선"
            )
            if mixed_stability:
                return InsightSection(
                    summary=(
                        "시나리오 발생일, 표본 수준과 시장 대비 과거 반응은 "
                        "확인되지만, 부채비율과 이자보상배율 추세가 엇갈려 재무 "
                        "체질과의 뚜렷한 일치 여부는 확인되지 않았습니다."
                    ),
                    evidence_keys=evidence + [debt_key, coverage_key],
                )
            return InsightSection(
                summary=(
                    "시나리오 발생일과 시장 대비 과거 반응은 확인할 수 있지만, "
                    "재무 체질과의 뚜렷한 일치 여부는 확인되지 않았습니다."
                ),
                evidence_keys=evidence,
            )
    if section_name == "overall_summary":
        evidence = []
        clauses = []
        debt_key = "financial_trend.debt_ratio"
        coverage_key = "financial_trend.interest_coverage_ratio"
        if all(metrics.get(key, {}).get("status") == "available" for key in (debt_key, coverage_key)):
            debt_direction = metrics[debt_key]["value"]
            coverage_direction = metrics[coverage_key]["value"]
            if debt_direction == coverage_direction == "개선":
                clauses.append(
                    "최근 3년 부채비율과 이자보상배율 추세는 모두 개선으로 "
                    "나타났습니다."
                )
            elif debt_direction == coverage_direction == "악화":
                clauses.append(
                    "최근 3년 부채비율과 이자보상배율 추세는 모두 악화로 "
                    "나타났습니다."
                )
            elif {debt_direction, coverage_direction} == {"개선", "악화"}:
                clauses.append(
                    f"최근 3년 부채비율은 {debt_direction}, 이자보상배율은 "
                    f"{coverage_direction}{_direction_particle(coverage_direction)} 나타나 "
                    "재무 안정성 신호가 혼재됐습니다."
                )
            else:
                clauses.append(
                    f"최근 3년 부채비율 추세는 {debt_direction}, 이자보상배율 "
                    f"추세는 {coverage_direction}{_direction_particle(coverage_direction)} "
                    "나타났습니다."
                )
            evidence.extend((debt_key, coverage_key))
        if not evidence:
            trend_evidence = [
                f"financial_trend.{key}"
                for key in TREND_LABELS
                if metrics.get(f"financial_trend.{key}", {}).get("status") == "available"
                and metrics[f"financial_trend.{key}"].get("value") is not None
            ]
            if trend_evidence:
                key = trend_evidence[0]
                clauses.append(
                    f"최근 3년 재무 지표에서 {TREND_LABELS[_base_metric_key(key)]} "
                    f"{metrics[key]['value']}가 나타났습니다."
                )
                evidence.append(key)
            else:
                current_evidence = [
                    key
                    for key in TREND_LABELS
                    if metrics.get(key, {}).get("status") == "available"
                    and metrics[key].get("value") is not None
                ]
                if current_evidence:
                    clauses.append("최근 연도의 재무 지표를 기준으로 재무 상태를 확인했습니다.")
                    evidence.append(current_evidence[0])
        if all(
            metrics.get(key, {}).get("status") == "available"
            and isinstance(metrics[key].get("value"), (int, float))
            for key in ("period_return", "market_index_change")
        ):
            company_direction = "상승" if metrics["period_return"]["value"] > 0 else "하락"
            market_direction = "상승" if metrics["market_index_change"]["value"] > 0 else "하락"
            market_name = metrics.get("market_index_name", {}).get("value") or "비교 시장지수"
            relative = (
                "높았습니다"
                if metrics["period_return"]["value"] > metrics["market_index_change"]["value"]
                else "낮았습니다"
                if metrics["period_return"]["value"] < metrics["market_index_change"]["value"]
                else "같았습니다"
            )
            clauses.append(
                f"조회기간 주가는 {company_direction}, {market_name}는 "
                f"{market_direction}했습니다. 기업 수익률은 {market_name}보다 "
                f"{relative}."
            )
            evidence.extend(("period_return", "market_index_change"))
        days = metrics.get("weak_krw_rising_rate_days", {})
        if days.get("status") == "available" and days.get("value") is not None:
            if days.get("value") == 0:
                clauses.append(
                    "금리 상승과 원화 약세 조건을 충족한 거래일이 없어 해당 시나리오 "
                    "반응은 판단할 수 없습니다."
                )
            else:
                clauses.append(
                    "금리 상승과 원화 약세 시나리오는 발생일 수를 고려한 과거 "
                    "반응으로만 해석해야 합니다."
                )
            evidence.append("weak_krw_rising_rate_days")
        if clauses:
            return InsightSection(summary=" ".join(clauses), evidence_keys=evidence)
    if section_name == "one_line_summary":
        growth_keys = (
            "revenue_growth",
            "operating_profit_growth",
            "net_income_growth",
        )
        if all(
            metrics.get(key, {}).get("status") == "available"
            and isinstance(metrics[key].get("value"), (int, float))
            and metrics[key]["value"] > 0
            for key in growth_keys
        ):
            periods = company.get("financial_periods", [])
            period = company.get("financial_period") or (
                periods[-1] if periods else None
            )
            period_label = f"{period}년" if period else "최근 연도"
            return InsightSection(
                summary=(
                    f"{period_label} 매출과 영업이익, 당기순이익이 모두 "
                    "전년 대비 증가했습니다."
                ),
                evidence_keys=list(growth_keys),
            )
        evidence = [
            key
            for key in (
                "financial_trend.operating_margin",
                "financial_trend.debt_ratio",
                "financial_trend.interest_coverage_ratio",
                "financial_trend.accounts_receivable_days",
            )
            if metrics.get(key, {}).get("status") == "available"
        ]
        if evidence:
            values = {metrics[key].get("value") for key in evidence}
            if {"개선", "악화"}.issubset(values):
                summary = (
                    "수익성, 안정성 및 효율성의 최근 3년 추세에는 개선과 악화가 "
                    "함께 나타났습니다."
                    if section_name == "overall_summary"
                    else "최근 3년 재무 지표에는 개선과 악화 신호가 함께 나타나므로 "
                    "한 방향으로 단정하기 어렵습니다."
                )
            elif values == {"개선"}:
                summary = "확인 가능한 최근 3년 재무 지표는 개선 흐름으로 나타났습니다."
            elif values == {"악화"}:
                summary = "확인 가능한 최근 3년 재무 지표는 악화 흐름으로 나타났습니다."
            else:
                summary = "최근 3년 재무 지표의 방향은 하나로 모이지 않았습니다."
            return InsightSection(
                summary=summary,
                evidence_keys=evidence[:4],
            )
    return InsightSection(
        summary="제시된 사용 가능한 KPI를 바탕으로 관련 흐름을 확인할 수 있습니다.",
        evidence_keys=[],
    )


def _trend_signal_sections(
    metrics: dict[str, dict[str, Any]], target: str, company: dict[str, Any] | None = None
) -> list[InsightSection]:
    sections = []
    skip_trends = set()
    growth_keys = ("revenue_growth", "operating_profit_growth", "net_income_growth")
    if target == "개선" and all(
        metrics.get(key, {}).get("status") == "available"
        and isinstance(metrics[key].get("value"), (int, float))
        and metrics[key]["value"] > 0
        for key in growth_keys
    ):
        periods = (company or {}).get("financial_periods", [])
        period = (company or {}).get("financial_period") or (
            periods[-1] if periods else None
        )
        period_label = f"{period}년" if period else "최근 연도"
        sections.append(
            InsightSection(
                summary=(
                    f"{period_label} 매출, 영업이익과 당기순이익 성장률은 "
                    "모두 양수입니다."
                ),
                evidence_keys=list(growth_keys),
            )
        )
    debt_key = "financial_trend.debt_ratio"
    coverage_key = "financial_trend.interest_coverage_ratio"
    if (
        target == "악화"
        and metrics.get(debt_key, {}).get("status") == "available"
        and metrics.get(debt_key, {}).get("value") == "악화"
        and metrics.get(coverage_key, {}).get("status") == "available"
        and metrics.get(coverage_key, {}).get("value") == "개선"
    ):
        sections.append(
            InsightSection(
                summary=(
                    "최근 3년 부채비율 추세는 악화됐지만, 이자보상배율 추세는 "
                    "개선되어 재무 안정성 신호가 혼재됐습니다."
                ),
                evidence_keys=[debt_key, coverage_key],
            )
        )
        skip_trends.update({"debt_ratio", "interest_coverage_ratio"})
    for key, label in TREND_LABELS.items():
        if key in skip_trends:
            continue
        metric_key = f"financial_trend.{key}"
        metric = metrics.get(metric_key, {})
        if metric.get("status") != "available" or metric.get("value") != target:
            continue
        sections.append(
            InsightSection(
                summary=(
                    f"{label}의 최근 3년 추세가 "
                    f"{target}{_direction_particle(target)} 나타났습니다."
                ),
                evidence_keys=[metric_key],
            )
        )
        if len(sections) == 3:
            break
    return sections


def _validate_section_semantics(
    section: InsightSection,
    section_name: str,
    metrics: dict[str, dict[str, Any]],
) -> None:
    text = section.summary
    evidence = section.evidence_keys
    scenario_days = metrics.get("weak_krw_rising_rate_days", {}).get("value")

    if not evidence and not NO_EVIDENCE_ALLOWED_PATTERN.search(text):
        raise GPTAnalysisError(f"{section_name}의 분석 문장에 KPI 근거가 없습니다.")
    if UNSUPPORTED_QUALITY_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}에 비교 기준 없는 주관적 품질 평가가 포함되어 있습니다."
        )
    if FUTURE_GROWTH_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}에 입력 KPI로 뒷받침되지 않는 미래 성장 가능성이 포함되어 있습니다."
        )
    if NEGATIVE_DECREASE_RATE_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}에서 음수 성장률을 감소율과 중복해 표현했습니다."
        )
    if RAW_METRIC_KEY_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}에 사용자용 명칭이 아닌 내부 KPI 키가 노출되었습니다."
        )
    if VAGUE_METRIC_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}에 구체적인 KPI 이름 대신 모호한 지표 표현이 포함되어 있습니다."
        )
    if WRONG_FINANCIAL_TERM_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}의 운영 이익 또는 운영 이익률은 영업이익 또는 영업이익률로 표현해야 합니다."
        )
    reversed_years = REVERSED_YEAR_COMPARISON_PATTERN.search(text)
    if reversed_years and int(reversed_years.group(2)) < int(reversed_years.group(1)):
        raise GPTAnalysisError(
            f"{section_name}에서 성장률의 기준 연도와 대상 연도를 거꾸로 표현했습니다."
        )
    if INVENTED_COST_CAUSE_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}에 입력 데이터가 제공하지 않은 원가 원인이 포함되어 있습니다."
        )
    if UNSUPPORTED_CONCERN_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}에 근거 범위를 넘어선 우려 확대 표현이 포함되어 있습니다."
        )
    if TREND_RISK_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}에서 3년 추세의 변동 판정을 위험으로 확대했습니다."
        )
    if UNSUPPORTED_PEAK_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}에 입력 KPI가 직접 제공하지 않은 피크 또는 정점 판정이 있습니다."
        )
    if CONSECUTIVE_DECLINE_PATTERN.search(
        text
    ) and not _supports_consecutive_decline(text, evidence, metrics):
        raise GPTAnalysisError(
            f"{section_name}의 연속 감소 표현에 같은 KPI의 연속 연도 감소 근거가 없습니다."
        )
    if OPERATIONAL_EFFICIENCY_IMPROVEMENT_PATTERN.search(text):
        efficiency_trend = "financial_trend.accounts_receivable_days"
        if (
            efficiency_trend not in evidence
            or metrics.get(efficiency_trend, {}).get("value") != "개선"
        ):
            raise GPTAnalysisError(
                f"{section_name}의 운영 효율성 개선 표현에 개선 방향의 효율성 추세 근거가 없습니다."
            )
    if VOLUME_TREND_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}에서 단일 거래량 변화율을 지속적인 증가세 또는 감소세로 표현했습니다."
        )
    if COVERAGE_PROFITABILITY_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}에서 이자보상배율을 수익성 지표로 잘못 해석했습니다."
        )
    if FINANCIAL_GROWTH_VOLATILITY_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}에서 재무 성장 추세의 변동 판정을 변동성으로 표현했습니다."
        )
    if GROWTH_SUSTAINABILITY_ATTENTION_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}에서 성장률 추세의 변동 판정을 성장 지속성 판단으로 확대했습니다."
        )
    if UNSUPPORTED_RECOVERY_TREND_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}에서 성장률 값을 회복세 지속으로 확대 해석했습니다."
        )
    if ENGLISH_FINANCIAL_DIRECTION_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}에 사용자 문맥과 맞지 않는 영문 방향 표현이 포함되어 있습니다."
        )
    if _has_missing_period_metric_evidence(text, evidence, metrics):
        raise GPTAnalysisError(
            f"{section_name}에서 특정 연도의 성장 수치를 언급했지만 해당 연도 KPI 근거가 없습니다."
        )
    if PLAN_CLAIM_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}에 입력 데이터에 없는 계획 또는 계획 대비 표현이 포함되어 있습니다."
        )
    if GROWTH_SLOWDOWN_PATTERN.search(text) and not _supports_growth_slowdown(
        evidence, metrics
    ):
        raise GPTAnalysisError(
            f"{section_name}의 성장 속도 둔화 표현에 같은 KPI의 복수 연도 근거가 없습니다."
        )
    if SCENARIO_FUTURE_RESULT_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}에 시나리오의 미래 결과 가능성을 예측하는 표현이 있습니다."
        )
    if CURRENT_PRICE_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}의 latest_close는 현재 주가가 아니라 최근 종가입니다."
        )
    if TREND_HEDGING_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}에서 계산된 재무 추세 판정을 불확실한 표현으로 바꿨습니다."
        )
    if PRICE_RETURN_CONFLATION_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}에서 최근 종가와 조회기간 수익률을 하나의 결과처럼 연결했습니다."
        )
    if RECEIVABLE_MISINTERPRETATION_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}에서 매출채권 회전일수를 지급기간이나 비효율성으로 단정했습니다."
        )
    improvement_start = IMPROVEMENT_START_PATTERN.search(text)
    if improvement_start:
        start_period = int(improvement_start.group(1))
        history_periods = {
            int(key.split(".")[1])
            for key in evidence
            if key.startswith("financial_history.")
            and key.split(".")[1].isdigit()
            and int(key.split(".")[1]) >= start_period
        }
        if len(history_periods) < 2:
            raise GPTAnalysisError(
                f"{section_name}의 개선 시작 시점 표현에 복수 연도 근거가 없습니다."
            )
    if MIXED_LONG_TERM_SIGNAL_PATTERN.search(text):
        trend_evidence = [
            key for key in evidence if key.startswith("financial_trend.")
        ]
        if len(trend_evidence) < 2 or _evidence_directions(
            trend_evidence, metrics
        ) != {-1, 1}:
            raise GPTAnalysisError(
                f"{section_name}의 최근 3년 혼재 신호에 상반된 추세 근거가 없습니다."
            )
    if GENERIC_FINANCIAL_CHANGE_PATTERN.search(text) and not any(
        key.startswith("financial_trend.") for key in evidence
    ):
        raise GPTAnalysisError(
            f"{section_name}의 일부 재무 지표 변화 표현에 추세 근거가 없습니다."
        )
    if UNSUPPORTED_PROFIT_STATUS_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}에 입력 KPI가 직접 제공하지 않은 적자 또는 흑자 판정이 있습니다."
        )
    if GROWTH_RATE_AS_CHANGING_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}에서 성장률 수치를 성장률 자체의 변화로 표현했습니다."
        )
    if GROWTH_VALUE_AS_QUALITY_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}에서 성장률 수치를 매출이나 이익의 개선 또는 악화로 표현했습니다."
        )
    if GROWTH_TREND_VOLATILITY_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}에서 재무 추세 판정 '변동'을 주가 변동성처럼 표현했습니다."
        )
    if YEAR_UNTIL_CONTINUING_TREND_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}에서 최근 3년 추세를 특정 연도까지 지속된 상태로 확대했습니다."
        )
    if GROWTH_TREND_CLAIM_PATTERN.search(text):
        has_growth_trend = any(
            key in evidence
            for key in (
                "financial_trend.revenue_growth",
                "financial_trend.operating_profit_growth",
                "financial_trend.net_income_growth",
            )
        )
        if not has_growth_trend:
            raise GPTAnalysisError(
                f"{section_name}의 3년 성장 추세 표현에 financial_trend 근거가 없습니다."
            )
    if COLLECTIVE_GROWTH_TREND_PATTERN.search(text):
        required_growth_trends = {
            "financial_trend.revenue_growth",
            "financial_trend.operating_profit_growth",
            "financial_trend.net_income_growth",
        }
        if not required_growth_trends.issubset(evidence):
            raise GPTAnalysisError(
                f"{section_name}의 매출과 이익 성장률 추세 표현에 각 KPI의 추세 근거가 필요합니다."
            )
    if YEAR_BY_YEAR_PATTERN.search(text):
        history_periods = {
            key.split(".")[1]
            for key in evidence
            if key.startswith("financial_history.")
        }
        if len(history_periods) < 2:
            raise GPTAnalysisError(
                f"{section_name}의 연도별 표현에 복수 연도 근거가 없습니다."
            )
    if UNSUPPORTED_LEVEL_COMPARISON_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}에서 비교 기준 없이 재무 KPI가 높거나 낮다고 평가했습니다."
        )
    if CURRENT_LEVEL_AS_TREND_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}에서 현재 KPI 값과 3년 추세 판정을 하나의 값처럼 표현했습니다."
        )
    if GROWTH_IMPROVEMENT_PATTERN.search(text):
        growth_trends = [
            key
            for key in evidence
            if key in {
                "financial_trend.revenue_growth",
                "financial_trend.operating_profit_growth",
                "financial_trend.net_income_growth",
            }
        ]
        if not growth_trends or any(
            metrics[key].get("value") != "개선" for key in growth_trends
        ):
            raise GPTAnalysisError(
                f"{section_name}의 성장성 향상 표현과 3년 성장 추세가 일치하지 않습니다."
            )
    if PROFITABILITY_IMPROVEMENT_PATTERN.search(
        text
    ) and not _has_profitability_change_evidence(evidence, metrics):
        raise GPTAnalysisError(
            f"{section_name}의 수익성 개선 표현에 수익성 KPI의 변화 근거가 없습니다."
        )
    if STABILITY_ASSURANCE_PATTERN.search(text):
        required = {
            "financial_trend.debt_ratio",
            "financial_trend.interest_coverage_ratio",
        }
        if not required.issubset(evidence) or any(
            metrics[key].get("value") != "개선" for key in required
        ):
            raise GPTAnalysisError(
                f"{section_name}은 부채비율과 이자보상배율이 함께 개선된 근거 없이 "
                "재무 안정성을 단정할 수 없습니다."
            )
    if section_name == "one_line_summary" and len(evidence) > 4:
        raise GPTAnalysisError("한줄 요약의 KPI 근거는 최대 4개여야 합니다.")
    if evidence and BOILERPLATE_SIGNAL_PATTERN.search(text):
        raise GPTAnalysisError(f"{section_name}에 반복적인 기본 문장이 포함되어 있습니다.")
    evidence_bases = {_base_metric_key(key) for key in evidence}
    for term_pattern, required_bases in METRIC_TERM_REQUIREMENTS:
        if term_pattern.search(text) and evidence_bases.isdisjoint(required_bases):
            raise GPTAnalysisError(
                f"{section_name}에서 언급한 지표명과 evidence_keys가 일치하지 않습니다."
            )

    if _has_direction_mismatch(text, evidence, metrics):
        raise GPTAnalysisError(
            f"{section_name}의 상승·하락 또는 증가·감소 표현이 KPI 부호와 반대입니다."
        )
    if _has_trend_wording_mismatch(text, evidence, metrics):
        raise GPTAnalysisError(
            f"{section_name}의 KPI 증감 표현이 3년 추세 판정 방향과 반대입니다."
        )
    if MIXED_PERIOD_SIMULTANEITY_PATTERN.search(
        text
    ) and _mixes_current_and_trend_without_periods(text, evidence):
        raise GPTAnalysisError(
            f"{section_name}에서 단일 연도 성장과 3년 추세를 같은 시점의 변화처럼 연결했습니다."
        )

    level_change_claims = _level_change_claims(text)
    if FINANCIAL_CHANGE_CLAIM_PATTERN.search(text) and not _has_change_evidence(
        evidence, level_change_claims
    ):
        raise GPTAnalysisError(
            f"{section_name}의 증가·감소·개선·악화 표현에 추세 또는 복수 연도 근거가 없습니다."
        )

    if RELATIVE_MARKET_PATTERN.search(text) and not (
        section_name == "financial_scenario" and scenario_days == 0
    ):
        has_scenario_excess = "weak_krw_rising_rate_excess_return" in evidence
        has_period_comparison = {
            "period_return",
            "market_index_change",
        }.issubset(evidence)
        if not has_scenario_excess and not has_period_comparison:
            raise GPTAnalysisError(
                f"{section_name}의 시장 대비 표현에 기업과 시장의 비교 근거가 모두 필요합니다."
            )
    if (
        section_name == "market"
        and {"period_return", "market_index_change"}.issubset(evidence)
        and not re.search(r"시장지수보다|시장\s*대비|KOSPI보다|KOSDAQ보다", text)
    ):
        raise GPTAnalysisError("시장 흐름에는 기업 수익률과 시장지수의 상대 비교가 필요합니다.")

    if "daily_volatility" in evidence and RELATIVE_VOLATILITY_PATTERN.search(text):
        raise GPTAnalysisError(
            f"{section_name}은 비교 기준 없이 변동성을 높거나 낮다고 평가할 수 없습니다."
        )

    if STABILITY_CONCERN_PATTERN.search(text) or DEBT_RISK_PATTERN.search(text):
        required = {
            "financial_trend.debt_ratio",
            "financial_trend.interest_coverage_ratio",
        }
        if not required.issubset(evidence) or any(
            metrics[key].get("value") != "악화" for key in required
        ):
            raise GPTAnalysisError(
                f"{section_name}은 부채비율과 이자보상배율이 함께 악화된 근거 없이 "
                "재무 안정성 우려를 단정할 수 없습니다."
            )

    if section_name == "overall_summary":
        financial_available = any(
            metric.get("status") == "available" and metric.get("value") is not None
            for key, metric in metrics.items()
            if key.startswith("financial_trend.")
            or key.startswith("financial_history.")
            or key in TREND_LABELS
        )
        has_financial = any(
            key.startswith("financial_trend.")
            or key.startswith("financial_history.")
            or key in TREND_LABELS
            for key in evidence
        )
        if financial_available and not has_financial:
            raise GPTAnalysisError("종합 분석에 재무 KPI 근거가 필요합니다.")
        comparable_market = all(
            metrics.get(key, {}).get("status") == "available"
            and metrics[key].get("value") is not None
            for key in ("period_return", "market_index_change")
        )
        if comparable_market and not {
            "period_return",
            "market_index_change",
        }.issubset(evidence):
            raise GPTAnalysisError("종합 분석에 기업과 시장지수 수익률 근거가 필요합니다.")
        scenario_days = metrics.get("weak_krw_rising_rate_days", {})
        if (
            scenario_days.get("status") == "available"
            and scenario_days.get("value") is not None
            and "weak_krw_rising_rate_days" not in evidence
        ):
            raise GPTAnalysisError("종합 분석에 시나리오 발생일 수 근거가 필요합니다.")

    if section_name == "relationships_and_mismatches" and MISMATCH_LANGUAGE_PATTERN.search(text):
        if _evidence_directions(evidence, metrics) != {-1, 1}:
            raise GPTAnalysisError(
                "KPI 불일치 표현에는 실제로 서로 반대인 방향 근거가 필요합니다."
            )
    if section_name == "relationships_and_mismatches" and NOT_ALL_IMPROVED_PATTERN.search(text):
        if _evidence_directions(evidence, metrics) == {1}:
            raise GPTAnalysisError(
                "모든 근거 KPI가 같은 증가 방향인데 일부만 개선됐다고 표현할 수 없습니다."
            )

    if section_name != "financial_scenario":
        return
    days_metric = metrics.get("weak_krw_rising_rate_days", {})
    days = days_metric.get("value")
    if days_metric.get("status") != "available" or not isinstance(days, (int, float)):
        return
    if "weak_krw_rising_rate_days" not in evidence:
        raise GPTAnalysisError("시나리오 분석에는 발생일 수 근거가 필요합니다.")
    if days > 0:
        required_observation = {
            key
            for key in (
                "weak_krw_rising_rate_sample_quality",
                "weak_krw_rising_rate_excess_return",
            )
            if metrics.get(key, {}).get("status") == "available"
            and metrics[key].get("value") is not None
        }
        if not required_observation.issubset(evidence):
            raise GPTAnalysisError(
                "발생일이 있는 시나리오 분석에는 표본 수준과 시장 대비 차이 근거가 필요합니다."
            )
    if FINANCIAL_CONDITION_CHANGE_PATTERN.search(text):
        used_trends = {
            key: metrics.get(key, {}).get("value")
            for key in SCENARIO_TREND_KEYS
            if key in evidence
        }
        if not used_trends or {"개선", "악화"}.issubset(set(used_trends.values())):
            raise GPTAnalysisError(
                "재무 체질 개선 또는 악화 표현에 일관된 재무 추세 근거가 필요합니다."
            )
    claims_vulnerability = bool(SCENARIO_VULNERABILITY_PATTERN.search(text))
    claims_buffer = bool(SCENARIO_BUFFER_PATTERN.search(text))
    if days < 5 and (claims_vulnerability or claims_buffer):
        raise GPTAnalysisError(
            "시나리오 표본이 매우 적을 때는 취약 또는 완충 가능성을 판정할 수 없습니다."
        )
    if not (claims_vulnerability or claims_buffer):
        return
    required_scenario = {
        "weak_krw_rising_rate_days",
        "weak_krw_rising_rate_sample_quality",
        "weak_krw_rising_rate_excess_return",
    }
    if not required_scenario.issubset(evidence):
        raise GPTAnalysisError("시나리오 판정에 발생일, 표본 수준과 시장 대비 차이가 필요합니다.")
    excess = metrics["weak_krw_rising_rate_excess_return"].get("value")
    trend_values = {
        key: metrics.get(key, {}).get("value") for key in SCENARIO_TREND_KEYS
    }
    if claims_vulnerability and not (
        isinstance(excess, (int, float))
        and excess < 0
        and "악화" in trend_values.values()
        and "개선" not in trend_values.values()
    ):
        raise GPTAnalysisError("취약 가능성 판정 조건과 실제 KPI 방향이 일치하지 않습니다.")
    if claims_buffer and not (
        isinstance(excess, (int, float))
        and excess > 0
        and "개선" in trend_values.values()
        and "악화" not in trend_values.values()
    ):
        raise GPTAnalysisError("완충 가능성 판정 조건과 실제 KPI 방향이 일치하지 않습니다.")


def _validate_response(parsed: KPIInsightResponse, payload: dict[str, Any]) -> None:
    companies = payload.get("companies", [])
    company_payloads = {company["company"]: company for company in companies}
    lookup = _payload_lookup(payload)
    expected = set(company_payloads)
    received = {item.company for item in parsed.analyses}
    if len(parsed.analyses) != len(received) or received != expected:
        raise GPTAnalysisError("요청한 기업과 GPT 분석 결과의 기업 목록이 일치하지 않습니다.")

    for analysis in parsed.analyses:
        _normalize_data_basis(analysis, company_payloads[analysis.company])
        _normalize_no_scenario_days(analysis, lookup[analysis.company])
        available = {
            key for key, metric in lookup[analysis.company].items()
            if metric.get("status") == "available" and metric.get("value") is not None
        }
        allowed_numbers = _allowed_numbers(company_payloads[analysis.company])

        def validate_section(section: InsightSection, context: str) -> None:
            section.evidence_keys = [
                _canonical_metric_key(key) for key in section.evidence_keys
            ]
            invalid = set(section.evidence_keys) - available
            if invalid:
                section.evidence_keys = [
                    key for key in section.evidence_keys if key in available
                ]
                section.summary = (
                    "제시된 사용 가능한 KPI를 바탕으로 관련 흐름을 확인할 수 있습니다."
                )
            _validate_numbers(
                section.summary,
                _section_numbers(
                    section.evidence_keys,
                    lookup[analysis.company],
                    company_payloads[analysis.company],
                ),
                context,
            )
            _validate_language(section.summary)
            _validate_section_semantics(
                section,
                context.rsplit(" ", 1)[-1],
                lookup[analysis.company],
            )

        for section_name in SECTIONS:
            validate_section(
                getattr(analysis, section_name), f"{analysis.company} {section_name}"
            )
        for section_list_name in SECTION_LISTS:
            for section in getattr(analysis, section_list_name):
                if section_list_name == "additional_checks" and not section.evidence_keys:
                    continue
                validate_section(
                    section, f"{analysis.company} {section_list_name}"
                )
        analysis.additional_checks = [
            section for section in analysis.additional_checks if section.evidence_keys
        ]
        _validate_numbers(
            analysis.data_basis, allowed_numbers, f"{analysis.company} 데이터 기준"
        )
        _validate_language(analysis.data_basis)

    if len(expected) == 1 and parsed.comparisons:
        raise GPTAnalysisError("단일 기업 분석에 기업 간 비교가 포함되었습니다.")
    if len(expected) > 1 and not parsed.comparisons:
        raise GPTAnalysisError("복수 기업 분석에 기업 간 비교가 없습니다.")
    comparison_numbers = [
        value
        for company in companies
        for value in _allowed_numbers(company)
    ]
    for comparison in parsed.comparisons:
        cited_companies = set()
        for reference in comparison.evidence:
            reference.metric_key = _canonical_metric_key(reference.metric_key)
            if reference.company not in expected:
                raise GPTAnalysisError("기업 간 비교가 요청하지 않은 기업을 참조했습니다.")
            metric = lookup[reference.company].get(reference.metric_key)
            if not metric or metric.get("status") != "available" or metric.get("value") is None:
                raise GPTAnalysisError("기업 간 비교가 사용할 수 없는 KPI 근거를 참조했습니다.")
            cited_companies.add(reference.company)
        if len(cited_companies) < 2:
            raise GPTAnalysisError("기업 간 비교 근거에는 두 개 이상의 기업이 필요합니다.")
        _validate_numbers(comparison.summary, comparison_numbers, "기업 간 비교")
        _validate_language(comparison.summary)


def _deterministic_comparisons(
    company_payloads: dict[str, dict[str, Any]],
    lookup: dict[str, dict[str, dict[str, Any]]],
) -> list[ComparisonInsight]:
    """모든 기업에 공통인 대표 KPI로 분야별 비교를 만든다."""
    company_names = list(company_payloads)
    comparisons: list[ComparisonInsight] = []

    for group_name, candidates in COMPARISON_GROUPS:
        selected: tuple[str, str, str] | None = None
        values: dict[str, float] = {}
        for metric_key, label, preferred_direction in candidates:
            candidate_values = {
                company_name: lookup[company_name].get(metric_key, {}).get("value")
                for company_name in company_names
            }
            if all(
                isinstance(value, (int, float)) and not isinstance(value, bool)
                for value in candidate_values.values()
            ):
                selected = (metric_key, label, preferred_direction)
                values = {
                    company_name: float(value)
                    for company_name, value in candidate_values.items()
                }
                break

        if selected is None:
            continue

        metric_key, label, preferred_direction = selected
        best_value = (
            min(values.values())
            if preferred_direction == "lower"
            else max(values.values())
        )
        opposite_value = (
            max(values.values())
            if preferred_direction == "lower"
            else min(values.values())
        )
        best_names = [name for name in company_names if values[name] == best_value]
        opposite_names = [
            name for name in company_names if values[name] == opposite_value
        ]

        if best_value == opposite_value:
            summary = f"{group_name}: 모든 기업의 {label}이 같습니다."
        elif len(company_names) == 2:
            direction = "낮습니다" if preferred_direction == "lower" else "높습니다"
            summary = (
                f"{group_name}: {best_names[0]}의 {label}{_subject_particle(label)} "
                f"{opposite_names[0]}보다 {direction}."
            )
        else:
            best_text = ", ".join(best_names)
            opposite_text = ", ".join(opposite_names)
            direction = "가장 낮고" if preferred_direction == "lower" else "가장 높고"
            opposite_direction = (
                "가장 높습니다" if preferred_direction == "lower" else "가장 낮습니다"
            )
            summary = (
                f"{group_name}: {best_text}의 {label}{_subject_particle(label)} {direction}, "
                f"{opposite_text}가 {opposite_direction}."
            )

        comparisons.append(
            ComparisonInsight(
                summary=summary,
                evidence=[
                    MetricReference(company=company_name, metric_key=metric_key)
                    for company_name in company_names
                ],
            )
        )

    return comparisons


def _fallback_company_insight(company: dict[str, Any]) -> CompanyInsight:
    """모델이 누락한 기업에 대해 숫자를 새로 만들지 않는 최소 인사이트를 구성한다."""
    available = {
        key
        for group_name in KPI_GROUPS
        for key, metric in company.get(group_name, {}).items()
        if metric.get("status") == "available" and metric.get("value") is not None
    }
    available.update(
        f"financial_trend.{key}"
        for key, metric in company.get("financial_trend", {}).items()
        if metric.get("status") == "available" and metric.get("value") is not None
    )

    def section(summary: str, candidates: tuple[str, ...] = ()) -> InsightSection:
        return InsightSection(
            summary=summary,
            evidence_keys=[key for key in candidates if key in available],
        )

    return CompanyInsight(
        company=company["company"],
        one_line_summary=section(
            "제시된 KPI를 종합하면 재무 및 시장 흐름을 확인할 수 있습니다."
        ),
        data_basis="제공된 재무 및 시장 데이터 기준",
        growth=section(
            "제시된 성장성 KPI를 통해 성장 흐름을 확인할 수 있습니다.",
            ("revenue_growth", "operating_profit_growth", "net_income_growth"),
        ),
        profitability=section(
            "제시된 수익성 KPI를 통해 수익성 흐름을 확인할 수 있습니다.",
            ("operating_margin", "net_margin", "roe", "roa"),
        ),
        stability=section(
            "제시된 재무 안정성 KPI를 통해 안정성 흐름을 확인할 수 있습니다.",
            ("debt_ratio", "interest_coverage_ratio"),
        ),
        efficiency=section(
            "제시된 효율성 KPI를 통해 운영 효율 흐름을 확인할 수 있습니다.",
            ("accounts_receivable_days",),
        ),
        market=section(
            "제시된 시장 KPI를 통해 주가와 거래 흐름을 확인할 수 있습니다.",
            ("period_return", "daily_volatility", "recent_volume_change"),
        ),
        financial_scenario=section(
            "제시된 재무 체질과 시나리오 KPI를 통해 두 결과의 일치 여부를 확인할 수 있습니다.",
            (
                "financial_trend.debt_ratio",
                "financial_trend.operating_margin",
                "weak_krw_rising_rate_days",
                "weak_krw_rising_rate_sample_quality",
                "weak_krw_rising_rate_excess_return",
            ),
        ),
        relationships_and_mismatches=[],
        positive_signals=[],
        caution_signals=[],
        additional_checks=[],
        overall_summary=section(
            "제시된 KPI를 종합해 재무 및 시장 흐름을 확인할 수 있습니다."
        ),
    )


def _repair_validation_issues(
    parsed: KPIInsightResponse, payload: dict[str, Any]
) -> None:
    """재시도 후에도 남은 잘못된 근거와 문장만 제거해 유효한 분석을 보존한다."""
    company_payloads = {
        company["company"]: company for company in payload.get("companies", [])
    }
    lookup = _payload_lookup(payload)
    expected = set(company_payloads)
    analyses_by_company: dict[str, CompanyInsight] = {}
    for analysis in parsed.analyses:
        if analysis.company in expected and analysis.company not in analyses_by_company:
            analyses_by_company[analysis.company] = analysis
    parsed.analyses = [
        analyses_by_company.get(company_name)
        or _fallback_company_insight(company_payloads[company_name])
        for company_name in company_payloads
    ]
    for analysis in parsed.analyses:
        company = company_payloads[analysis.company]
        metrics = lookup[analysis.company]
        _normalize_data_basis(analysis, company)
        _normalize_no_scenario_days(analysis, metrics)
        available = {
            key
            for key, metric in metrics.items()
            if metric.get("status") == "available" and metric.get("value") is not None
        }

        def section_is_valid(section: InsightSection, section_name: str) -> bool:
            section.evidence_keys = [
                key
                for key in (
                    _canonical_metric_key(key) for key in section.evidence_keys
                )
                if key in available
            ]
            if (
                section_name == "financial_scenario"
                and "weak_krw_rising_rate_days" in available
                and "weak_krw_rising_rate_days" not in section.evidence_keys
            ):
                section.evidence_keys.append("weak_krw_rising_rate_days")
            allowed = _section_numbers(section.evidence_keys, metrics, company)
            try:
                _validate_numbers(section.summary, allowed, analysis.company)
                _validate_language(section.summary)
                _validate_section_semantics(section, section_name, metrics)
            except GPTAnalysisError:
                return False
            return True

        for section_name in SECTIONS:
            section = getattr(analysis, section_name)
            if section_is_valid(section, section_name):
                continue
            replacement = _deterministic_section(section_name, company, metrics)
            setattr(analysis, section_name, replacement)

        for section_list_name in SECTION_LISTS:
            valid_sections = [
                section
                for section in getattr(analysis, section_list_name)
                if section_is_valid(section, section_list_name)
            ]
            setattr(analysis, section_list_name, valid_sections)
        if not analysis.positive_signals:
            analysis.positive_signals = _trend_signal_sections(
                metrics, "개선", company
            )
        if not analysis.caution_signals:
            analysis.caution_signals = _trend_signal_sections(
                metrics, "악화", company
            )

    if len(expected) == 1:
        parsed.comparisons = []
        return

    parsed.comparisons = _deterministic_comparisons(company_payloads, lookup)
    if not parsed.comparisons:
        raise GPTAnalysisError("기업 간에 공통으로 비교할 수 있는 KPI가 없습니다.")


def _find_refusal(response: Any) -> str | None:
    for output in getattr(response, "output", []) or []:
        for content in getattr(output, "content", []) or []:
            if getattr(content, "type", None) == "refusal":
                return getattr(content, "refusal", None) or "요청이 거부되었습니다."
    return None


def build_fallback_insights(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """GPT 호출 실패 시 계산된 KPI만으로 검증 가능한 최소 인사이트를 만든다."""
    parsed = KPIInsightResponse(analyses=[], comparisons=[])
    _repair_validation_issues(parsed, payload)
    _validate_response(parsed, payload)
    return {
        "analyses": [item.model_dump() for item in parsed.analyses],
        "comparisons": [item.model_dump() for item in parsed.comparisons],
    }


def analyze_kpis(
    payload: dict[str, Any],
    project_root: Path,
    *,
    model: str | None = None,
    timeout: float = 90.0,
    max_retries: int = 1,
    max_validation_attempts: int = MAX_VALIDATION_ATTEMPTS,
) -> dict[str, list[dict[str, Any]]]:
    """KPI 계약을 전달하고 기업별 구조화된 인사이트를 반환한다."""
    try:
        from openai import (
            APIConnectionError,
            APITimeoutError,
            AuthenticationError,
            BadRequestError,
            OpenAI,
            RateLimitError,
        )
    except ImportError as error:
        raise GPTAnalysisError("openai 패키지가 설치되어 있지 않습니다.") from error

    client = OpenAI(
        api_key=get_openai_api_key(project_root),
        timeout=timeout,
        max_retries=max_retries,
    )
    selected_model = model or os.getenv("OPENAI_MODEL") or DEFAULT_MODEL
    company_count = len(payload.get("companies", []))
    max_output_tokens = min(16_000, 4_000 + 4_000 * max(1, company_count))
    base_input = (
        "다음 KPI JSON만 근거로 분석하십시오.\n"
        + json.dumps(payload, ensure_ascii=False, allow_nan=False)
    )

    def request_parsed(input_text: str) -> KPIInsightResponse:
        try:
            response = client.responses.parse(
                model=selected_model,
                instructions=ANALYSIS_SYSTEM_PROMPT,
                input=input_text,
                text_format=KPIInsightResponse,
                max_output_tokens=max_output_tokens,
                store=False,
            )
        except AuthenticationError as error:
            raise GPTAnalysisError("OpenAI API 인증에 실패했습니다. API 키를 확인해 주세요.") from error
        except RateLimitError as error:
            raise GPTAnalysisError("OpenAI API 요청 한도에 도달했습니다. 잠시 후 다시 시도해 주세요.") from error
        except APITimeoutError as error:
            raise GPTAnalysisError("OpenAI API 응답 시간이 초과되었습니다.") from error
        except APIConnectionError as error:
            raise GPTAnalysisError("OpenAI API에 연결할 수 없습니다.") from error
        except BadRequestError as error:
            raise GPTAnalysisError("OpenAI API 요청 형식 또는 모델 설정을 확인해 주세요.") from error
        except Exception as error:
            raise GPTAnalysisError("OpenAI API 분석 요청을 처리하지 못했습니다.") from error

        refusal = _find_refusal(response)
        if refusal:
            raise GPTAnalysisError("모델이 기업 분석 요청을 거부했습니다.")
        if response.output_parsed is None:
            raise GPTAnalysisError("구조화된 분석 결과를 받지 못했습니다.")
        return response.output_parsed

    response_requirements = (
        "입력된 기업을 정확히 한 번 포함하고 comparisons는 빈 배열로 작성하십시오."
        if company_count == 1
        else "입력된 모든 기업을 정확히 한 번씩 포함하고 comparisons를 하나 이상 작성하십시오."
    )
    request_input = base_input
    attempts = max(1, int(max_validation_attempts))
    for attempt in range(1, attempts + 1):
        parsed = request_parsed(request_input)
        try:
            _validate_response(parsed, payload)
            break
        except GPTAnalysisError as validation_error:
            if attempt == attempts:
                _repair_validation_issues(parsed, payload)
                _validate_response(parsed, payload)
                break
            correction = (
                "\n\n이전 응답이 다음 내부 검증을 통과하지 못했습니다: "
                f"{validation_error}\n"
                f"전체 응답을 처음부터 다시 작성하십시오. {response_requirements} "
                "개별 기업 분석에는 해당 기업의 available KPI만 사용하십시오. "
                "evidence_keys와 metric_key는 위 JSON에 실제 존재하는 키를 그대로 복사하고, "
                "근거 KPI에 없는 숫자는 문장에 쓰지 마십시오."
            )
            request_input = base_input + correction
    return {
        "analyses": [item.model_dump() for item in parsed.analyses],
        "comparisons": [item.model_dump() for item in parsed.comparisons],
    }
