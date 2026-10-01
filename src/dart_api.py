"""Open DART API 호출과 기업 고유번호 조회 기능."""

from __future__ import annotations

import io
import json
import os
import re
import unicodedata
import zipfile
from difflib import SequenceMatcher
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree


BASE_URL = "https://opendart.fss.or.kr/api"
ANNUAL_REPORT_CODE = "11011"


class DartAPIError(RuntimeError):
    """DART API 또는 네트워크 요청 실패."""

    def __init__(self, message: str, status: str | None = None) -> None:
        super().__init__(message)
        self.status = status


class CompanyNotFoundError(ValueError):
    """입력한 기업명을 DART 고유번호 목록에서 찾지 못한 경우."""


def load_env_file(path: Path) -> None:
    """외부 패키지 없이 .env의 KEY=VALUE 항목을 환경 변수로 읽는다."""
    if not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_api_key(project_root: Path) -> str:
    """기존 DART_KEY와 일반적인 DART_API_KEY 이름을 모두 지원한다."""
    load_env_file(project_root / ".env")
    api_key = os.getenv("DART_KEY") or os.getenv("DART_API_KEY")
    if not api_key:
        raise DartAPIError(
            "프로젝트 루트의 .env에 DART_KEY 또는 DART_API_KEY를 설정해 주세요."
        )
    return api_key.strip()


def _normalize_company_name(name: str) -> str:
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r"주식회사|\(주\)|㈜", "", name)
    normalized = re.sub(r"[^0-9a-z가-힣]", "", name.casefold())
    # 사용자가 영문 브랜드를 한글 발음으로 입력해도 같은 이름으로 비교한다.
    brand_aliases = (
        ("에이치디현대", "hd현대"),
        ("에스케이", "sk"),
        ("에스오일", "soil"),
        ("에쓰오일", "soil"),
        ("아이비케이", "ibk"),
        ("비엔케이", "bnk"),
        ("디지비", "dgb"),
        ("엘지", "lg"),
        ("케이티", "kt"),
        ("케이비", "kb"),
        ("엔에이치", "nh"),
        ("디비", "db"),
        ("제이비", "jb"),
    )
    for korean, latin in brand_aliases:
        normalized = normalized.replace(korean, latin)
    return normalized


