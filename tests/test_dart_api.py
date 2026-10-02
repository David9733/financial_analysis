from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src.dart_api import DartClient


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


if __name__ == "__main__":
    unittest.main()
