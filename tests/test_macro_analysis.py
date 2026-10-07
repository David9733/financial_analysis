from __future__ import annotations

import unittest
from datetime import date

import numpy as np
import pandas as pd

from src.data_quality import QualityLog
from src.kpi_analysis import _macro_kpis
from src.macro_analysis import (
    CORPORATE_BOND_COLUMN,
    CREDIT_SPREAD_CHANGE_BP_COLUMN,
    CREDIT_SPREAD_COLUMN,
    CREDIT_SPREAD_FILLED_COLUMN,
    FX_CHANGE_COLUMN,
    FX_COLUMN,
    FX_FILLED_COLUMN,
    FX_OUTLIER_COLUMN,
    MARKET_INDEX_COLUMN,
    MARKET_INDEX_NAME_COLUMN,
    MARKET_INDEX_RETURN_COLUMN,
    PRICE_CHANGE_COLUMN,
    PRICE_OUTLIER_COLUMN,
    RATE_CHANGE_BP_COLUMN,
    RATE_CHANGE_PP_COLUMN,
    RATE_COLUMN,
    RATE_FILLED_COLUMN,
    RATE_OUTLIER_COLUMN,
    merge_macro_with_prices,
    prepare_macro_series,
)


def price_frame(dates: list[str], closes: list[float] | None = None) -> pd.DataFrame:
    closes = closes or [100.0 + index for index in range(len(dates))]
    return pd.DataFrame(
        {
            "기업명": "테스트전자",
            "종목코드": "000001",
            "기준일": pd.to_datetime(dates),
            "종가": closes,
        }
    )


