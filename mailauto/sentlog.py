import csv
import os
from datetime import datetime

FIELDS = ["timestamp", "email", "status", "error"]


def load_sent(path: str = "sent_log.csv") -> set:
    sent = set()
    if not os.path.exists(path):
        return sent
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if (row.get("status") or "").strip() == "sent":
                sent.add((row.get("email") or "").strip().lower())
    return sent


def append_result(path: str, email: str, status: str, error: str = "") -> None:
    is_new = not os.path.exists(path)
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
