import csv
import os
from datetime import datetime

FIELDS = ["timestamp", "email", "status", "error"]
MAX_ATTEMPTS = 3


def _read_rows(path: str):
    """Yield (status, normalized_email) for each row, or raise on a bad header."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != FIELDS:
            raise ValueError(
                f"{path} is malformed: header is {reader.fieldnames!r}, expected {FIELDS!r}. "
                "Refusing to continue — a corrupt log could cause contacts to be emailed twice. "
                "Inspect and repair the file before sending."
            )
        return [
            ((row.get("status") or "").strip(), (row.get("email") or "").strip().lower())
            for row in reader
        ]


def load_sent(path: str = "sent_log.csv") -> set:
    return {email for status, email in _read_rows(path) if status == "sent"}


def load_done(path: str = "sent_log.csv", max_attempts: int = MAX_ATTEMPTS) -> set:
    """Addresses that must not be contacted again.

    An address is done when it was delivered, or when it has failed
    `max_attempts` times. The retry budget exists because a failure does not say
    why: the 8 failures on record all died to a dropped socket mid-batch, and
    deserve another go, while a genuinely dead address would otherwise be
    retried every weekday forever and keep the run from ever completing.
    """
    rows = _read_rows(path)
    delivered = set()
    failures = {}
    for status, email in rows:
        if status == "sent":
            delivered.add(email)
        elif status == "error":
            failures[email] = failures.get(email, 0) + 1
    exhausted = {e for e, n in failures.items() if n >= max_attempts}
    return delivered | exhausted


def append_result(path: str, email: str, status: str, error: str = "") -> None:
    is_new = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if is_new:
            w.writeheader()
        w.writerow({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "email": email,
            "status": status,
            "error": error,
        })
