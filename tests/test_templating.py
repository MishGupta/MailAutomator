from mailauto.parsing import Contact
from mailauto.templating import parse_template, render, strip_bold, to_html
import pytest


TEMPLATE = """Subject: Application for opportunities at {company}

Dear {name},

I saw your role as {title} at {company}. Reach me at {email}.
"""


def test_parse_template_splits_subject_and_body():
    subject, body = parse_template(TEMPLATE)
    assert subject == "Application for opportunities at {company}"
    assert body.startswith("Dear {name},")
    assert "{title}" in body


def test_parse_template_requires_subject():
    with pytest.raises(ValueError):
        parse_template("No subject line here\n\nBody")


def test_render_fills_all_tokens():
    subject_t, body_t = parse_template(TEMPLATE)
    c = Contact("Akanksha Puri", "akanksha.puri@sourcefuse.com",
                "Associate Director HR", "SourceFuse Technologies")
    subject, body = render(subject_t, body_t, c)
    assert subject == "Application for opportunities at SourceFuse Technologies"
    assert "Dear Akanksha Puri," in body
    assert "Associate Director HR" in body
    assert "akanksha.puri@sourcefuse.com" in body
    assert "{" not in body  # no leftover tokens


def test_render_handles_empty_field():
    subject_t, body_t = parse_template(TEMPLATE)
    c = Contact("Jane", "jane@acme.com", "", "Acme")
    subject, body = render(subject_t, body_t, c)
    assert "role as  at Acme" in body  # empty title collapses cleanly


def test_strip_bold_removes_markers():
    assert strip_bold("I did **20+ fields** fast") == "I did 20+ fields fast"


def test_strip_bold_leaves_plain_text_alone():
    assert strip_bold("no markers here") == "no markers here"


def test_to_html_wraps_bold_in_b_tags():
    assert "<b>20+ fields</b>" in to_html("I did **20+ fields** fast")


def test_to_html_escapes_html_special_characters():
    # Company names like "Johnson & Johnson" must not corrupt the markup.
    html = to_html("Hi Johnson & Johnson <team>")
    assert "&amp;" in html
    assert "&lt;team&gt;" in html
    assert "<team>" not in html


def test_to_html_keeps_paragraph_breaks():
    html = to_html("First para.\n\nSecond para.")
    assert "<p>" in html
    assert html.count("<p>") == 2


def test_to_html_linkifies_bare_urls():
    html = to_html("See https://example.com/x now")
    assert '<a href="https://example.com/x">https://example.com/x</a>' in html
