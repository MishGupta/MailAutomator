from mailauto.parsing import Contact
from mailauto.planner import select_pending


def _c(email, name="N", title="T", company="C"):
    return Contact(name, email, title, company)


def test_select_pending_filters_and_limits():
    contacts = [
        _c("a@acme.com"),
        _c("BAD-EMAIL"),          # invalid -> dropped
        _c("b@acme.com"),
        _c("Sent@Acme.com"),      # already sent (case-insensitive) -> dropped
        _c("c@acme.com"),
    ]
    sent = {"sent@acme.com"}
    result = select_pending(contacts, sent, limit=2)
    assert [c.email for c in result] == ["a@acme.com", "b@acme.com"]


def test_select_pending_no_limit():
    contacts = [_c("a@acme.com"), _c("b@acme.com")]
    result = select_pending(contacts, set(), limit=None)
    assert len(result) == 2
