from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DashboardLayoutTests(unittest.TestCase):
    def test_multi_company_macro_radar_stacks_summary_below_title(self):
        template = (
            PROJECT_ROOT / "templates" / "result_dashboard.html"
        ).read_text(encoding="utf-8")
        styles = (PROJECT_ROOT / "static" / "style.css").read_text(encoding="utf-8")

        self.assertIn("matrix.companies|length > 1", template)
        self.assertIn("radar-heading{% if", template)
        self.assertIn(".radar-heading h3 {", styles)
        self.assertIn("white-space: nowrap", styles)
        self.assertIn(".radar-heading.is-multi-company {", styles)
        self.assertIn("flex-direction: column", styles)
