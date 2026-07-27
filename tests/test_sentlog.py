import pytest
from mailauto.sentlog import load_sent, append_result
from mailauto.sentlog import load_done, append_result, MAX_ATTEMPTS


def _log(tmp_path, rows):
    p = tmp_path / "sent_log.csv"
    for email, status in rows:
        append_result(str(p), email, status, "boom" if status == "error" else "")
    return str(p)


def test_load_sent_missing_file(tmp_path):
    assert load_sent(str(tmp_path / "none.csv")) == set()


def test_append_then_load_roundtrip(tmp_path):
    p = str(tmp_path / "sent_log.csv")
    append_result(p, "Jane@Acme.com", "sent")
    append_result(p, "bob@acme.com", "error", "SMTP boom")
    sent = load_sent(p)
    assert "jane@acme.com" in sent      # lowercased
    assert "bob@acme.com" not in sent    # errors are not counted as sent


def test_load_sent_empty_file_returns_empty_set(tmp_path):
    p = tmp_path / "sent_log.csv"
    p.write_text("")
    assert load_sent(str(p)) == set()


def test_append_result_writes_header_when_file_exists_but_is_empty(tmp_path):
    p = tmp_path / "sent_log.csv"
    p.write_text("")  # simulates a crash that created a 0-byte file
    append_result(str(p), "jane@acme.com", "sent")
    # header must have been written, so the row is parseable and counted
    assert load_sent(str(p)) == {"jane@acme.com"}


def test_load_sent_raises_on_malformed_header(tmp_path):
    p = tmp_path / "sent_log.csv"
    # a data row written without a preceding header
    p.write_text("2026-01-01T00:00:00,jane@acme.com,sent,\n")
    with pytest.raises(ValueError):
        load_sent(str(p))


def test_delivered_address_is_done(tmp_path):
    p = _log(tmp_path, [("a@x.com", "sent")])
    assert load_done(p) == {"a@x.com"}


def test_one_failure_is_not_done_so_it_retries(tmp_path):
    """The 8 real failures on record died to a dropped socket, not a bad
    address. Giving up after one error would silently discard live contacts."""
    p = _log(tmp_path, [("a@x.com", "error")])
    assert load_done(p) == set()


def test_two_failures_are_not_done(tmp_path):
    p = _log(tmp_path, [("a@x.com", "error"), ("a@x.com", "error")])
    assert load_done(p) == set()


def test_three_failures_are_done(tmp_path):
    """Three strikes: a dead address must stop blocking completion, or the
    scheduler retries it every weekday forever and never switches off."""
    p = _log(tmp_path, [("a@x.com", "error")] * 3)
    assert load_done(p) == {"a@x.com"}


def test_more_than_three_failures_stay_done(tmp_path):
    p = _log(tmp_path, [("a@x.com", "error")] * 5)
    assert load_done(p) == {"a@x.com"}


def test_success_after_failures_is_done(tmp_path):
    p = _log(tmp_path, [("a@x.com", "error"), ("a@x.com", "sent")])
    assert load_done(p) == {"a@x.com"}


def test_failures_are_counted_per_address(tmp_path):
    p = _log(tmp_path, [
        ("a@x.com", "error"), ("a@x.com", "error"), ("a@x.com", "error"),
        ("b@x.com", "error"),
    ])
    assert load_done(p) == {"a@x.com"}


def test_addresses_are_matched_case_insensitively(tmp_path):
    """contacts.csv and the log disagree on case; three attempts must count
    as three even when the address is spelled differently each time."""
    p = _log(tmp_path, [("A@x.com", "error"), ("a@X.com", "error"), (" a@x.com ", "error")])
    assert load_done(p) == {"a@x.com"}


def test_missing_log_means_nothing_is_done(tmp_path):
    assert load_done(str(tmp_path / "nope.csv")) == set()


def test_max_attempts_is_three():
    assert MAX_ATTEMPTS == 3


def test_load_done_rejects_a_malformed_log(tmp_path):
    """Same refusal as load_sent: a corrupt log must never be guessed at."""
    p = tmp_path / "sent_log.csv"
    p.write_text("wrong,header\n1,2\n")
    with pytest.raises(ValueError):
        load_done(str(p))