class MergeMacroTests(unittest.TestCase):
    def test_user_example_uses_stock_calendar_and_ffills_only_gaps(self):
        # 1일차 정상, 2일차 환율 수집 실패, 3일차 국내외 휴일(주가 없음),
        # 4일차 해외만 열림(주가 없음), 5일차 해외 휴일.
        prices = price_frame(["2026-03-02", "2026-03-03", "2026-03-06"])
        fx = prepare_macro_series(
            [
                (date(2026, 3, 2), 1300.0),
                (date(2026, 3, 5), 1310.0),  # 4일차: 주가 없는 날의 관측값
            ],
            FX_COLUMN,
        )
        rate = prepare_macro_series(
            [
                (date(2026, 3, 2), 3.0),
                (date(2026, 3, 3), 3.1),
                (date(2026, 3, 5), 3.2),
            ],
            RATE_COLUMN,
        )

        merged = merge_macro_with_prices(prices, fx, rate)

        self.assertEqual(len(merged), len(prices))
        self.assertTrue(merged["기준일"].is_monotonic_increasing)
        self.assertEqual(
            merged["기준일"].dt.strftime("%Y-%m-%d").tolist(),
            ["2026-03-02", "2026-03-03", "2026-03-06"],
        )
        self.assertEqual(merged[FX_COLUMN].tolist(), [1300.0, 1300.0, 1310.0])
        self.assertEqual(merged[FX_FILLED_COLUMN].tolist(), [False, True, True])
        self.assertEqual(merged[RATE_COLUMN].tolist(), [3.0, 3.1, 3.2])
        self.assertEqual(merged[RATE_FILLED_COLUMN].tolist(), [False, False, True])

    def test_lookback_value_seeds_first_trading_day(self):
        prices = price_frame(["2026-03-03", "2026-03-04"])
        fx = prepare_macro_series(
            [(date(2026, 2, 27), 1290.0), (date(2026, 3, 4), 1295.0)], FX_COLUMN
        )

        merged = merge_macro_with_prices(prices, fx, None)

        self.assertEqual(merged[FX_COLUMN].tolist(), [1290.0, 1295.0])
        self.assertEqual(merged[FX_FILLED_COLUMN].tolist(), [True, False])
        self.assertTrue(merged[RATE_COLUMN].isna().all())

    def test_stale_values_beyond_limit_are_not_filled(self):
        prices = price_frame(["2026-03-02", "2026-03-20"])
        fx = prepare_macro_series([(date(2026, 3, 2), 1300.0)], FX_COLUMN)

        merged = merge_macro_with_prices(prices, fx, None)

        self.assertEqual(merged[FX_COLUMN].iloc[0], 1300.0)
        self.assertTrue(pd.isna(merged[FX_COLUMN].iloc[1]))
        self.assertFalse(merged[FX_FILLED_COLUMN].iloc[1])

    def test_unsorted_and_duplicate_inputs_are_ordered(self):
        prices = price_frame(["2026-03-03", "2026-03-02"], [101.0, 100.0])
        fx = prepare_macro_series(
            [
                (date(2026, 3, 3), 1301.0),
                (date(2026, 3, 2), 1299.0),
                (date(2026, 3, 2), 1300.0),
            ],
            FX_COLUMN,
        )

        merged = merge_macro_with_prices(prices, fx, None)

        self.assertEqual(merged["종가"].tolist(), [100.0, 101.0])
        self.assertEqual(merged[FX_COLUMN].tolist(), [1300.0, 1301.0])

    def test_multiple_companies_keep_their_own_calendars(self):
        first = price_frame(["2026-03-02", "2026-03-03"])
        second = price_frame(["2026-03-03"]).assign(기업명="둘째", 종목코드="000002")
        prices = pd.concat([first, second], ignore_index=True)
        fx = prepare_macro_series(
            [(date(2026, 3, 2), 1300.0), (date(2026, 3, 3), 1301.0)], FX_COLUMN
        )

        merged = merge_macro_with_prices(prices, fx, None)

        self.assertEqual(len(merged), 3)
        self.assertEqual(
            merged.groupby("기업명").size().to_dict(), {"둘째": 1, "테스트전자": 2}
        )

    def test_each_company_is_mapped_to_its_own_market_index(self):
        dates = ["2026-03-02", "2026-03-03", "2026-03-04"]
        kospi_company = price_frame(dates, [100.0, 101.0, 102.0]).assign(
            시장구분="KOSPI"
        )
        kosdaq_company = price_frame(dates, [50.0, 51.0, 50.5]).assign(
            기업명="코스닥기업", 종목코드="000002", 시장구분="KOSDAQ"
        )
        kospi = prepare_macro_series(
            [
                (date(2026, 3, 2), 2500.0),
                (date(2026, 3, 3), 2525.0),
                (date(2026, 3, 4), 2550.0),
            ],
            MARKET_INDEX_COLUMN,
        )
        kosdaq = prepare_macro_series(
            [
                (date(2026, 3, 2), 800.0),
                (date(2026, 3, 3), 792.0),
                (date(2026, 3, 4), 808.0),
            ],
            MARKET_INDEX_COLUMN,
        )

        merged = merge_macro_with_prices(
            pd.concat([kospi_company, kosdaq_company], ignore_index=True),
            market_indices={"KOSPI": kospi, "KOSDAQ": kosdaq},
        )

        first = merged[merged["기업명"] == "테스트전자"]
        second = merged[merged["기업명"] == "코스닥기업"]
        self.assertEqual(first[MARKET_INDEX_NAME_COLUMN].unique().tolist(), ["KOSPI"])
        self.assertEqual(second[MARKET_INDEX_NAME_COLUMN].unique().tolist(), ["KOSDAQ"])
        self.assertEqual(first[MARKET_INDEX_COLUMN].tolist(), [2500.0, 2525.0, 2550.0])
        self.assertEqual(second[MARKET_INDEX_COLUMN].tolist(), [800.0, 792.0, 808.0])
        self.assertEqual(first[MARKET_INDEX_RETURN_COLUMN].iloc[1], 1.0)
        self.assertEqual(second[MARKET_INDEX_RETURN_COLUMN].iloc[1], -1.0)


