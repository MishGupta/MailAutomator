import smtplib
from types import SimpleNamespace

import pytest

import send_emails
from send_emails import ConnectionProblem, connect_or_explain, validate_limit


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
