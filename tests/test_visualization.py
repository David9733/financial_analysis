from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.macro_analysis import (
    CORPORATE_BOND_COLUMN,
    FX_COLUMN,
    MARKET_INDEX_COLUMN,
    RATE_COLUMN,
    merge_macro_with_prices,
    prepare_macro_series,
)
from src.stock_visualization import (
    _build_rolling_correlation_figure,
    _build_fx_rate_scatter_figure,
    _build_market_correlation_heatmap_figure,
    _create_monthly_volume_chart,
    _outlier_status_text,
    create_rolling_correlation_visualizations,
    create_daily_change_visualizations,
    create_fx_rate_scatter_visualizations,
    create_market_correlation_heatmaps,
    monthly_volume_summary,
)
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

    def test_single_year_omits_uninformative_single_metric_bars(self) -> None:
        data = self.general_company_frame([2025])
        with tempfile.TemporaryDirectory() as directory:
            charts_dir = Path(directory)

            create_single_company_charts(data, charts_dir)

            self.assertFalse((charts_dir / "debt_ratio.png").exists())
            self.assertFalse((charts_dir / "interest_coverage.png").exists())
            self.assertFalse((charts_dir / "receivables_days.png").exists())
            self.assertFalse((charts_dir / "financial_stability_snapshot.png").exists())
            self.assertTrue((charts_dir / "revenue_operating_profit.png").exists())
            self.assertTrue((charts_dir / "operating_margin.png").exists())
            self.assertTrue((charts_dir / "roe_revenue_growth.png").exists())


