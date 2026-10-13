"""한국수출입은행 환율·한국은행 ECOS 금리 API 호출 기능."""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

if __package__:
    from .dart_api import load_env_file
else:
    from dart_api import load_env_file


EXIM_URL = "https://oapi.koreaexim.go.kr/site/program/financial/exchangeJSON"
ECOS_URL = "https://ecos.bok.or.kr/api/StatisticSearch"
ECOS_RATE_TABLE = "817Y002"  # 시장금리(일별)
ECOS_TREASURY_3Y = "010200000"  # 국고채(3년)
ECOS_CORPORATE_AA_MINUS_3Y = "010300000"  # 회사채(3년, AA-)
ECOS_PAGE_SIZE = 1000
EXIM_MAX_WORKERS = 4
EXIM_ATTEMPTS = 3
EXIM_RETRY_DELAY_SECONDS = 0.5
LOGGER = logging.getLogger(__name__)


class MacroAPIError(RuntimeError):
    """환율·금리 API 또는 응답 처리 실패."""


class MacroQuotaError(MacroAPIError):
    """인증키 오류나 호출 한도 초과처럼 남은 날짜도 모두 실패할 오류."""


def _get_key(project_root: Path, names: tuple[str, ...], label: str) -> str:
    load_env_file(project_root / ".env")
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    raise MacroAPIError(f"프로젝트 루트의 .env에 {names[0]}를 설정해 주세요. ({label})")


def get_exim_api_key(project_root: Path) -> str:
    return _get_key(project_root, ("KOREAEXIM_API_KEY", "EXIM_API_KEY"), "환율")


def get_ecos_api_key(project_root: Path) -> str:
    return _get_key(project_root, ("ECOS_API_KEY",), "금리")


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
    """'1,358.4'처럼 쉼표가 들어간 문자열 금액을 숫자로 바꾼다."""
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
    """날짜 오름차순 관측값과 수집 중 빠진 날짜."""

    rows: list[tuple[date, float]]
    failed_dates: list[date] = field(default_factory=list)


