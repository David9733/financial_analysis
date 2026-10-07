from __future__ import annotations

import unittest
from datetime import date

from src.stock_api import StockClient


class FakeStockClient(StockClient):
    def __init__(self):
        super().__init__("test-key")
        self.params = []

    def _request_page(self, params: dict, timeout: int = 30) -> dict:
        self.params.append(params)
        return {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {
                "totalCount": 2,
                "items": {
                    "item": [
                        {"srtnCd": "005930", "basDt": "20260102"},
                        {"srtnCd": "1005930", "basDt": "20260102"},
                    ]
                },
            },
        }

    def _request_market_index_page(self, params: dict, timeout: int = 30) -> dict:
        self.params.append(params)
        return {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {
                "totalCount": 2,
                "items": {
                    "item": [
                        {"idxNm": params["idxNm"], "basDt": "20260102", "clpr": "2500"},
                        {"idxNm": params["idxNm"], "basDt": "20260101", "clpr": "2490"},
                    ]
                },
            },
        }


class StockClientTests(unittest.TestCase):
    def test_end_date_is_converted_to_exclusive_api_parameter(self):
        client = FakeStockClient()
        rows = client.get_stock_prices(
            "005930", date(2026, 1, 1), date(2026, 1, 31)
        )

        self.assertEqual(client.params[0]["beginBasDt"], "20260101")
        self.assertEqual(client.params[0]["endBasDt"], "20260201")
        self.assertEqual(rows, [{"srtnCd": "005930", "basDt": "20260102"}])

    def test_invalid_date_range_is_rejected(self):
        client = FakeStockClient()
        with self.assertRaises(ValueError):
            client.get_stock_prices(
                "005930", date(2026, 2, 1), date(2026, 1, 31)
            )

    def test_market_index_uses_exact_index_name_and_exclusive_end(self):
        client = FakeStockClient()

        rows = client.get_market_index_prices(
            "KOSDAQ", date(2026, 1, 1), date(2026, 1, 31)
        )

        self.assertEqual(client.params[0]["idxNm"], "코스닥")
        self.assertEqual(client.params[0]["beginBasDt"], "20260101")
        self.assertEqual(client.params[0]["endBasDt"], "20260201")
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
