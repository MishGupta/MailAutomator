import smtplib
from types import SimpleNamespace

import pytest

import send_emails
from send_emails import ConnectionProblem, connect_or_explain, validate_limit
from mailauto.parsing import Contact
from mailauto.sentlog import load_sent


def _conf():
    return SimpleNamespace(address="me@gmail.com", app_password="pw")


def test_connect_or_explain_returns_smtp_and_reports_progress(monkeypatch, capsys):
    sentinel = object()
    monkeypatch.setattr(send_emails.mailer, "connect", lambda a, p: sentinel)
    assert connect_or_explain(_conf()) is sentinel
    # silence is what made a 2s connect look like a hang
    assert "Connecting to Gmail" in capsys.readouterr().out


def test_connect_or_explain_auth_error_is_friendly(monkeypatch):
    def boom(addr, pw):
        raise smtplib.SMTPAuthenticationError(535, b"bad creds")
    monkeypatch.setattr(send_emails.mailer, "connect", boom)
    with pytest.raises(ConnectionProblem) as e:
        connect_or_explain(_conf())
    assert "app password" in str(e.value).lower()


def test_connect_or_explain_timeout_is_friendly(monkeypatch):
    def boom(addr, pw):
        raise TimeoutError("timed out")
    monkeypatch.setattr(send_emails.mailer, "connect", boom)
    with pytest.raises(ConnectionProblem) as e:
        connect_or_explain(_conf())
    assert "could not reach gmail" in str(e.value).lower()


def test_connect_or_explain_network_error_is_friendly(monkeypatch):
    def boom(addr, pw):
        raise OSError("network is down")
    monkeypatch.setattr(send_emails.mailer, "connect", boom)
    with pytest.raises(ConnectionProblem):
        connect_or_explain(_conf())


def test_validate_limit_none_ok():
    assert validate_limit(None) is None


def test_validate_limit_positive_ok():
    assert validate_limit(400) == 400


def test_validate_limit_zero_rejected():
    with pytest.raises(ValueError):
        validate_limit(0)


def test_validate_limit_negative_rejected():
    with pytest.raises(ValueError):
        validate_limit(-5)


# --- batch resilience when the SMTP connection dies mid-run -------------------
#
# Live incident: after 11 successful sends Gmail reset the connection. smtplib
# then raised SMTPServerDisconnected("please run connect() first") on every
# later send, and the batch loop logged each remaining contact as a failure
# without sending anything. A dead socket is a batch-level problem, not a
# per-recipient one.

class _FakeSMTP:
    """SMTP double whose send_message follows a scripted pass/raise sequence.

    Once a disconnect is scripted the session stays dead, as smtplib does: it
    drops its socket and raises SMTPServerDisconnected on every later call.
    That permanence is the whole reason a dead connection can eat a batch.
    """

    def __init__(self, script):
        self.script = list(script)  # each entry: None to succeed, else an exception
        self.sent = []
        self.dead = False
        self.quit_calls = 0

    def send_message(self, msg):
        if self.dead:
            raise smtplib.SMTPServerDisconnected("please run connect() first")
        outcome = self.script.pop(0) if self.script else None
        if outcome is not None:
            if isinstance(outcome, smtplib.SMTPServerDisconnected):
                self.dead = True
            raise outcome
        self.sent.append(msg["To"])

    def quit(self):
        self.quit_calls += 1

    def close(self):
        pass


def _setup(monkeypatch, tmp_path, smtps, n_contacts=3, connect_fails_after=None):
    """Wire cmd_send onto fake SMTP sessions and a temp send log."""
    log = tmp_path / "sent_log.csv"
    monkeypatch.setattr(send_emails, "SENT_LOG", str(log))
    monkeypatch.setattr(send_emails.time, "sleep", lambda s: None)

    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fake")

    sessions = list(smtps)
    connects = []

    def fake_connect(addr, pw):
        connects.append(addr)
        if connect_fails_after is not None and len(connects) > connect_fails_after:
            raise smtplib.SMTPServerDisconnected("cannot reach gmail")
        return sessions.pop(0)

    monkeypatch.setattr(send_emails.mailer, "connect", fake_connect)

    conf = SimpleNamespace(
        address="me@gmail.com", app_password="pw", resume_path=str(resume),
        cc_self=False, daily_limit=10, delay_seconds=0,
    )
    contacts = [
        Contact(name=f"P{i}", email=f"p{i}@acme.com", title="HR", company=f"Co{i}")
        for i in range(n_contacts)
    ]
    return conf, contacts, log, connects


