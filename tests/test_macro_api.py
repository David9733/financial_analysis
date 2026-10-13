from __future__ import annotations

import json
import unittest
from datetime import date
from unittest.mock import patch
from urllib.parse import urlparse

from src.macro_api import (
    InterestRateClient,
    MacroAPIError,
)


class FakeResponse:
    def __init__(self, data):
        self.payload = json.dumps(data).encode("utf-8")
        self.headers = self

    def get_content_charset(self):
        return "utf-8"

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class InterestRateClientTests(unittest.TestCase):
    def test_usd_krw_uses_ecos_exchange_table_and_item_code(self):
        requested_parts = []

        def opener(request, timeout=None):
            requested_parts.append(urlparse(request.full_url).path.split("/"))
            return FakeResponse(
                {
                    "StatisticSearch": {
                        "list_total_count": 1,
                        "row": [{"TIME": "20261001", "DATA_VALUE": "1,358.4"}],
                    }
                }
            )

        with patch("src.macro_api.urlopen", opener):
            series = InterestRateClient("key").get_usd_krw(
                date(2026, 10, 1), date(2026, 10, 1)
            )

        self.assertIn("731Y001", requested_parts[0])
        self.assertEqual(requested_parts[0][-1], "0000001")
        self.assertEqual(series.rows, [(date(2026, 10, 1), 1358.4)])

    def test_paginates_and_sorts_rows(self):
        pages = []

        def opener(request, timeout=None):
            parts = urlparse(request.full_url).path.split("/")
            start_row = int(parts[-7])
            pages.append(start_row)
            if start_row == 1:
                rows = [
                    {"TIME": "20261002", "DATA_VALUE": "3.93"},
                    {"TIME": "20261001", "DATA_VALUE": "3.878"},
                ]
            else:
                rows = [{"TIME": "20261005", "DATA_VALUE": "3.9"}]
            return FakeResponse(
                {"StatisticSearch": {"list_total_count": 1001, "row": rows}}
            )

        with patch("src.macro_api.urlopen", opener):
            series = InterestRateClient("key").get_treasury_3y(
                date(2026, 10, 1), date(2026, 10, 5)
            )

        self.assertEqual(pages, [1, 1001])
        self.assertEqual(
            series.rows,
            [
                (date(2026, 10, 1), 3.878),
                (date(2026, 10, 2), 3.93),
                (date(2026, 10, 5), 3.9),
            ],
        )

    def test_empty_result_mentions_codes(self):
        def opener(request, timeout=None):
            return FakeResponse({"RESULT": {"CODE": "INFO-200", "MESSAGE": "no data"}})

        with patch("src.macro_api.urlopen", opener):
            with self.assertRaisesRegex(MacroAPIError, "817Y002"):
                InterestRateClient("key").get_treasury_3y(
                    date(2026, 10, 1), date(2026, 10, 5)
                )

    def test_corporate_aa_minus_uses_verified_ecos_item_code(self):
        requested_item_codes = []

        def opener(request, timeout=None):
            requested_item_codes.append(urlparse(request.full_url).path.split("/")[-1])
            return FakeResponse(
                {
                    "StatisticSearch": {
                        "list_total_count": 1,
                        "row": [{"TIME": "20261001", "DATA_VALUE": "4.12"}],
                    }
                }
            )

        with patch("src.macro_api.urlopen", opener):
            series = InterestRateClient("key").get_corporate_aa_minus_3y(
                date(2026, 10, 1), date(2026, 10, 1)
            )

        self.assertEqual(requested_item_codes, ["010300000"])
        self.assertEqual(series.rows, [(date(2026, 10, 1), 4.12)])

if __name__ == "__main__":
    unittest.main()
