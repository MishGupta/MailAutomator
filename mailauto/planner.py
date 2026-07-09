from mailauto.parsing import is_valid_email


def select_pending(contacts: list, sent_lower: set, limit) -> list:
    pending = [
        c for c in contacts
        if is_valid_email(c.email) and c.email.strip().lower() not in sent_lower
    ]
    if isinstance(limit, int) and limit > 0:
        return pending[:limit]
    return pending