def test_send_reconnects_and_still_delivers_after_socket_dies(monkeypatch, tmp_path):
    """A dropped connection must be re-established, not charged to the contact."""
    dead = _FakeSMTP([None, smtplib.SMTPServerDisconnected("please run connect() first")])
    fresh = _FakeSMTP([None, None])
    conf, contacts, log, connects = _setup(monkeypatch, tmp_path, [dead, fresh])

    rc = send_emails.cmd_send(conf, "Hi {company}", "Dear {name}", contacts, set())

    assert rc.exit_code == 0
    assert len(connects) == 2, "should have reconnected after the socket died"
    # p1 hit the dead socket; it must still be delivered, not written off.
    assert dead.sent == ["p0@acme.com"]
    assert fresh.sent == ["p1@acme.com", "p2@acme.com"]
    assert load_sent(str(log)) == {"p0@acme.com", "p1@acme.com", "p2@acme.com"}


def test_send_aborts_rather_than_burning_contacts_when_reconnect_fails(monkeypatch, tmp_path):
    """If Gmail is unreachable, remaining contacts must stay pending for a retry."""
    dead = _FakeSMTP([None, smtplib.SMTPServerDisconnected("connection reset by peer")])
    conf, contacts, log, connects = _setup(
        monkeypatch, tmp_path, [dead], connect_fails_after=1
    )

    rc = send_emails.cmd_send(conf, "Hi {company}", "Dear {name}", contacts, set())

    assert rc.exit_code == 1, "an unreachable Gmail should be reported as a failed run"
    # Only p0 got out. p1 and p2 must NOT be recorded at all -- any row for them
    # is a contact silently consumed by a dead socket.
    rows = log.read_text()
    assert "p0@acme.com" in rows
    assert "p1@acme.com" not in rows
    assert "p2@acme.com" not in rows
    assert load_sent(str(log)) == {"p0@acme.com"}


def test_send_logs_bad_recipient_and_keeps_going(monkeypatch, tmp_path):
    """Per-recipient refusals are still per-contact: log and carry on."""
    refused = smtplib.SMTPRecipientsRefused({"p1@acme.com": (550, b"no such user")})
    smtp = _FakeSMTP([None, refused, None])
    conf, contacts, log, connects = _setup(monkeypatch, tmp_path, [smtp])

    rc = send_emails.cmd_send(conf, "Hi {company}", "Dear {name}", contacts, set())

    assert rc.exit_code == 0
    assert len(connects) == 1, "a bad address must not trigger a reconnect"
    assert load_sent(str(log)) == {"p0@acme.com", "p2@acme.com"}
    assert "p1@acme.com" in log.read_text()  # recorded as an error


def test_send_result_reports_counts_and_remaining(monkeypatch, tmp_path):
    """The scheduler needs real numbers, not a parsed sentence."""
    smtp = _FakeSMTP([None, None, None])
    conf, contacts, log, connects = _setup(monkeypatch, tmp_path, [smtp], n_contacts=5)
    conf.daily_limit = 3  # 5 pending, 3 go out, 2 must be reported as left

    result = send_emails.cmd_send(conf, "Hi {company}", "Dear {name}", contacts, set())

    assert result.sent == 3
    assert result.failed == 0
    assert result.remaining == 2
    assert result.aborted is None
    assert result.exit_code == 0


def test_send_result_remaining_counts_failures_as_still_pending(monkeypatch, tmp_path):
    """A refused address was not delivered, so it still counts as outstanding."""
    refused = smtplib.SMTPRecipientsRefused({"p1@acme.com": (550, b"no such user")})
    smtp = _FakeSMTP([None, refused, None])
    conf, contacts, log, connects = _setup(monkeypatch, tmp_path, [smtp], n_contacts=3)

    result = send_emails.cmd_send(conf, "Hi {company}", "Dear {name}", contacts, set())

    assert (result.sent, result.failed) == (2, 1)
    assert result.remaining == 1
    assert result.exit_code == 0


def test_send_result_aborted_carries_the_reason(monkeypatch, tmp_path):
    """An aborted batch must be distinguishable from a clean one."""
    dead = _FakeSMTP([None, smtplib.SMTPServerDisconnected("connection reset by peer")])
    conf, contacts, log, connects = _setup(
        monkeypatch, tmp_path, [dead], n_contacts=3, connect_fails_after=1
    )

    result = send_emails.cmd_send(conf, "Hi {company}", "Dear {name}", contacts, set())

    assert result.aborted is not None
    assert "gmail" in result.aborted.lower()
    assert result.sent == 1
    assert result.exit_code == 1


