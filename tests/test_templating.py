from mailauto.parsing import Contact
from mailauto.templating import parse_template, render
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
