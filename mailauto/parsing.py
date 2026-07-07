import csv
import re
from dataclasses import dataclass

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

CSV_FIELDS = ["name", "email", "title", "company"]


@dataclass
class Contact:
    name: str
    email: str
    title: str
    company: str


def is_valid_email(s: str) -> bool:
    if not s:
        return False
    return bool(EMAIL_RE.fullmatch(s.strip()))


def write_contacts_csv(path: str, contacts: list) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for c in contacts:
            w.writerow({"name": c.name, "email": c.email,
                        "title": c.title, "company": c.company})


def load_contacts_csv(path: str) -> list:
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out.append(Contact(
                name=(row.get("name") or "").strip(),
                email=(row.get("email") or "").strip(),
                title=(row.get("title") or "").strip(),
                company=(row.get("company") or "").strip(),
            ))
    return out
