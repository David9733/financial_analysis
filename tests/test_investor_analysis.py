from __future__ import annotations

import unittest

import pandas as pd

from src.investor_analysis import summarize_investor_trading


class InvestorAnalysisTests(unittest.TestCase):
    def test_groups_investors_and_calculates_buy_ratio(self):
        raw = pd.DataFrame(
            {
                "매도": [10, 20, 30, 5, 5],
                "매수": [20, 30, 40, 5, 5],
                "순매수": [10, 10, 10, 0, 0],
            },
            index=["금융투자", "개인", "외국인", "기타법인", "기타외국인"],
        )

        result = summarize_investor_trading(raw, "테스트", "005930")

        self.assertEqual(result["투자자구분"].tolist(), ["기관", "개인", "외국인", "기타"])
        self.assertEqual(result["매수거래량"].tolist(), [20.0, 30.0, 40.0, 10.0])
        self.assertAlmostEqual(result["매수비중"].sum(), 100.0)


if __name__ == "__main__":
    unittest.main()