class MonthlyVolumeTests(unittest.TestCase):
    def tearDown(self) -> None:
        plt.close("all")

    @staticmethod
    def volume_frame(start: str, days: int) -> pd.DataFrame:
        dates = pd.date_range(start, periods=days, freq="B")
        return pd.DataFrame({"기준일": dates, "거래량": [1000 + index for index in range(days)]})

    def test_summary_uses_mean_max_and_trading_days(self) -> None:
        data = pd.DataFrame(
            {
                "기준일": pd.to_datetime(["2026-01-05", "2026-01-06", "2026-02-02"]),
                "거래량": [100, 300, 500],
            }
        )

        summary = monthly_volume_summary(data)

        self.assertEqual(summary["월평균거래량"].tolist(), [200.0, 500.0])
        self.assertEqual(summary["최대일거래량"].tolist(), [300, 500])
        self.assertEqual(summary["거래일수"].tolist(), [2, 1])

    def test_chart_only_for_six_months_or_more(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            long_path = Path(directory) / "long.png"
            short_path = Path(directory) / "short.png"
            _create_monthly_volume_chart(self.volume_frame("2026-01-01", 150), "테스트", long_path)
            _create_monthly_volume_chart(self.volume_frame("2026-01-01", 60), "테스트", short_path)

            self.assertTrue(long_path.exists())
            self.assertFalse(short_path.exists())


class DailyChangeVisualizationTests(unittest.TestCase):
    def tearDown(self) -> None:
        plt.close("all")

    def test_status_text_covers_all_cases(self) -> None:
        self.assertEqual(_outlier_status_text(2, (-1.0, 1.0)), "이상치 2일 (원인 확인 필요)")
        self.assertEqual(_outlier_status_text(0, (-1.0, 1.0)), "이상치 0일")
        self.assertEqual(_outlier_status_text(0, None), "관측일 부족으로 판정 안 함")

    def test_daily_change_chart_is_created_for_short_and_long_data(self) -> None:
        for days in (5, 40):
            closes = [100.0 + index * 0.5 for index in range(days)]
            if days > 30:
                closes[30] = closes[29] * 1.1
            prices = pd.DataFrame(
                {
                    "기업명": "테스트전자",
                    "종목코드": "000001",
                    "기준일": pd.date_range("2026-01-01", periods=days, freq="B"),
                    "종가": closes,
                }
            )
            fx = prepare_macro_series(
                [(day.date(), 1300.0 + index) for index, day in enumerate(prices["기준일"])],
                FX_COLUMN,
            )
            merged = merge_macro_with_prices(prices, fx, None)
            with tempfile.TemporaryDirectory() as directory:
                create_daily_change_visualizations(merged, Path(directory))
                self.assertTrue((Path(directory) / "daily_change_000001.png").exists())


class FXRateScatterVisualizationTests(unittest.TestCase):
    def tearDown(self) -> None:
        plt.close("all")

    @staticmethod
    def macro_frame() -> pd.DataFrame:
        dates = pd.date_range("2026-01-01", periods=15, freq="B")
        prices = pd.DataFrame(
            {
                "기업명": "테스트전자",
                "종목코드": "000001",
                "기준일": dates,
                "종가": [100.0 + index for index in range(len(dates))],
                "시장구분": "KOSPI",
            }
        )
        fx = prepare_macro_series(
            [(day.date(), 1300.0 + index * index) for index, day in enumerate(dates)],
            FX_COLUMN,
        )
        rate = prepare_macro_series(
            [
                (day.date(), 3.0 + index * 0.01 + (index % 3) * 0.002)
                for index, day in enumerate(dates)
            ],
            RATE_COLUMN,
        )
        corporate = prepare_macro_series(
            [
                (day.date(), 4.1 + index * 0.014 + (index % 4) * 0.003)
                for index, day in enumerate(dates)
            ],
            CORPORATE_BOND_COLUMN,
        )
        market_index = prepare_macro_series(
            [
                (day.date(), 2500.0 + index * 2 + (index % 5) * 1.3)
                for index, day in enumerate(dates)
            ],
            MARKET_INDEX_COLUMN,
        )
        return merge_macro_with_prices(
            prices,
            fx,
            rate,
            corporate,
            market_indices={"KOSPI": market_index},
        )

    def test_scatter_has_korean_labels_dashed_trend_and_slope(self):
        built = _build_fx_rate_scatter_figure(self.macro_frame(), "테스트전자")

        self.assertIsNotNone(built)
        figure, slope = built
        axis = figure.axes[0]
        self.assertEqual(axis.get_xlabel(), "환율 변화율(%)")
        self.assertEqual(axis.get_ylabel(), "금리 변화폭(bp)")
        self.assertIn("환율 변화율과 금리 변화폭 산점도", axis.get_title())
        self.assertTrue(any(line.get_linestyle() == "--" for line in axis.lines))
        self.assertTrue(any("추세선 기울기" in text.get_text() for text in axis.texts))
        self.assertIsInstance(slope, float)

    def test_scatter_png_is_created(self):
        with tempfile.TemporaryDirectory() as directory:
            create_fx_rate_scatter_visualizations(self.macro_frame(), Path(directory))

            self.assertTrue((Path(directory) / "fx_rate_scatter_000001.png").exists())


class MarketCorrelationHeatmapTests(unittest.TestCase):
    def tearDown(self) -> None:
        plt.close("all")

    def test_heatmap_uses_four_daily_change_series_and_pearson_corr(self):
        data = FXRateScatterVisualizationTests.macro_frame()

        built = _build_market_correlation_heatmap_figure(data, "테스트전자")

        self.assertIsNotNone(built)
        figure, correlation, observations = built
        axis = figure.axes[0]
        self.assertEqual(correlation.shape, (5, 5))
        self.assertTrue(correlation.equals(correlation.T))
        self.assertGreaterEqual(observations, 10)
        self.assertIn(
            "주가 수익률·시장지수 수익률·환율 변화율·금리 변화폭·신용 스프레드 변화폭 상관관계 히트맵",
            axis.get_title(),
        )
        self.assertEqual(axis.images[0].get_clim(), (-1.0, 1.0))
        self.assertTrue(axis.images[0].get_array().mask.diagonal().all())
        self.assertEqual(len(axis.texts), 20)

    def test_heatmap_png_is_created(self):
        data = FXRateScatterVisualizationTests.macro_frame()
        with tempfile.TemporaryDirectory() as directory:
            create_market_correlation_heatmaps(data, Path(directory))

            self.assertTrue(
                (Path(directory) / "market_correlation_heatmap_000001.png").exists()
            )


class RollingCorrelationVisualizationTests(unittest.TestCase):
    def tearDown(self) -> None:
        plt.close("all")

    @staticmethod
    def three_month_macro_frame() -> pd.DataFrame:
        dates = pd.date_range("2026-07-01", periods=65, freq="B")
        positions = np.arange(len(dates), dtype=float)
        stock_returns = 0.2 + 0.6 * np.sin(positions / 4)
        fx_changes = 0.08 * np.sin(positions / 5) + 0.04 * np.cos(positions / 3)
        rate_changes = 0.008 * np.cos(positions / 6) + 0.003 * np.sin(positions / 2)
        closes = 100 * np.cumprod(1 + stock_returns / 100)
        fx_values = 1350 * np.cumprod(1 + fx_changes / 100)
        rate_values = 3.0 + np.cumsum(rate_changes)
        corporate_values = rate_values + 1.1 + np.cumsum(
            0.004 * np.sin(positions / 3)
        )
        prices = pd.DataFrame(
            {
                "기업명": "테스트전자",
                "종목코드": "000001",
                "기준일": dates,
                "종가": closes,
                "시장구분": "KOSDAQ",
            }
        )
        fx = prepare_macro_series(
            [(day.date(), value) for day, value in zip(dates, fx_values)],
            FX_COLUMN,
        )
        rate = prepare_macro_series(
            [(day.date(), value) for day, value in zip(dates, rate_values)],
            RATE_COLUMN,
        )
        corporate = prepare_macro_series(
            [(day.date(), value) for day, value in zip(dates, corporate_values)],
            CORPORATE_BOND_COLUMN,
        )
        market_values = 900 * np.cumprod(
            1 + (0.12 * np.cos(positions / 5)) / 100
        )
        market_index = prepare_macro_series(
            [(day.date(), value) for day, value in zip(dates, market_values)],
            MARKET_INDEX_COLUMN,
        )
        return merge_macro_with_prices(
            prices,
            fx,
            rate,
            corporate,
            market_indices={"KOSDAQ": market_index},
        )

    def test_four_company_factor_panels_for_all_periods(self):
        expected = {
            "1m": ("1개월", 10, 10),
            "3m": ("3개월", 20, 20),
            "6m": ("6개월", 60, 60),
            "1y": ("1년", 60, 60),
            "3y": ("3년", 60, 60),
        }
        for period, (label, window, minimum) in expected.items():
            with self.subTest(period=period):
                built = _build_rolling_correlation_figure(
                    self.three_month_macro_frame(), "테스트전자", period
                )

                self.assertIsNotNone(built)
                figure, rolling = built
                title = figure._suptitle.get_text()
                self.assertEqual(len(figure.axes), 4)
                self.assertNotIn("환율 변화율-금리 변화폭", rolling.columns)
                self.assertIn(f"{label} 조회 · {window}거래일 이동상관", title)
                self.assertIn(f"유효 관측 {minimum}일 이상", title)
                self.assertTrue(
                    all(axis.get_ylim() == (-1.05, 1.05) for axis in figure.axes)
                )
                self.assertTrue(
                    all(
                        rolling[column].notna().any()
                        for column in rolling.columns[1:]
                    )
                )
                for axis in figure.axes:
                    horizontal_levels = {
                        float(line.get_ydata()[0])
                        for line in axis.lines[1:]
                        if len(line.get_ydata()) >= 2
                        and np.allclose(line.get_ydata(), line.get_ydata()[0])
                    }
                    self.assertTrue(
                        {-0.7, -0.3, 0.0, 0.3, 0.7}.issubset(
                            horizontal_levels
                        )
                    )
                plt.close(figure)

    def test_optional_market_and_spread_panels_can_be_omitted(self):
        data = self.three_month_macro_frame().drop(
            columns=[
                MARKET_INDEX_COLUMN,
                "시장지수수익률(%)",
                "시장지수보간",
                "시장지수이상치",
                "회사채3년AA-",
                "회사채금리보간",
                "신용스프레드(bp)",
                "신용스프레드보간",
                "신용스프레드변화폭(bp)",
                "신용스프레드이상치",
            ]
        )

        built = _build_rolling_correlation_figure(data, "테스트전자", "3m")

        self.assertIsNotNone(built)
        figure, rolling = built
        self.assertEqual(len(figure.axes), 2)
        self.assertEqual(
            list(rolling.columns),
            ["기준일", "주가 수익률-환율 변화율", "주가 수익률-금리 변화폭"],
        )
        plt.close(figure)

    def test_rolling_correlation_png_is_created_for_all_periods(self):
        for period in ("1m", "3m", "6m", "1y", "3y"):
            with (
                self.subTest(period=period),
                tempfile.TemporaryDirectory() as directory,
            ):
                create_rolling_correlation_visualizations(
                    self.three_month_macro_frame(), Path(directory), period
                )

                self.assertTrue(
                    (
                        Path(directory)
                        / f"rolling_correlation_{period}_000001.png"
                    ).exists()
                )


if __name__ == "__main__":
    unittest.main()