class DailyChangeColumnTests(unittest.TestCase):
    def test_close_fx_rate_changes_use_movement_not_level(self):
        prices = price_frame(["2026-03-02", "2026-03-03", "2026-03-04"], [100.0, 105.0, 102.9])
        fx = prepare_macro_series(
            [(date(2026, 3, 2), 1385.2), (date(2026, 3, 3), 1399.052), (date(2026, 3, 4), 1399.052)],
            FX_COLUMN,
        )
        rate = prepare_macro_series(
            [(date(2026, 3, 2), 2.85), (date(2026, 3, 3), 2.90), (date(2026, 3, 4), 2.88)],
            RATE_COLUMN,
        )

        merged = merge_macro_with_prices(prices, fx, rate)

        # 종가 등락률 = 오늘 ÷ 어제 − 1, 첫날은 어제가 없어 빈 값
        self.assertTrue(pd.isna(merged[PRICE_CHANGE_COLUMN].iloc[0]))
        self.assertEqual(merged[PRICE_CHANGE_COLUMN].iloc[1:].tolist(), [5.0, -2.0])
        # 환율 변화율 = 오늘 ÷ 어제 − 1
        self.assertEqual(merged[FX_CHANGE_COLUMN].iloc[1], 1.0)
        # 금리는 '%의 %'(약 1.75%)가 아니라 변화폭: 2.85% → 2.90% = +0.05%p = +5bp
        self.assertEqual(merged[RATE_CHANGE_PP_COLUMN].iloc[1], 0.05)
        self.assertEqual(merged[RATE_CHANGE_BP_COLUMN].iloc[1], 5.0)
        self.assertEqual(merged[RATE_CHANGE_BP_COLUMN].iloc[2], -2.0)

    def test_changes_restart_for_each_company(self):
        first = price_frame(["2026-03-02", "2026-03-03"], [100.0, 110.0])
        second = price_frame(["2026-03-02", "2026-03-03"], [50.0, 51.0]).assign(
            기업명="둘째", 종목코드="000002"
        )

        merged = merge_macro_with_prices(pd.concat([first, second], ignore_index=True))

        second_rows = merged[merged["기업명"] == "둘째"]
        self.assertTrue(pd.isna(second_rows[PRICE_CHANGE_COLUMN].iloc[0]))
        self.assertEqual(second_rows[PRICE_CHANGE_COLUMN].iloc[1], 2.0)

    def test_credit_spread_is_corporate_minus_treasury_and_changes_in_bp(self):
        dates = ["2026-03-02", "2026-03-03", "2026-03-04"]
        prices = price_frame(dates)
        rate = prepare_macro_series(
            [
                (date(2026, 3, 2), 3.00),
                (date(2026, 3, 3), 3.05),
                (date(2026, 3, 4), 3.02),
            ],
            RATE_COLUMN,
        )
        corporate = prepare_macro_series(
            [
                (date(2026, 3, 2), 4.20),
                (date(2026, 3, 3), 4.30),
                (date(2026, 3, 4), 4.22),
            ],
            CORPORATE_BOND_COLUMN,
        )

        merged = merge_macro_with_prices(
            prices, rate=rate, corporate_bond=corporate
        )

        self.assertEqual(merged[CREDIT_SPREAD_COLUMN].tolist(), [120.0, 125.0, 120.0])
        self.assertTrue(pd.isna(merged[CREDIT_SPREAD_CHANGE_BP_COLUMN].iloc[0]))
        self.assertEqual(
            merged[CREDIT_SPREAD_CHANGE_BP_COLUMN].iloc[1:].tolist(),
            [5.0, -5.0],
        )
        self.assertEqual(merged[CREDIT_SPREAD_FILLED_COLUMN].tolist(), [False] * 3)


class MissingAndOutlierTests(unittest.TestCase):
    def test_first_rows_without_seed_are_backfilled_and_logged(self):
        prices = price_frame(["2026-03-02", "2026-03-03", "2026-03-04"])
        fx = prepare_macro_series([(date(2026, 3, 4), 1300.0)], FX_COLUMN)
        log = QualityLog()

        merged = merge_macro_with_prices(prices, fx, None, log=log)

        self.assertEqual(len(merged), len(prices))
        self.assertEqual(merged[FX_COLUMN].tolist(), [1300.0, 1300.0, 1300.0])
        self.assertEqual(merged[FX_FILLED_COLUMN].tolist(), [True, True, False])
        actions = [record["처리"] for record in log.records if record["대상"] == FX_COLUMN]
        self.assertEqual(actions, ["bfill", "bfill"])

    def test_middle_gap_is_ffilled_not_backfilled(self):
        prices = price_frame(["2026-03-02", "2026-03-03", "2026-03-04"])
        fx = prepare_macro_series(
            [(date(2026, 3, 2), 1300.0), (date(2026, 3, 4), 1320.0)], FX_COLUMN
        )
        log = QualityLog()

        merged = merge_macro_with_prices(prices, fx, None, log=log)

        self.assertEqual(merged[FX_COLUMN].tolist(), [1300.0, 1300.0, 1320.0])
        self.assertEqual(
            [record["처리"] for record in log.records if record["대상"] == FX_COLUMN],
            ["ffill"],
        )

    def test_outlier_columns_flag_spike_and_keep_values(self):
        dates = pd.date_range("2026-01-01", periods=40, freq="B")
        rng = np.random.default_rng(3)
        closes = list(100 * np.cumprod(1 + rng.normal(0, 0.005, len(dates))))
        closes[25] = closes[24] * 1.10
        prices = price_frame(list(dates.strftime("%Y-%m-%d")), closes)
        log = QualityLog()

        merged = merge_macro_with_prices(prices, None, None, log=log)

        for column in (PRICE_OUTLIER_COLUMN, FX_OUTLIER_COLUMN, RATE_OUTLIER_COLUMN):
            self.assertIn(column, merged.columns)
        self.assertTrue(merged[PRICE_OUTLIER_COLUMN].iloc[25])
        self.assertEqual(merged["종가"].iloc[25], closes[25])
        self.assertTrue(
            any(record["처리"] == "이상치표시" and record["대상"] == "종가" for record in log.records)
        )

    def test_macro_scale_error_is_corrected_before_merge(self):
        prices = price_frame(["2026-03-02", "2026-03-03", "2026-03-04"])
        rate = prepare_macro_series(
            [(date(2026, 3, 2), 3.9), (date(2026, 3, 3), 0.0391), (date(2026, 3, 4), 3.92)],
            RATE_COLUMN,
        )
        log = QualityLog()

        merged = merge_macro_with_prices(prices, None, rate, log=log)

        self.assertAlmostEqual(merged[RATE_COLUMN].iloc[1], 3.91)
        self.assertEqual(log.count("입력오류보정"), 1)


