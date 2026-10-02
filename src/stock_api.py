"""금융위원회 주식시세 API 호출 기능."""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

if __package__:
    from .dart_api import load_env_file
else:
    from dart_api import load_env_file


BASE_URL = (
    "https://apis.data.go.kr/1160100/"
    "GetStockSecuritiesInfoService_V2/getStockPriceInfo_V2"
)


class StockAPIError(RuntimeError):
    """주식시세 API 또는 응답 처리 실패."""


def get_stock_api_key(project_root: Path) -> str:
    """프로젝트 환경파일에서 공공데이터포털 API 키를 읽는다."""
    load_env_file(project_root / ".env")
    api_key = os.getenv("PUBLIC_STOCK_API_KEY") or os.getenv("STOCK_API_KEY")
    if not api_key:
        raise StockAPIError(
            "프로젝트 루트의 .env에 PUBLIC_STOCK_API_KEY를 설정해 주세요."
        )
    return api_key.strip()


def _xml_error_message(payload: bytes) -> str | None:
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError:
        return None
    code = root.findtext(".//returnReasonCode") or root.findtext(".//resultCode")
    message = root.findtext(".//returnAuthMsg") or root.findtext(".//resultMsg")
    if code or message:
        return f"code={code or 'unknown'}, message={message or 'unknown'}"
    return None


class StockClient:
    """종목코드와 날짜 범위로 일별 주식시세를 조회한다."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def _request_page(self, params: dict, timeout: int = 30) -> dict:
        query = urlencode({"serviceKey": self.api_key, **params})
        request = Request(
            f"{BASE_URL}?{query}",
            headers={"User-Agent": "dart-financial-analysis/2.0"},
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
        except HTTPError as error:
            raise StockAPIError(
                f"주식시세 HTTP 오류: {error.code} {error.reason}"
            ) from error
        except URLError as error:
            raise StockAPIError(f"주식시세 네트워크 오류: {error.reason}") from error
        except TimeoutError as error:
            raise StockAPIError("주식시세 API 요청 시간이 초과되었습니다.") from error

        try:
            data = json.loads(payload.decode(charset))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            xml_error = _xml_error_message(payload)
            if xml_error:
                raise StockAPIError(f"주식시세 API 오류: {xml_error}") from error
            raise StockAPIError("주식시세 API 응답을 해석하지 못했습니다.") from error

        response_data = data.get("response") or {}
        header = response_data.get("header") or {}
        if str(header.get("resultCode", "")) != "00":
            raise StockAPIError(
                "주식시세 API 오류: "
                f"code={header.get('resultCode')}, message={header.get('resultMsg')}"
            )
        return response_data

    def get_stock_prices(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
        page_size: int = 1000,
    ) -> list[dict]:
        """종료일을 포함한 날짜 범위의 일별 시세를 반환한다."""
        stock_code = stock_code.strip()
        if not stock_code:
            return []
        if start_date > end_date:
            raise ValueError("주식시세 시작일은 종료일보다 늦을 수 없습니다.")
        if not 1 <= page_size <= 10000:
            raise ValueError("page_size는 1~10000이어야 합니다.")

        # 명세상 endBasDt는 검색값 미만이므로 종료일 다음 날을 전달한다.
        exclusive_end = end_date + timedelta(days=1)
        page_no = 1
        collected: list[dict] = []
        total_count = None

        while total_count is None or len(collected) < total_count:
            response_data = self._request_page(
                {
                    "numOfRows": str(page_size),
                    "pageNo": str(page_no),
                    "resultType": "json",
                    "beginBasDt": start_date.strftime("%Y%m%d"),
                    "endBasDt": exclusive_end.strftime("%Y%m%d"),
                    "likeSrtnCd": stock_code,
                }
            )
            body = response_data.get("body") or {}
            total_count = int(body.get("totalCount") or 0)
            items_node = body.get("items") or {}
            page_items = items_node.get("item", []) if isinstance(items_node, dict) else []
            if isinstance(page_items, dict):
                page_items = [page_items]
            # likeSrtnCd 조회이므로 혹시 포함 검색된 다른 코드는 제거한다.
            exact_items = [
                item for item in page_items if str(item.get("srtnCd", "")) == stock_code
            ]
            collected.extend(exact_items)
            if not page_items or page_no * page_size >= total_count:
                break
            page_no += 1

        return collected
