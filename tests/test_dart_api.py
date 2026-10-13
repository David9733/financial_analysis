from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src.dart_api import CompanyNotFoundError, DartClient


class DartClientCacheTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
