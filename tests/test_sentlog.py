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
