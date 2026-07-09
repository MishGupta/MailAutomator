import pytest
from mailauto.sentlog import load_sent, append_result


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
