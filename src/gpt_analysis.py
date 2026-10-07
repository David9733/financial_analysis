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


SECTIONS = (
    "one_line_summary",
    "growth",
    "profitability",
    "stability",
    "efficiency",
    "market",
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
        for history in company.get("financial_history", []):
            period = history.get("period")
            for key, metric in history.get("financial_kpi", {}).items():
                metrics[f"financial_history.{period}.{key}"] = metric
        lookup[company["company"]] = metrics
    return lookup


def _allowed_numbers(company: dict[str, Any]) -> list[float]:
    allowed = [3.0, 20.0]  # 추세 최소연도와 이동평균·볼린저밴드의 고정 창
    if company.get("financial_periods"):
        allowed.append(float(len(company["financial_periods"])))
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
    allowed = [3.0, 20.0]
    if company.get("financial_periods"):
        allowed.append(float(len(company["financial_periods"])))
        allowed.extend(float(period) for period in company["financial_periods"])
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
    return allowed


def _validate_response(parsed: KPIInsightResponse, payload: dict[str, Any]) -> None:
    companies = payload.get("companies", [])
    company_payloads = {company["company"]: company for company in companies}
    lookup = _payload_lookup(payload)
    expected = set(company_payloads)
    received = {item.company for item in parsed.analyses}
    if len(parsed.analyses) != len(received) or received != expected:
        raise GPTAnalysisError("요청한 기업과 GPT 분석 결과의 기업 목록이 일치하지 않습니다.")

    for analysis in parsed.analyses:
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

        for section_name in SECTIONS:
            validate_section(
                getattr(analysis, section_name), f"{analysis.company} {section_name}"
            )
        for section_list_name in SECTION_LISTS:
            for section in getattr(analysis, section_list_name):
                validate_section(
                    section, f"{analysis.company} {section_list_name}"
                )
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


def _fallback_company_insight(company: dict[str, Any]) -> CompanyInsight:
    """모델이 누락한 기업에 대해 숫자를 새로 만들지 않는 최소 인사이트를 구성한다."""
    available = {
        key
        for group_name in KPI_GROUPS
        for key, metric in company.get(group_name, {}).items()
        if metric.get("status") == "available" and metric.get("value") is not None
    }

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
    section_fallbacks = {
        "one_line_summary": "제시된 KPI를 종합하면 재무 및 시장 흐름을 확인할 수 있습니다.",
        "growth": "제시된 성장성 KPI를 통해 성장 흐름을 확인할 수 있습니다.",
        "profitability": "제시된 수익성 KPI를 통해 수익성 흐름을 확인할 수 있습니다.",
        "stability": "제시된 재무 안정성 KPI를 통해 안정성 흐름을 확인할 수 있습니다.",
        "efficiency": "제시된 효율성 KPI를 통해 운영 효율 흐름을 확인할 수 있습니다.",
        "market": "제시된 시장 KPI를 통해 주가와 거래 흐름을 확인할 수 있습니다.",
        "overall_summary": "제시된 KPI를 종합해 재무 및 시장 흐름을 확인할 수 있습니다.",
    }
    list_fallbacks = {
        "relationships_and_mismatches": "제시된 근거 KPI 사이의 흐름과 차이를 확인할 수 있습니다.",
        "positive_signals": "제시된 근거 KPI에서 긍정적인 흐름을 확인할 수 있습니다.",
        "caution_signals": "제시된 근거 KPI의 흐름을 주의해서 확인할 필요가 있습니다.",
        "additional_checks": "제시된 근거 KPI와 관련한 추가 확인이 필요합니다.",
    }

    for analysis in parsed.analyses:
        company = company_payloads[analysis.company]
        metrics = lookup[analysis.company]
        available = {
            key
            for key, metric in metrics.items()
            if metric.get("status") == "available" and metric.get("value") is not None
        }

        def repair_section(section: InsightSection, fallback: str) -> None:
            section.evidence_keys = [
                key
                for key in (
                    _canonical_metric_key(key) for key in section.evidence_keys
                )
                if key in available
            ]
            allowed = _section_numbers(section.evidence_keys, metrics, company)
            try:
                _validate_numbers(section.summary, allowed, analysis.company)
                _validate_language(section.summary)
            except GPTAnalysisError:
                section.summary = fallback

        for section_name, fallback in section_fallbacks.items():
            repair_section(getattr(analysis, section_name), fallback)
        for section_list_name, fallback in list_fallbacks.items():
            for section in getattr(analysis, section_list_name):
                repair_section(section, fallback)
        try:
            _validate_numbers(
                analysis.data_basis,
                _allowed_numbers(company),
                f"{analysis.company} 데이터 기준",
            )
        except GPTNumericValidationError:
            analysis.data_basis = "제공된 재무 및 시장 데이터 기준"
        try:
            _validate_language(analysis.data_basis)
        except GPTAnalysisError:
            analysis.data_basis = "제공된 재무 및 시장 데이터 기준"

    if len(expected) == 1:
        parsed.comparisons = []
        return

    companies = list(company_payloads)
    shared_keys = set(lookup[companies[0]])
    for company_name in companies[1:]:
        shared_keys &= set(lookup[company_name])
    shared_available = sorted(
        key
        for key in shared_keys
        if all(
            lookup[company_name][key].get("status") == "available"
            and lookup[company_name][key].get("value") is not None
            for company_name in companies
        )
    )
    if shared_available:
        comparison_key = shared_available[0]
        parsed.comparisons = [
            ComparisonInsight(
                summary="제시된 공통 KPI 근거로 기업 간 차이를 확인할 수 있습니다.",
                evidence=[
                    MetricReference(company=company_name, metric_key=comparison_key)
                    for company_name in companies
                ],
            )
        ]


def _find_refusal(response: Any) -> str | None:
    for output in getattr(response, "output", []) or []:
        for content in getattr(output, "content", []) or []:
            if getattr(content, "type", None) == "refusal":
                return getattr(content, "refusal", None) or "요청이 거부되었습니다."
    return None


def analyze_kpis(
    payload: dict[str, Any],
    project_root: Path,
    *,
    model: str | None = None,
    timeout: float = 90.0,
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

    client = OpenAI(api_key=get_openai_api_key(project_root), timeout=timeout, max_retries=1)
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
    for attempt in range(1, MAX_VALIDATION_ATTEMPTS + 1):
        parsed = request_parsed(request_input)
        try:
            _validate_response(parsed, payload)
            break
        except GPTAnalysisError as validation_error:
            if attempt == MAX_VALIDATION_ATTEMPTS:
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