class DartClient:
    """DART API를 호출하고, 저장 경로가 있을 때만 기업코드를 캐시한다."""

    def __init__(self, api_key: str, data_dir: Path | None = None) -> None:
        self.api_key = api_key
        self.data_dir = data_dir
        self.corp_code_cache = data_dir / "corp_codes.json" if data_dir else None
        self._companies_cache: list[dict] | None = None

    def _open(self, endpoint: str, params: dict, timeout: int = 30):
        query = urlencode({"crtfc_key": self.api_key, **params})
        request = Request(
            f"{BASE_URL}/{endpoint}?{query}",
            headers={"User-Agent": "dart-financial-analysis/1.0"},
        )
        try:
            return urlopen(request, timeout=timeout)
        except HTTPError as error:
            raise DartAPIError(
                f"DART HTTP 오류: {error.code} {error.reason}"
            ) from error
        except URLError as error:
            raise DartAPIError(f"DART 네트워크 오류: {error.reason}") from error
        except TimeoutError as error:
            raise DartAPIError("DART API 요청 시간이 초과되었습니다.") from error

    def _request_json(
        self,
        endpoint: str,
        params: dict,
        allow_no_data: bool = False,
    ) -> dict | None:
        with self._open(endpoint, params) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            try:
                data = json.loads(response.read().decode(charset))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise DartAPIError("DART JSON 응답을 해석하지 못했습니다.") from error

        status = data.get("status")
        if status == "000":
            return data
        if allow_no_data and status == "013":
            return None
        raise DartAPIError(
            f"DART API 오류: status={status}, message={data.get('message')}",
            status=status,
        )

    def _download_corp_codes(self) -> list[dict]:
        """DART의 ZIP/XML 고유번호 목록을 내려받는다."""
        with self._open("corpCode.xml", {}, timeout=60) as response:
            payload = response.read()

        buffer = io.BytesIO(payload)
        if not zipfile.is_zipfile(buffer):
            try:
                root = ElementTree.fromstring(payload)
                status = root.findtext("status")
                message = root.findtext("message")
            except ElementTree.ParseError as error:
                raise DartAPIError("DART 고유번호 파일이 올바른 ZIP이 아닙니다.") from error
            raise DartAPIError(
                f"DART API 오류: status={status}, message={message}", status=status
            )

        with zipfile.ZipFile(buffer) as archive:
            xml_names = [name for name in archive.namelist() if name.lower().endswith(".xml")]
            if not xml_names:
                raise DartAPIError("DART 고유번호 ZIP 안에 XML 파일이 없습니다.")
            xml_bytes = archive.read(xml_names[0])

        root = ElementTree.fromstring(xml_bytes)
        companies = []
        for item in root.findall("list"):
            companies.append(
                {
                    "corp_code": (item.findtext("corp_code") or "").strip(),
                    "corp_name": (item.findtext("corp_name") or "").strip(),
                    "corp_eng_name": (item.findtext("corp_eng_name") or "").strip(),
                    "stock_code": (item.findtext("stock_code") or "").strip(),
                    "modify_date": (item.findtext("modify_date") or "").strip(),
                }
            )
        return companies

    def get_corp_codes(self, refresh: bool = False) -> list[dict]:
        """고유번호 목록을 받고, 캐시 경로가 설정된 경우에만 저장한다."""
        if self._companies_cache is not None and not refresh:
            return self._companies_cache
        if self.corp_code_cache and self.corp_code_cache.is_file() and not refresh:
            self._companies_cache = json.loads(
                self.corp_code_cache.read_text(encoding="utf-8")
            )
            return self._companies_cache

        companies = self._download_corp_codes()
        self._companies_cache = companies
        if self.data_dir and self.corp_code_cache:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.corp_code_cache.write_text(
                json.dumps(companies, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        return companies

    def find_company(self, company_name: str) -> dict:
        """정확한 이름, 부분 이름, 오타 순으로 가장 가까운 기업을 찾는다."""
        companies = self.get_corp_codes()
        exact = [item for item in companies if item["corp_name"] == company_name.strip()]
        if len(exact) == 1:
            return exact[0]

        normalized = _normalize_company_name(company_name)
        matches = [
            item
            for item in companies
            if _normalize_company_name(item["corp_name"]) == normalized
        ]
        # 전체 이름을 기억하지 못한 사용자를 위해 부분 이름도 허용한다.
        # 후보가 여러 개면 아래의 상장사 우선 규칙을 적용하고, 그래도
        # 하나로 좁혀지지 않을 때는 후보 목록을 보여준다.
        if not matches and normalized:
            matches = [
                item
                for item in companies
                if normalized in _normalize_company_name(item["corp_name"])
            ]
        if not matches and len(normalized) >= 2:
            scored_matches = []
            for item in companies:
                candidate = _normalize_company_name(item["corp_name"])
                if not candidate:
                    continue
                # 길이가 크게 다른 이름은 유사도가 우연히 높아지는 것을 막는다.
                if abs(len(candidate) - len(normalized)) > max(4, len(normalized) // 2):
                    continue
                score = SequenceMatcher(None, normalized, candidate).ratio()
                if score >= 0.5:
                    scored_matches.append((score, item))

            scored_matches.sort(
                key=lambda pair: (
                    pair[0],
                    bool(pair[1].get("stock_code")),
                    pair[1].get("modify_date", ""),
                ),
                reverse=True,
            )
            if scored_matches:
                best_score = scored_matches[0][0]
                # 자동 선택은 충분히 유사하면서 2위 후보와도 차이가 나는 경우로 제한한다.
                close_matches = [
                    item for score, item in scored_matches if score >= best_score - 0.06
                ]
                if best_score >= 0.72:
                    matches = close_matches
                else:
                    suggestions = ", ".join(
                        item["corp_name"] for _, item in scored_matches[:5]
                    )
                    raise CompanyNotFoundError(
                        f"입력한 기업명 '{company_name}'을(를) 찾을 수 없습니다. "
                        f"비슷한 기업: {suggestions}"
                    )
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise CompanyNotFoundError(
                f"입력한 기업명 '{company_name}'을(를) 찾을 수 없습니다."
            )

        listed = [item for item in matches if item.get("stock_code")]
        if len(listed) == 1:
            return listed[0]
        if listed:
            # 합병·상호 변경 등으로 같은 법인명이 여러 상장 이력에 남아 있으면
            # DART에서 가장 최근에 갱신된 상장 법인을 현재 법인으로 선택한다.
            latest_modify_date = max(item.get("modify_date", "") for item in listed)
            latest_listed = [
                item
                for item in listed
                if item.get("modify_date", "") == latest_modify_date
            ]
            if len(latest_listed) == 1:
                return latest_listed[0]
        names = ", ".join(item["corp_name"] for item in matches[:5])
        raise CompanyNotFoundError(
            f"기업명 '{company_name}' 검색 결과가 여러 개입니다: {names}"
        )

    def get_annual_financials(
        self,
        corp_code: str,
        year: int,
        prefer_consolidated: bool = True,
    ) -> tuple[list[dict], str] | None:
        """연결재무제표(CFS)를 우선하고 없으면 별도재무제표(OFS)를 조회한다."""
        divisions = ("CFS", "OFS") if prefer_consolidated else ("OFS",)
        for fs_div in divisions:
            data = self._request_json(
                "fnlttSinglAcntAll.json",
                {
                    "corp_code": corp_code,
                    "bsns_year": str(year),
                    "reprt_code": ANNUAL_REPORT_CODE,
                    "fs_div": fs_div,
                },
                allow_no_data=True,
            )
            if data is not None:
                return data.get("list", []), fs_div
        return None
