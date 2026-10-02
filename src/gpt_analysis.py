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


class GPTAnalysisError(RuntimeError):
    """GPT 분석을 생성하지 못했지만 기본 분석은 계속할 수 있는 오류."""


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
        for group_name in ("financial_kpi", "market_kpi"):
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
    for group_name in ("financial_kpi", "market_kpi"):
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
            raise GPTAnalysisError(f"{context}에 입력 KPI와 일치하지 않는 숫자가 포함되어 있습니다.")


def _validate_language(text: str) -> None:
    if FORBIDDEN_RECOMMENDATION_PATTERN.search(text):
        raise GPTAnalysisError("GPT 분석에 허용되지 않는 투자 추천 표현이 포함되어 있습니다.")


def _canonical_metric_key(metric_key: str) -> str:
    """모델이 JSON 경로를 붙여 반환해도 내부 KPI 키로 정규화한다."""
    for prefix in ("financial_kpi.", "market_kpi."):
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
                raise GPTAnalysisError(
                    f"{analysis.company} 분석이 사용할 수 없는 KPI 근거를 참조했습니다: "
                    + ", ".join(sorted(invalid))
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

    parsed = request_parsed(base_input)
    try:
        _validate_response(parsed, payload)
    except GPTAnalysisError as first_error:
        if company_count < 2:
            raise
        correction = (
            "\n\n이전 복수 기업 응답이 다음 내부 검증을 통과하지 못했습니다: "
            f"{first_error}\n"
            "전체 응답을 처음부터 다시 작성하십시오. 입력된 모든 기업을 정확히 한 번씩 "
            "포함하고 comparisons를 하나 이상 작성하십시오. 개별 기업 분석에는 해당 기업의 "
            "available KPI만 사용하십시오. evidence_keys와 metric_key는 위 JSON에 실제 존재하는 "
            "키를 그대로 복사하고, 근거 KPI에 없는 숫자는 문장에 쓰지 마십시오."
        )
        parsed = request_parsed(base_input + correction)
        _validate_response(parsed, payload)
    return {
        "analyses": [item.model_dump() for item in parsed.analyses],
        "comparisons": [item.model_dump() for item in parsed.comparisons],
    }