class MacroKPITests(unittest.TestCase):
    def test_missing_macro_marks_all_missing(self):
        kpis = _macro_kpis(None)
        self.assertTrue(all(metric["status"] == "missing" for metric in kpis.values()))

    def test_changes_and_correlation(self):
        dates = pd.date_range("2026-01-01", periods=30, freq="B")
        rng = np.random.default_rng(0)
        closes = 100 * np.cumprod(1 + rng.normal(0, 0.01, len(dates)))
        prices = price_frame(list(dates.strftime("%Y-%m-%d")), list(closes))
        fx = prepare_macro_series(
            [(day.date(), 1300.0 + index) for index, day in enumerate(dates)], FX_COLUMN
        )
        rate = prepare_macro_series(
            [(day.date(), 3.0) for day in dates],
            RATE_COLUMN,
        )

        kpis = _macro_kpis(merge_macro_with_prices(prices, fx, rate))

        self.assertEqual(kpis["usd_krw_latest"]["value"], 1329.0)
        self.assertEqual(kpis["usd_krw_change"]["value"], round(29 / 1300 * 100, 2))
        self.assertEqual(kpis["treasury_3y_change_bp"]["value"], 0.0)
        self.assertEqual(kpis["macro_filled_days"]["value"], 0)
        self.assertEqual(kpis["corr_return_usd_krw"]["status"], "available")
        self.assertEqual(kpis["corr_return_usd_krw"]["observations"], 29)
        self.assertEqual(kpis["corr_return_treasury_3y"]["observations"], 29)
        # 금리가 변하지 않아 분산이 0이면 상관계수를 만들지 않는다.
        self.assertEqual(kpis["corr_return_treasury_3y"]["status"], "missing")
        self.assertEqual(
            kpis["corr_usd_krw_treasury_3y_level"]["status"], "missing"
        )
        self.assertEqual(
            kpis["corr_usd_krw_treasury_3y_change"]["status"], "missing"
        )

    def test_credit_spread_kpis_and_stock_return_correlation(self):
        dates = pd.date_range("2026-01-01", periods=30, freq="B")
        rng = np.random.default_rng(21)
        spread_changes = rng.normal(0, 0.12, len(dates) - 1)
        spread_values = [110.0]
        for change in spread_changes:
            spread_values.append(spread_values[-1] + change)
        returns = np.r_[0.0, spread_changes]
        closes = 100 * np.cumprod(1 + returns / 100)
        prices = price_frame(
            list(dates.strftime("%Y-%m-%d")), list(closes)
        ).assign(시장구분="KOSPI")
        rate = prepare_macro_series(
            [(day.date(), 3.0) for day in dates], RATE_COLUMN
        )
        corporate = prepare_macro_series(
            [
                (day.date(), 3.0 + spread / 100)
                for day, spread in zip(dates, spread_values)
            ],
            CORPORATE_BOND_COLUMN,
        )
        market_index = prepare_macro_series(
            [
                (day.date(), value)
                for day, value in zip(
                    dates, 2500 * np.cumprod(1 + returns / 100)
                )
            ],
            MARKET_INDEX_COLUMN,
        )

        kpis = _macro_kpis(
            merge_macro_with_prices(
                prices,
                rate=rate,
                corporate_bond=corporate,
                market_indices={"KOSPI": market_index},
            )
        )

        self.assertEqual(kpis["market_index_name"]["value"], "KOSPI")
        self.assertEqual(kpis["corr_return_market_index"]["status"], "available")
        self.assertAlmostEqual(
            kpis["corr_return_market_index"]["value"], 1.0, places=2
        )
        self.assertEqual(kpis["credit_spread_latest"]["status"], "available")
        self.assertEqual(kpis["credit_spread_change_bp"]["status"], "available")
        self.assertEqual(kpis["corr_return_credit_spread"]["status"], "available")
        self.assertEqual(kpis["corr_return_credit_spread"]["observations"], 29)
        self.assertAlmostEqual(
            kpis["corr_return_credit_spread"]["value"], 1.0, places=2
        )

    def test_fx_rate_level_and_change_correlations(self):
        dates = pd.date_range("2026-01-01", periods=35, freq="B")
        rng = np.random.default_rng(7)
        linked_changes = rng.normal(0, 0.2, len(dates) - 1)
        fx_values = [1300.0]
        rate_values = [3.0]
        for change in linked_changes:
            fx_values.append(fx_values[-1] * (1 + change / 100))
            rate_values.append(rate_values[-1] + change / 100)
        prices = price_frame(
            list(dates.strftime("%Y-%m-%d")),
            list(100 * np.cumprod(1 + rng.normal(0, 0.01, len(dates)))),
        )
        fx = prepare_macro_series(
            [(day.date(), value) for day, value in zip(dates, fx_values)],
            FX_COLUMN,
        )
        rate = prepare_macro_series(
            [(day.date(), value) for day, value in zip(dates, rate_values)],
            RATE_COLUMN,
        )

        kpis = _macro_kpis(merge_macro_with_prices(prices, fx, rate))

        self.assertEqual(
            kpis["corr_usd_krw_treasury_3y_level"]["status"], "available"
        )
        self.assertEqual(
            kpis["corr_usd_krw_treasury_3y_change"]["status"], "available"
        )
        self.assertAlmostEqual(
            kpis["corr_usd_krw_treasury_3y_change"]["value"], 1.0, places=2
        )

    def test_short_period_has_no_correlation(self):
        prices = price_frame(["2026-03-02", "2026-03-03", "2026-03-04"])
        fx = prepare_macro_series(
            [(date(2026, 3, 2), 1300.0), (date(2026, 3, 3), 1301.0), (date(2026, 3, 4), 1299.0)],
            FX_COLUMN,
        )

        kpis = _macro_kpis(merge_macro_with_prices(prices, fx, None))

        self.assertEqual(kpis["corr_return_usd_krw"]["status"], "no_comparison_period")
        self.assertEqual(kpis["treasury_3y_latest"]["status"], "missing")
        self.assertEqual(
            kpis["corr_usd_krw_treasury_3y_level"]["status"], "missing"
        )

    def test_one_month_sized_sample_has_correlations(self):
        dates = pd.date_range("2026-09-14", periods=15, freq="B")
        rng = np.random.default_rng(11)
        stock_changes = rng.normal(0, 0.01, len(dates))
        macro_changes = rng.normal(0, 0.15, len(dates) - 1)
        closes = list(100 * np.cumprod(1 + stock_changes))
        fx_values = [1400.0]
        rate_values = [2.8]
        for index, change in enumerate(macro_changes):
            fx_values.append(fx_values[-1] * (1 + change / 100))
            rate_values.append(rate_values[-1] + (change + (index % 3 - 1) * 0.02) / 100)
        prices = price_frame(list(dates.strftime("%Y-%m-%d")), closes)
        fx = prepare_macro_series(
            [(day.date(), value) for day, value in zip(dates, fx_values)],
            FX_COLUMN,
        )
        rate = prepare_macro_series(
            [(day.date(), value) for day, value in zip(dates, rate_values)],
            RATE_COLUMN,
        )

        kpis = _macro_kpis(merge_macro_with_prices(prices, fx, rate))

        for name in (
            "corr_return_usd_krw",
            "corr_return_treasury_3y",
            "corr_usd_krw_treasury_3y_level",
            "corr_usd_krw_treasury_3y_change",
        ):
            self.assertEqual(kpis[name]["status"], "available")


if __name__ == "__main__":
    unittest.main()
