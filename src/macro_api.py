"""한국은행 ECOS 환율과 금리 API 호출 기능."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

if __package__:
    from .dart_api import load_env_file
else:
    from dart_api import load_env_file


ECOS_URL = "https://ecos.bok.or.kr/api/StatisticSearch"
ECOS_EXCHANGE_TABLE = "731Y001"  # 주요국 통화의 대원화환율(일별)
ECOS_USD_KRW = "0000001"  # 원/미국달러(매매기준율)
ECOS_RATE_TABLE = "817Y002"  # 시장금리(일별)
ECOS_TREASURY_3Y = "010200000"  # 국고채(3년)
ECOS_CORPORATE_AA_MINUS_3Y = "010300000"  # 회사채(3년, AA-)
ECOS_PAGE_SIZE = 1000


class MacroAPIError(RuntimeError):
    """ECOS API 또는 응답 처리 실패."""


def _get_key(project_root: Path, names: tuple[str, ...], label: str) -> str:
    load_env_file(project_root / ".env")
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    raise MacroAPIError(f"프로젝트 루트의 .env에 {names[0]}를 설정해 주세요. ({label})")


def get_ecos_api_key(project_root: Path) -> str:
    return _get_key(project_root, ("ECOS_API_KEY",), "환율과 금리")


def _get_json(url: str, label: str, timeout: int = 20):
    request = Request(url, headers={"User-Agent": "dart-financial-analysis/2.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
    except HTTPError as error:
        raise MacroAPIError(f"{label} HTTP 오류: {error.code} {error.reason}") from error
    except URLError as error:
        raise MacroAPIError(f"{label} 네트워크 오류: {error.reason}") from error
    except TimeoutError as error:
        raise MacroAPIError(f"{label} API 요청 시간이 초과되었습니다.") from error
    try:
        return json.loads(payload.decode(charset))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MacroAPIError(f"{label} API 응답을 해석하지 못했습니다.") from error


def _parse_number(value) -> float | None:
    """쉼표가 포함된 숫자 문자열을 실수로 바꾼다."""
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


@dataclass
class MacroSeries:
    """날짜 오름차순 관측값과 수집 중 누락된 날짜."""

    rows: list[tuple[date, float]]
    failed_dates: list[date] = field(default_factory=list)


class InterestRateClient:
    """ECOS StatisticSearch로 일별 환율과 금리를 기간 단위로 조회한다."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def _request_page(
        self,
        start_row: int,
        end_row: int,
        start: str,
        end: str,
        item_code: str,
        table_code: str,
        label: str,
    ) -> dict:
        path = "/".join(
            quote(str(part), safe="")
            for part in (
                self.api_key,
                "json",
                "kr",
                start_row,
                end_row,
                table_code,
                "D",
                start,
                end,
                item_code,
            )
        )
        data = _get_json(f"{ECOS_URL}/{path}", label)
        if not isinstance(data, dict):
            raise MacroAPIError(f"{label} API 응답 형식이 올바르지 않습니다.")
        return data

    def _get_daily_rate(
        self,
        start_date: date,
        end_date: date,
        item_code: str,
        label: str,
        table_code: str = ECOS_RATE_TABLE,
    ) -> MacroSeries:
        if start_date > end_date:
            raise ValueError(f"{label} 시작일은 종료일보다 늦을 수 없습니다.")
        start = start_date.strftime("%Y%m%d")
        end = end_date.strftime("%Y%m%d")
        rows: list[tuple[date, float]] = []
        start_row = 1
        total = None
        while total is None or start_row <= total:
            data = self._request_page(
                start_row,
                start_row + ECOS_PAGE_SIZE - 1,
                start,
                end,
                item_code,
                table_code,
                label,
            )
            if "RESULT" in data:
                result = data["RESULT"] or {}
                code = result.get("CODE")
                if code == "INFO-200":
                    raise MacroAPIError(
                        f"{label} API 결과가 비어 있습니다. 기간 또는 "
                        f"통계표({table_code})와 항목({item_code}) 코드를 확인해 주세요."
                    )
                raise MacroAPIError(
                    f"{label} API 오류: code={code}, message={result.get('MESSAGE')}"
                )
            body = data.get("StatisticSearch") or {}
            total = int(body.get("list_total_count") or 0)
            page_rows = body.get("row") or []
            for item in page_rows:
                time_text = str(item.get("TIME", "")).strip()
                value = _parse_number(item.get("DATA_VALUE"))
                if len(time_text) != 8 or not time_text.isdigit() or value is None:
                    continue
                rows.append(
                    (date(int(time_text[:4]), int(time_text[4:6]), int(time_text[6:])), value)
                )
            if not page_rows:
                break
            start_row += ECOS_PAGE_SIZE
        rows.sort(key=lambda item: item[0])
        return MacroSeries(rows=rows)

    def get_usd_krw(self, start_date: date, end_date: date) -> MacroSeries:
        """원/달러 매매기준율을 반환한다."""
        return self._get_daily_rate(
            start_date,
            end_date,
            ECOS_USD_KRW,
            "원/달러 환율",
            table_code=ECOS_EXCHANGE_TABLE,
        )

    def get_treasury_3y(self, start_date: date, end_date: date) -> MacroSeries:
        """국고채 3년 일별 금리를 반환한다."""
        return self._get_daily_rate(
            start_date,
            end_date,
            ECOS_TREASURY_3Y,
            "국고채 3년 금리",
        )

    def get_corporate_aa_minus_3y(
        self, start_date: date, end_date: date
    ) -> MacroSeries:
        """회사채 3년 AA- 일별 금리를 반환한다."""
        return self._get_daily_rate(
            start_date,
            end_date,
            ECOS_CORPORATE_AA_MINUS_3Y,
            "회사채 3년 AA- 금리",
        )
