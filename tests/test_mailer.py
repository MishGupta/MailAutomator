import smtplib
from mailauto import mailer


def test_build_message_has_headers_body_and_attachment(tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fake")
    msg = mailer.build_message(
        "me@gmail.com", "hr@acme.com", "Hello Acme", "Body text here",
        str(resume), cc_self="me@gmail.com",
    )
    assert msg["From"] == "me@gmail.com"
    assert msg["To"] == "hr@acme.com"
    assert msg["Cc"] == "me@gmail.com"
    assert msg["Subject"] == "Hello Acme"
    assert "Body text here" in msg.get_body(preferencelist=("plain",)).get_content()
    atts = list(msg.iter_attachments())
    assert len(atts) == 1
    assert atts[0].get_filename() == "resume.pdf"


def test_build_message_adds_html_alternative_and_keeps_plain(tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fake")
    msg = mailer.build_message(
        "me@gmail.com", "hr@acme.com", "S", "Plain body",
        str(resume), html_body="<p>HTML <b>body</b></p>",
    )
    assert "Plain body" in msg.get_body(preferencelist=("plain",)).get_content()
    assert "<b>body</b>" in msg.get_body(preferencelist=("html",)).get_content()
    # The attachment must survive the multipart restructuring.
    atts = list(msg.iter_attachments())
    assert len(atts) == 1
    assert atts[0].get_filename() == "resume.pdf"


def test_build_message_stays_plain_only_without_html(tmp_path):
    resume = tmp_path / "resume.pdf"; resume.write_bytes(b"x")
    msg = mailer.build_message("me@gmail.com", "hr@acme.com", "S", "B", str(resume))
    assert msg.get_body(preferencelist=("html",)) is None


def test_build_message_no_cc(tmp_path):
    resume = tmp_path / "resume.pdf"; resume.write_bytes(b"x")
    msg = mailer.build_message("me@gmail.com", "hr@acme.com", "S", "B", str(resume))
    assert msg["Cc"] is None


class _FakeSMTP:
    calls = []

    def __init__(self, host, port, timeout=None):
        _FakeSMTP.calls.append(("init", host, port, timeout))

    def starttls(self):
        _FakeSMTP.calls.append(("starttls",))

    def login(self, addr, pw):
        _FakeSMTP.calls.append(("login", addr, pw))

    def send_message(self, msg):
        _FakeSMTP.calls.append(("send_message", msg["To"]))


def test_connect_and_send(monkeypatch):
    _FakeSMTP.calls = []
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    smtp = mailer.connect("me@gmail.com", "app pass word here")
    assert ("init", "smtp.gmail.com", 587, 30) in _FakeSMTP.calls
    assert ("starttls",) in _FakeSMTP.calls
    assert ("login", "me@gmail.com", "app pass word here") in _FakeSMTP.calls

    class M(dict):
        pass
    m = M(); m["To"] = "hr@acme.com"
    mailer.send(smtp, m)
    assert ("send_message", "hr@acme.com") in _FakeSMTP.calls


def test_connect_uses_configured_host_and_port(monkeypatch):
    """A non-Gmail provider must be reachable without editing source."""
    _FakeSMTP.calls = []
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    mailer.connect("me@outlook.com", "pw",
                   host="smtp-mail.outlook.com", port=587)
    assert ("init", "smtp-mail.outlook.com", 587, 30) in _FakeSMTP.calls
    assert ("login", "me@outlook.com", "pw") in _FakeSMTP.calls


def test_connect_defaults_to_gmail(monkeypatch):
    """Omitting host/port keeps the original Gmail behaviour."""
    _FakeSMTP.calls = []
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    mailer.connect("me@gmail.com", "pw")
    assert ("init", "smtp.gmail.com", 587, 30) in _FakeSMTP.calls
