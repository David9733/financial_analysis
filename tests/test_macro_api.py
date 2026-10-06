from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from src.macro_api import (
    ExchangeRateClient,
    InterestRateClient,
    MacroAPIError,
    MacroQuotaError,
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


def exim_day(usd_rate: str) -> list[dict]:
    return [
        {"result": 1, "cur_unit": "JPY(100)", "deal_bas_r": "912.33"},
        {"result": 1, "cur_unit": "USD", "deal_bas_r": usd_rate},
    ]


class ExchangeRateClientTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_path = Path(self.temp_dir.name) / "exim.json"
        self.requested_dates: list[str] = []

    def tearDown(self):
        self.temp_dir.cleanup()

    def fake_urlopen(self, responses: dict[str, object]):
        def opener(request, timeout=None):
            query = parse_qs(urlparse(request.full_url).query)
            searchdate = query["searchdate"][0]
            self.requested_dates.append(searchdate)
            response = responses.get(searchdate, [])
            if isinstance(response, Exception):
                raise response
            return FakeResponse(response)

        return opener

    def client(self) -> ExchangeRateClient:
        return ExchangeRateClient("key", cache_path=self.cache_path, today=date(2026, 10, 6))

    def test_parses_usd_comma_rate_and_skips_weekend_and_holiday(self):
        responses = {
            "20261001": exim_day("1,358.4"),
            "20261002": exim_day("1,361.0"),
            "20261005": [],  # 공휴일은 빈 배열
        }
        with patch("src.macro_api.urlopen", self.fake_urlopen(responses)):
            series = self.client().get_usd_krw(date(2026, 10, 1), date(2026, 10, 5))

        self.assertEqual(
            series.rows,
            [(date(2026, 10, 1), 1358.4), (date(2026, 10, 2), 1361.0)],
        )
        # 10/3(토), 10/4(일)는 호출하지 않는다.
        self.assertEqual(sorted(self.requested_dates), ["20261001", "20261002", "20261005"])
        self.assertEqual(series.failed_dates, [])

    def test_cache_hit_avoids_second_request(self):
        responses = {"20261001": exim_day("1,358.4"), "20261002": []}
        with patch("src.macro_api.urlopen", self.fake_urlopen(responses)):
            self.client().get_usd_krw(date(2026, 10, 1), date(2026, 10, 2))
            self.requested_dates.clear()
            series = self.client().get_usd_krw(date(2026, 10, 1), date(2026, 10, 2))

        self.assertEqual(self.requested_dates, [])
        self.assertEqual(series.rows, [(date(2026, 10, 1), 1358.4)])

    def test_today_is_not_cached(self):
        responses = {"20261006": []}  # 11시 이전 당일은 빈 응답
        with patch("src.macro_api.urlopen", self.fake_urlopen(responses)):
            self.client().get_usd_krw(date(2026, 10, 6), date(2026, 10, 6))
            self.client().get_usd_krw(date(2026, 10, 6), date(2026, 10, 6))

        self.assertEqual(self.requested_dates, ["20261006", "20261006"])

    @patch("src.macro_api.time.sleep")
    def test_single_day_failure_is_reported_not_raised(self, _sleep):
        responses = {
            "20261001": exim_day("1,358.4"),
            "20261002": MacroAPIError("timeout"),
        }
        with patch("src.macro_api.urlopen", self.fake_urlopen(responses)):
            series = self.client().get_usd_krw(date(2026, 10, 1), date(2026, 10, 2))

        self.assertEqual(series.rows, [(date(2026, 10, 1), 1358.4)])
        self.assertEqual(series.failed_dates, [date(2026, 10, 2)])
        self.assertEqual(self.requested_dates.count("20261002"), 3)

    @patch("src.macro_api.time.sleep")
    def test_transient_failure_is_retried(self, _sleep):
        attempts = []

        def opener(request, timeout=None):
            attempts.append(1)
            if len(attempts) == 1:
                raise MacroAPIError("connection reset")
            return FakeResponse(exim_day("1,359.6"))

        with patch("src.macro_api.urlopen", opener):
            series = self.client().get_usd_krw(date(2026, 10, 2), date(2026, 10, 2))

        self.assertEqual(series.rows, [(date(2026, 10, 2), 1359.6)])
        self.assertEqual(series.failed_dates, [])

    def test_quota_exceeded_raises(self):
        responses = {"20261001": [{"result": 4}]}
        with patch("src.macro_api.urlopen", self.fake_urlopen(responses)):
            with self.assertRaises(MacroQuotaError):
                self.client().get_usd_krw(date(2026, 10, 1), date(2026, 10, 1))


class InterestRateClientTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
