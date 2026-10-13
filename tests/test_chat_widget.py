from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = PROJECT_ROOT / "templates"


def test_chat_widget_uses_requested_chatbot_id_and_async_embed():
    widget = (TEMPLATES / "_chat_widget.html").read_text(encoding="utf-8")

    assert 'chatbotId: "8128624198"' in widget
    assert 'data-id="8128624198"' in widget
    assert 'id="chtl-script"' in widget
    assert "https://chatling.ai/js/embed.js" in widget
    assert "async" in widget


def test_all_full_page_templates_include_chat_widget():
    for template_name in ("index.html", "result_dashboard.html", "result.html"):
        template = (TEMPLATES / template_name).read_text(encoding="utf-8")
        assert '{% include "_chat_widget.html" %}' in template
