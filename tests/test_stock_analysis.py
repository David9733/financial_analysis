from __future__ import annotations

import unittest

import pandas as pd

from src.stock_analysis import (
    add_bollinger_bands,
    add_moving_averages,
    normalize_for_comparison,
    prepare_stock_prices,
    summarize_stock_prices,
)


def row(day: str, close: int, code: str = "005930") -> dict:
    return {
        "basDt": day,
        "srtnCd": code,
        "mrktCtg": "KOSPI",
        "clpr": str(close),
        "mkp": str(close - 100),
        "hipr": str(close + 200),
        "lopr": str(close - 200),
        "trqu": "1000",
        "trPrc": "1000000",
        "lstgStCnt": "100000",
        "mrktTotAmt": str(close * 100000),
        "fltRt": "1.0",
    }


class StockAnalysisTests(unittest.TestCase):
    def test_bollinger_bands_use_mean_and_two_standard_deviations(self):
        prices = prepare_stock_prices(
            [row(f"2026010{day}", day * 10) for day in range(1, 6)],
            "테스트",
            "005930",
        )

        result = add_bollinger_bands(prices, window=5, std_multiplier=2)

        self.assertTrue(result["BB중간"].iloc[:4].isna().all())
        self.assertAlmostEqual(result["BB중간"].iloc[-1], 30.0)
        self.assertAlmostEqual(result["BB상한"].iloc[-1], 58.2842712475)
        self.assertAlmostEqual(result["BB하한"].iloc[-1], 1.7157287525)

    def test_moving_averages_use_trading_day_closes(self):
        prices = prepare_stock_prices(
            [row(f"2026010{day}", day * 10) for day in range(1, 6)],
            "테스트",
            "005930",
        )

        result = add_moving_averages(prices, windows=(3, 5))

        self.assertTrue(result["이동평균3일"].iloc[:2].isna().all())
        self.assertAlmostEqual(result["이동평균3일"].iloc[-1], 40.0)
        self.assertAlmostEqual(result["이동평균5일"].iloc[-1], 30.0)

    def test_prepare_sorts_converts_and_normalizes_prices(self):
        prices = prepare_stock_prices(
            [row("20260103", 110), row("20260102", 100)], "테스트", "005930"
        )

        self.assertEqual(prices["기준일"].dt.strftime("%Y%m%d").tolist(), ["20260102", "20260103"])
        self.assertEqual(prices["종가"].tolist(), [100, 110])
        self.assertAlmostEqual(prices.loc[0, "정규화주가"], 100.0)
        self.assertAlmostEqual(prices.loc[1, "정규화주가"], 110.0)

    def test_summary_uses_latest_close_and_period_range(self):
        prices = prepare_stock_prices(
            [row("20260102", 100), row("20260103", 120)], "테스트", "005930"
        )
        summary = summarize_stock_prices(prices).iloc[0]

        self.assertEqual(summary["최근종가"], 120)
        self.assertAlmostEqual(summary["기간수익률"], 20.0)
        self.assertEqual(summary["기간최고가"], 320)
        self.assertEqual(summary["기간최저가"], -100)

    def test_comparison_uses_first_common_trading_day(self):
        first = prepare_stock_prices(
            [row("20260102", 100), row("20260103", 120)], "A", "000001"
        )
        second = prepare_stock_prices(
            [row("20260103", 200), row("20260104", 220)], "B", "000002"
        )
        comparison = normalize_for_comparison(pd.concat([first, second], ignore_index=True))

        base_rows = comparison[comparison["기준일"] == pd.Timestamp("2026-01-03")]
        self.assertEqual(base_rows["정규화주가"].tolist(), [100.0, 100.0])
        self.assertNotIn(pd.Timestamp("2026-01-02"), set(comparison["기준일"]))


if __name__ == "__main__":
    unittest.main()
