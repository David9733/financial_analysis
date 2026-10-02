from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from src.visualization import _line_chart, create_single_company_charts


class SingleCompanyVisualizationTests(unittest.TestCase):
    def tearDown(self) -> None:
        plt.close("all")

    @staticmethod
    def general_company_frame(years: list[int]) -> pd.DataFrame:
        rows = []
        for index, year in enumerate(years):
            rows.append(
                {
                    "기업명": "테스트전자",
                    "분석유형": "일반기업",
                    "연도": year,
                    "매출": 1000 + index * 100,
                    "영업이익": 100 + index * 20,
                    "영업이익률": 10 + index,
                    "부채비율": 40 - index,
                    "이자보상배율": 8 + index,
                    "ROE": 12 + index,
                    "ROA": 7 + index,
                    "매출성장": 5 + index,
                    "영업이익성장": 6 + index,
                    "당기순이익성장": 4 + index,
                    "매출채권회전일수": 30 - index,
                }
            )
        return pd.DataFrame(rows)

    def test_single_year_trend_is_rendered_as_labeled_bar(self) -> None:
        data = self.general_company_frame([2025])

        figure = _line_chart(data, ["ROE", "ROA"], "수익성", "%")
        axis = figure.axes[0]

        self.assertGreater(len(axis.containers), 0)
        self.assertTrue(any("단일 연도 조회" in text.get_text() for text in axis.texts))
        self.assertFalse(any(line.get_label() in {"ROE", "ROA"} for line in axis.lines))

    def test_multiple_year_trend_remains_a_line_chart(self) -> None:
        data = self.general_company_frame([2024, 2025])

        figure = _line_chart(data, ["ROE", "ROA"], "수익성", "%")

        self.assertEqual(
            {line.get_label() for line in figure.axes[0].lines} & {"ROE", "ROA"},
            {"ROE", "ROA"},
        )

    def test_general_company_charts_mix_profitability_lines_and_metric_bars(self) -> None:
        data = self.general_company_frame([2024, 2025])
        with tempfile.TemporaryDirectory() as directory:
            figures = create_single_company_charts(data, Path(directory))

            self.assertTrue(any(line.get_label() == "ROE" for line in figures[1].axes[0].lines))
            self.assertGreater(len(figures[2].axes[0].containers), 0)
            self.assertTrue((Path(directory) / "operating_margin.png").exists())
            self.assertTrue((Path(directory) / "debt_ratio.png").exists())


if __name__ == "__main__":
    unittest.main()
