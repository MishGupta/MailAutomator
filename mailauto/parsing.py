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


# trailing separators the PDF table leaves on company cells
_COMPANY_TRAILING = " \t,.;:-&/"


def clean_company(value: str) -> str:
    """Strip trailing separators left by the PDF table ("Estuate," -> "Estuate"),
    so a rendered sentence doesn't read "...openings at Estuate,."."""
    return value.strip().rstrip(_COMPANY_TRAILING).strip()


def find_email(cells: list) -> tuple:
    for i, c in enumerate(cells):
        m = EMAIL_RE.search((c or "").strip())
        if m:
            return i, m.group(0)
    return -1, ""


def parse_rows(rows: list) -> list:
    contacts = []
    for row in rows:
        cells = [(c or "").strip() for c in row]
        idx, email = find_email(cells)
        if idx == -1:
            continue  # header or non-data row
        before = cells[:idx]
        after = [a for a in cells[idx + 1:] if a]
        if before and before[0].isdigit():
            before = before[1:]  # drop serial number
        name = " ".join(p for p in before if p).strip()
        if len(after) >= 2:
            title = " ".join(after[:-1]).strip()
            company = clean_company(after[-1])
        elif len(after) == 1:
            title = ""
            company = clean_company(after[0])
        else:
            title = ""
            company = ""
        contacts.append(Contact(name=name, email=email, title=title, company=company))
    return contacts


def parse_pdf(path: str) -> list:
    import pdfplumber

    rows = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    rows.append(row)
    return parse_rows(rows)
