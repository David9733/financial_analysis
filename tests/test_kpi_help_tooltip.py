from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class KpiHelpTooltipTests(unittest.TestCase):
    def test_dashboard_tooltips_are_only_shown_by_single_active_controller(self):
        styles = (PROJECT_ROOT / "static" / "style.css").read_text(encoding="utf-8")
        template = (
            PROJECT_ROOT / "templates" / "result_dashboard.html"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "body:not(.result-page) .kpi-help-item:hover .kpi-help-tooltip",
            styles,
        )
        self.assertIn(
            "body:not(.result-page) .kpi-help-item:focus .kpi-help-tooltip",
            styles,
        )
        self.assertIn("if (activeHelp) hideHelp(null, true);", template)
        self.assertIn(
            "activeOwner.setAttribute('aria-expanded', 'false');", template
        )
        self.assertIn("owner.setAttribute('aria-expanded', 'true');", template)
