from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from src.dart_api import CompanyNotFoundError, DartClient


class DartClientCacheTests(unittest.TestCase):
    def test_bundled_zip_cache_avoids_network_download(self) -> None:
        companies = [
            {
                "corp_code": "00126380",
                "corp_name": "삼성전자",
                "stock_code": "005930",
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundled_cache = root / "corp_codes.zip"
            with zipfile.ZipFile(bundled_cache, "w") as archive:
                archive.writestr(
                    "corp_codes.json",
                    json.dumps(companies, ensure_ascii=False),
                )
            client = DartClient(
                "key",
                root / "runtime-cache",
                bundled_cache=bundled_cache,
            )

            with patch.object(client, "_download_corp_codes") as download:
                self.assertEqual(client.get_corp_codes(), companies)

            download.assert_not_called()

    def test_uses_fresh_corp_code_cache(self) -> None:
        companies = [{"corp_code": "001", "corp_name": "테스트전자"}]
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "corp_codes.json"
            cache_path.write_text(json.dumps(companies), encoding="utf-8")
            client = DartClient("key", Path(directory), cache_ttl_seconds=3600)

            with patch.object(client, "_download_corp_codes") as download:
                self.assertEqual(client.get_corp_codes(), companies)

            download.assert_not_called()

    def test_refreshes_stale_corp_code_cache(self) -> None:
        old_companies = [{"corp_code": "001", "corp_name": "이전기업"}]
        new_companies = [{"corp_code": "002", "corp_name": "신규기업"}]
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "corp_codes.json"
            cache_path.write_text(json.dumps(old_companies), encoding="utf-8")
            stale_time = time.time() - 7200
            os.utime(cache_path, (stale_time, stale_time))
            client = DartClient("key", Path(directory), cache_ttl_seconds=3600)

            with patch.object(
                client, "_download_corp_codes", return_value=new_companies
            ) as download:
                self.assertEqual(client.get_corp_codes(), new_companies)

            download.assert_called_once_with()
            self.assertEqual(
                json.loads(cache_path.read_text(encoding="utf-8")), new_companies
            )


class DartClientCompanySearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = DartClient("key")
        self.client._companies_cache = [
            {
                "corp_code": "01258507",
                "corp_name": "롯데웰푸드",
                "stock_code": "280360",
                "modify_date": "20260323",
            },
            {
                "corp_code": "00120508",
                "corp_name": "롯데푸드",
                "stock_code": "002270",
                "modify_date": "20240628",
            },
            {
                "corp_code": "00126380",
                "corp_name": "삼성전자",
                "stock_code": "005930",
                "modify_date": "20260101",
            },
        ]

    def test_similar_exact_company_names_resolve_to_distinct_corp_codes(self) -> None:
        wellfood = self.client.find_company("롯데웰푸드")
        food = self.client.find_company("롯데푸드")

        self.assertEqual(wellfood["corp_code"], "01258507")
        self.assertEqual(food["corp_code"], "00120508")

    def test_normalized_exact_name_is_supported(self) -> None:
        company = self.client.find_company("(주) 삼성전자")

        self.assertEqual(company["corp_code"], "00126380")

    def test_typo_is_not_silently_resolved_to_similar_company(self) -> None:
        with self.assertRaisesRegex(
            CompanyNotFoundError, "비슷한 기업:.*롯데웰푸드"
        ):
            self.client.find_company("롯데웰프드")

    def test_common_abbreviation_resolves_to_official_company(self) -> None:
        self.client._companies_cache += [
            {"corp_code": "00164742", "corp_name": "현대자동차", "stock_code": "005380"},
            # "현대차"를 포함한 유일한 상장사라 약칭 표가 없으면 부분 일치로 선택된다.
            {"corp_code": "00137997", "corp_name": "현대차증권", "stock_code": "001500"},
            {"corp_code": "01515323", "corp_name": "LG에너지솔루션", "stock_code": "373220"},
        ]

        self.assertEqual(self.client.find_company("현대차")["corp_name"], "현대자동차")
        self.assertEqual(self.client.find_company("현대차증권")["corp_name"], "현대차증권")
        for name in ("LG엔솔", "엘지엔솔", "lg 엔솔"):
            with self.subTest(name):
                self.assertEqual(
                    self.client.find_company(name)["corp_name"], "LG에너지솔루션"
                )

    def test_warns_when_analyzed_company_name_differs_from_input(self) -> None:
        from src.main import name_resolution_warnings

        warnings = name_resolution_warnings(
            [
                {"requested_name": "현대차", "corp_name": "현대자동차"},
                {"requested_name": "sk하이닉스", "corp_name": "SK하이닉스"},
                {"requested_name": "삼성전자", "corp_name": "삼성전자"},
            ]
        )

        self.assertEqual(
            warnings, ["'현대차' 입력을 DART 기업명 '현대자동차'(으)로 분석했습니다."]
        )


if __name__ == "__main__":
    unittest.main()
