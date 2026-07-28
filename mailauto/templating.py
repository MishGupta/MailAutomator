import html as _html
import re

# **bold** spans, and bare URLs to turn into anchors in the HTML part.
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_URL = re.compile(r"(https?://[^\s<>\"]+)")


def strip_bold(text: str) -> str:
    """Drop the ** markers, leaving clean text for the plain-text part."""
    return _BOLD.sub(r"\1", text)


def to_html(text: str) -> str:
    """Render the body as HTML: **bold** to <b>, blank lines to paragraphs.

    Escapes first so contact fields carrying & or <> (e.g. "Johnson & Johnson")
    can't corrupt the markup.
    """
    escaped = _html.escape(text)
    marked = _BOLD.sub(r"<b>\1</b>", escaped)
    linked = _URL.sub(r'<a href="\1">\1</a>', marked)
    paragraphs = [p.replace("\n", "<br>\n") for p in linked.split("\n\n")]
    return "\n".join(f"<p>{p}</p>" for p in paragraphs)


def parse_template(text: str) -> tuple:
    lines = text.splitlines()
    if not lines or not lines[0].lower().startswith("subject:"):
        raise ValueError("Template must start with 'Subject: ...' on the first line")
    subject_template = lines[0].split(":", 1)[1].strip()
    rest = lines[1:]
    i = 0
    while i < len(rest) and rest[i].strip() == "":
        i += 1
    body_template = "\n".join(rest[i:])
    return subject_template, body_template


def _fill(template: str, contact) -> str:
    return (template
            .replace("{name}", contact.name)
            .replace("{company}", contact.company)
            .replace("{title}", contact.title)
            .replace("{email}", contact.email))


def render(subject_template: str, body_template: str, contact) -> tuple:
    return _fill(subject_template, contact), _fill(body_template, contact)