class ExchangeRateClient:
    """수출입은행 현재환율 API로 날짜별 USD 매매기준율을 조회한다.

    요청 1번이 날짜 1개(모든 통화)이므로 평일 수만큼 호출하고,
    바뀌지 않는 과거 날짜 결과는 디스크에 캐시한다.
    """

    def __init__(
        self,
        api_key: str,
        cache_path: Path | None = None,
        today: date | None = None,
    ) -> None:
        self.api_key = api_key
        self.cache_path = cache_path
        self.today = today or date.today()

    def _load_cache(self) -> dict[str, float | None]:
        if self.cache_path is None or not self.cache_path.is_file():
            return {}
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_cache(self, cache: dict[str, float | None]) -> None:
        if self.cache_path is None:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(dict(sorted(cache.items())), ensure_ascii=False),
            encoding="utf-8",
        )

    def fetch_usd_rate(self, target: date) -> float | None:
        """하루치 응답에서 USD 행의 deal_bas_r을 반환한다. 휴일이면 None."""
        query = urlencode(
            {"authkey": self.api_key, "searchdate": target.strftime("%Y%m%d"), "data": "AP01"}
        )
        data = _get_json(f"{EXIM_URL}?{query}", "환율")
        if not isinstance(data, list):
            raise MacroAPIError("환율 API 응답 형식이 올바르지 않습니다.")
        # 주말·공휴일, 그리고 11시 이전의 당일은 빈 배열이 온다.
        if not data:
            return None
        result_code = data[0].get("result")
        if str(result_code) == "3":
            raise MacroQuotaError("환율 API 인증키가 유효하지 않습니다.")
        if str(result_code) == "4":
            raise MacroQuotaError("환율 API 일일 호출 한도(1,000건)를 초과했습니다.")
        if str(result_code) != "1":
            LOGGER.warning("exim_unexpected_result date=%s result=%s", target, result_code)
            return None
        for item in data:
            if str(item.get("cur_unit", "")).strip().upper() == "USD":
                return _parse_number(item.get("deal_bas_r"))
        return None

    def get_usd_krw(self, start_date: date, end_date: date) -> MacroSeries:
        if start_date > end_date:
            raise ValueError("환율 시작일은 종료일보다 늦을 수 없습니다.")
        end_date = min(end_date, self.today)
        weekdays = []
        current = start_date
        while current <= end_date:
            if current.weekday() < 5:  # 주말은 빈 응답이므로 호출하지 않는다.
                weekdays.append(current)
            current += timedelta(days=1)

        cache = self._load_cache()
        pending = [day for day in weekdays if day.strftime("%Y%m%d") not in cache]
        fetched: dict[date, float | None] = {}
        failed: list[date] = []

        def fetch(day: date):
            # 동시 호출 중 간헐적으로 끊기는 경우가 있어 짧게 재시도한다.
            for attempt in range(EXIM_ATTEMPTS):
                try:
                    return day, self.fetch_usd_rate(day), None
                except MacroQuotaError as error:
                    return day, None, error
                except MacroAPIError as error:
                    if attempt + 1 == EXIM_ATTEMPTS:
                        LOGGER.warning("exim_fetch_failed date=%s error=%s", day, error)
                        return day, None, error
                    time.sleep(EXIM_RETRY_DELAY_SECONDS * (attempt + 1))
            return day, None, None

        executor = ThreadPoolExecutor(max_workers=EXIM_MAX_WORKERS)
        try:
            for day, value, error in executor.map(fetch, pending):
                if isinstance(error, MacroQuotaError):
                    # 남은 요청도 같은 이유로 실패하므로 대기 중인 호출을 취소한다.
                    executor.shutdown(wait=False, cancel_futures=True)
                    self._save_fetched(cache, fetched)
                    raise error
                if error is not None:
                    failed.append(day)
                    continue
                fetched[day] = value
        finally:
            executor.shutdown(wait=True)

        self._save_fetched(cache, fetched)
        rows = []
        for day in weekdays:
            key = day.strftime("%Y%m%d")
            value = fetched[day] if day in fetched else cache.get(key)
            if value is not None:
                rows.append((day, float(value)))
        return MacroSeries(rows=rows, failed_dates=sorted(failed))

    def _save_fetched(
        self, cache: dict[str, float | None], fetched: dict[date, float | None]
    ) -> None:
        changed = False
        for day, value in fetched.items():
            # 당일 값은 11시 이후 갱신되므로 캐시하지 않는다.
            # 지난 날의 빈 응답은 휴일로 확정되어 None으로 캐시한다.
            if day >= self.today:
                continue
            cache[day.strftime("%Y%m%d")] = value
            changed = True
        if changed:
            try:
                self._save_cache(cache)
            except OSError as error:
                LOGGER.warning("exim_cache_write_failed error=%s", error)


class InterestRateClient:
    """ECOS StatisticSearch로 국고채·회사채 일별 금리를 기간 단위로 조회한다."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def _request_page(
        self,
        start_row: int,
        end_row: int,
        start: str,
        end: str,
        item_code: str,
    ) -> dict:
        path = "/".join(
            quote(str(part), safe="")
            for part in (
                self.api_key,
                "json",
                "kr",
                start_row,
                end_row,
                ECOS_RATE_TABLE,
                "D",
                start,
                end,
                item_code,
            )
        )
        data = _get_json(f"{ECOS_URL}/{path}", "금리")
        if not isinstance(data, dict):
            raise MacroAPIError("금리 API 응답 형식이 올바르지 않습니다.")
        return data

    def _get_daily_rate(
        self,
        start_date: date,
        end_date: date,
        item_code: str,
        label: str,
    ) -> MacroSeries:
        if start_date > end_date:
            raise ValueError("금리 시작일은 종료일보다 늦을 수 없습니다.")
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
            )
            if "RESULT" in data:
                result = data["RESULT"] or {}
                code = result.get("CODE")
                if code == "INFO-200":
                    raise MacroAPIError(
                        f"{label} API 결과가 비어 있습니다. 기간 또는 "
                        f"통계표({ECOS_RATE_TABLE})와 항목({item_code}) 코드를 확인해 주세요."
                    )
                raise MacroAPIError(
                    f"금리 API 오류: code={code}, message={result.get('MESSAGE')}"
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
