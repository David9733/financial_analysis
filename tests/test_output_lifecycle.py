from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import app as app_module
from src.main import CLI_OUTPUT_DIR, OUTPUT_DIR


class OutputLifecycleTests(unittest.TestCase):
    def setUp(self):
        app_module.ACTIVE_RUN_IDS.clear()

    def tearDown(self):
        app_module.ACTIVE_RUN_IDS.clear()

    def _make_run(
        self,
        root: Path,
        run_id: str,
        *,
        completed_at: float | None = None,
    ) -> Path:
        run_dir = root / run_id
        run_dir.mkdir()
        (run_dir / "result.csv").write_text("result", encoding="utf-8")
        if completed_at is not None:
            marker = run_dir / app_module.COMPLETED_MARKER_NAME
            marker.touch()
            os.utime(marker, (completed_at, completed_at))
        return run_dir

    def test_cli_and_web_outputs_use_separate_directories(self):
        self.assertEqual(CLI_OUTPUT_DIR, OUTPUT_DIR / "cli")
        self.assertEqual(app_module.WEB_RUNS_DIR, OUTPUT_DIR / "web_runs")

    def test_cleanup_removes_only_expired_completed_runs(self):
        now = 10_000.0
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            expired = self._make_run(root, "a" * 32, completed_at=now - 3_601)
            recent = self._make_run(root, "b" * 32, completed_at=now - 3_599)
            incomplete = self._make_run(root, "c" * 32)

            with patch.object(app_module, "WEB_RUNS_DIR", root):
                app_module.cleanup_expired_web_runs(now=now)

            self.assertFalse(expired.exists())
            self.assertTrue(recent.exists())
            self.assertTrue(incomplete.exists())

    def test_cleanup_never_removes_an_active_run(self):
        now = 10_000.0
        run_id = "d" * 32
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            active = self._make_run(root, run_id, completed_at=now - 7_200)
            app_module.ACTIVE_RUN_IDS.add(run_id)

            with patch.object(app_module, "WEB_RUNS_DIR", root):
                app_module.cleanup_expired_web_runs(now=now)

            self.assertTrue(active.exists())


if __name__ == "__main__":
    unittest.main()