def test_send_result_empty_list_is_complete_not_aborted(monkeypatch, tmp_path):
    """Nothing pending is the finished state, and must not touch Gmail."""
    conf, contacts, log, connects = _setup(monkeypatch, tmp_path, [], n_contacts=0)

    result = send_emails.cmd_send(conf, "Hi {company}", "Dear {name}", contacts, set())

    assert (result.sent, result.failed, result.remaining) == (0, 0, 0)
    assert result.aborted is None
    assert connects == [], "an empty batch must never connect to Gmail"


# --- consecutive-failure circuit breaker (Finding 1) --------------------------
#
# If Gmail starts refusing the message class wholesale (identical attachment,
# cold outreach) every recipient in the batch fails individually even though
# the connection is fine. Without a breaker, each of those failures still
# burns one of that contact's 3 lifetime attempts, and the run still reports
# success to the scheduler -- three such days permanently retires 150 live
# contacts who were never actually emailed.

def test_send_aborts_after_five_consecutive_failures(monkeypatch, tmp_path):
    """A solid wall of refusals must stop the batch, not burn every contact."""
    refused = smtplib.SMTPRecipientsRefused({"x": (550, b"no such user")})
    smtp = _FakeSMTP([refused] * 5)
    conf, contacts, log, connects = _setup(monkeypatch, tmp_path, [smtp], n_contacts=10)

    rc = send_emails.cmd_send(conf, "Hi {company}", "Dear {name}", contacts, set())

    assert rc.aborted is not None
    assert rc.exit_code == 1
    assert smtp.sent == []
    rows = log.read_text()
    for i in range(5):
        assert f"p{i}@acme.com" in rows, "each of the 5 refusals must still be logged"
    for i in range(5, 10):
        assert f"p{i}@acme.com" not in rows, "contacts beyond the 5th must never be attempted"


def test_send_four_failures_then_a_success_does_not_abort_and_resets_the_counter(monkeypatch, tmp_path):
    """Scattered failures below the limit, or reset by a success, must not abort."""
    refused = smtplib.SMTPRecipientsRefused({"x": (550, b"no such user")})
    script = [refused] * 4 + [None] + [refused] * 4  # 9 items, never 5 in a row
    smtp = _FakeSMTP(script)
    conf, contacts, log, connects = _setup(monkeypatch, tmp_path, [smtp], n_contacts=9)

    rc = send_emails.cmd_send(conf, "Hi {company}", "Dear {name}", contacts, set())

    assert rc.aborted is None
    assert rc.exit_code == 0
    assert rc.sent == 1
    assert rc.failed == 8
    # nothing was cut short -- all 9 contacts were attempted
    rows = log.read_text()
    for i in range(9):
        assert f"p{i}@acme.com" in rows


def test_send_single_bad_recipient_among_successes_still_just_logs_and_continues(monkeypatch, tmp_path):
    """Existing behaviour, unchanged: one refusal is nowhere near the threshold."""
    refused = smtplib.SMTPRecipientsRefused({"p1@acme.com": (550, b"no such user")})
    smtp = _FakeSMTP([None, refused, None])
    conf, contacts, log, connects = _setup(monkeypatch, tmp_path, [smtp])

    rc = send_emails.cmd_send(conf, "Hi {company}", "Dear {name}", contacts, set())

    assert rc.aborted is None
    assert rc.exit_code == 0
    assert (rc.sent, rc.failed) == (2, 1)


# --- Finding 2b: a contacts file that parses to zero rows must not look like
# "the whole list is finished" ------------------------------------------------

def test_load_all_rejects_a_contacts_file_that_yields_zero_contacts(tmp_path, monkeypatch):
    resume = tmp_path / "resume.pdf"; resume.write_text("x")
    template = tmp_path / "email_template.txt"; template.write_text("Subject: hi\n\nbody")
    contacts = tmp_path / "contacts.csv"; contacts.write_text("name,email,title,company\n")
    config = tmp_path / "config.ini"
    config.write_text(
        "[gmail]\naddress = a@b.com\napp_password = pw\n"
        f"[files]\nresume = {resume}\ntemplate = {template}\ncontacts = {contacts}\n"
    )

    with pytest.raises(ValueError):
        send_emails._load_all(str(config))
