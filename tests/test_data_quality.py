from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.data_quality import (
    ACTION_OUTLIER,
    ACTION_SCALE_FIX,
    QualityLog,
    correct_scale_errors,
    daily_change,
    flag_change_outliers,
    iqr_bounds,
    pair_valid,
)


def trend_series(length: int = 60, seed: int = 1) -> pd.Series:
    """꾸준히 오르는 추세 + 작은 노이즈."""
    rng = np.random.default_rng(seed)
    return pd.Series(100 + np.arange(length) * 1.0 + rng.normal(0, 0.2, length))


def frame_of(values) -> pd.DataFrame:
    return pd.DataFrame(
        {"기준일": pd.date_range("2026-01-01", periods=len(values), freq="B"), "값": values}
    )


class OutlierTests(unittest.TestCase):
    def test_level_iqr_would_cut_trend_but_daily_change_does_not(self):
        # 40일 횡보 후 20일 동안 꾸준히 상승하는 정상적인 추세 구간.
        rng = np.random.default_rng(1)
        flat = 100 + rng.normal(0, 0.2, 40)
        rising = flat[-1] + np.arange(1, 21) * 2.0 + rng.normal(0, 0.2, 20)
        values = pd.Series(np.concatenate([flat, rising]))

        q1, q3 = values.quantile(0.25), values.quantile(0.75)
        level_outliers = values > q3 + 1.5 * (q3 - q1)
        self.assertGreaterEqual(int(level_outliers.sum()), 5)  # 상승 구간이 잘려 나간다
        self.assertTrue(level_outliers.iloc[-1])

        flags = flag_change_outliers(daily_change(values, "pct"))
        self.assertEqual(int(flags.sum()), 0)

    def test_spike_day_is_flagged_and_kept(self):
        values = trend_series()
        values.iloc[30] = values.iloc[29] * 1.08
        values.iloc[31:] = values.iloc[31:] + (values.iloc[30] - values.iloc[29])
        original = values.copy()

        changes = daily_change(values, "pct")
        flags = flag_change_outliers(changes)

        self.assertTrue(flags.iloc[30])
        # 튄 날이 가장 큰 이상치이고, 값은 지우거나 바꾸지 않는다.
        self.assertEqual(changes[flags].abs().idxmax(), 30)
        pd.testing.assert_series_equal(values, original)

    def test_too_few_observations_flag_nothing(self):
        changes = daily_change(pd.Series([1.0, 1.0, 1.0, 5.0, 1.0]), "pct")
        self.assertFalse(flag_change_outliers(changes).any())
        self.assertIsNone(iqr_bounds(changes))

    def test_filled_zero_changes_do_not_narrow_iqr(self):
        values = trend_series(40)
        filled = pd.Series(False, index=values.index)
        # 절반을 직전 값으로 채운 것처럼 만든다(변화 0).
        for position in range(2, 40, 2):
            values.iloc[position] = values.iloc[position - 1]
            filled.iloc[position] = True
        changes = daily_change(values, "pct")

        naive = iqr_bounds(changes)
        cleaned = iqr_bounds(changes, pair_valid(filled))

        self.assertIsNone(cleaned)  # 유효 관측이 20개 미만이면 판정하지 않는다
        self.assertIsNotNone(naive)

    def test_pair_valid_excludes_filled_day_and_next_day(self):
        filled = pd.Series([False, False, True, False, False])
        self.assertEqual(pair_valid(filled).tolist(), [False, True, False, False, True])


class ScaleErrorTests(unittest.TestCase):
    def test_decimal_error_is_corrected_and_logged(self):
        log = QualityLog()
        frame = frame_of([3.878, 3.93, 0.03901, 3.91, 3.88])

        corrected, multiplier = correct_scale_errors(frame, "값", log, target="국고채3년")

        self.assertAlmostEqual(corrected["값"].iloc[2], 3.901)
        self.assertEqual(multiplier.iloc[2], 100)
        self.assertEqual(log.count(ACTION_SCALE_FIX), 1)
        record = log.records[0]
        self.assertEqual(record["대상"], "국고채3년")
        self.assertAlmostEqual(record["원래값"], 0.03901)

    def test_ten_times_too_large_is_corrected(self):
        corrected, _ = correct_scale_errors(frame_of([1350.0, 13580.0, 1360.0]), "값")
        self.assertAlmostEqual(corrected["값"].iloc[1], 1358.0)

    def test_persistent_level_shift_is_not_corrected(self):
        # 액면분할처럼 수준이 바뀐 뒤 유지되면 입력 오류로 보지 않는다.
        values = [50000.0, 50500.0, 1000.0, 1010.0, 1005.0]
        log = QualityLog()

        corrected, multiplier = correct_scale_errors(frame_of(values), "값", log)

        self.assertEqual(corrected["값"].tolist(), values)
        self.assertTrue((multiplier == 1).all())
        self.assertEqual(log.records, [])

    def test_real_large_move_is_not_corrected(self):
        values = [100.0, 130.0, 101.0]
        corrected, _ = correct_scale_errors(frame_of(values), "값")
        self.assertEqual(corrected["값"].tolist(), values)


class QualityLogTests(unittest.TestCase):
    def test_summary_mentions_cause_check_when_outliers(self):
        log = QualityLog()
        log.add("종가", "2026-03-02", ACTION_OUTLIER, 100, 100, "테스트", "테스트전자")
        self.assertIn("이상치 표시 1건(원인 확인 필요)", log.summary_text())
        self.assertEqual(log.to_frame()["기준일"].iloc[0], "2026-03-02")


if __name__ == "__main__":
    unittest.main()
