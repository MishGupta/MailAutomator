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
    """Load contacts, refusing a header that doesn't match CSV_FIELDS.

    csv.DictReader otherwise yields None for any column whose name doesn't
    match -- a capitalised "Email", an "E-mail" typo, or a deleted header row
    -- so every contact would silently come out with email="" and nothing
    would ever be pending. Mirrors the header check in sentlog.py for the
    same reason: a corrupt/mismatched header must be a loud failure, not a
    silent no-op.

    encoding="utf-8-sig" rather than "utf-8": a spreadsheet-saved CSV commonly
    carries a leading BOM, which "utf-8" leaves attached to the first header
    name ("﻿name") and would otherwise fail this exact check even for an
    otherwise-correct file.

    An empty or missing file is left alone: DictReader.fieldnames is None for
    an empty file, and a missing path already raises FileNotFoundError from
    open() before this check runs.
    """
    out = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is not None and reader.fieldnames != CSV_FIELDS:
            raise ValueError(
                f"{path} has the wrong header: found {reader.fieldnames!r}, expected "
                f"{CSV_FIELDS!r}. Open it in a spreadsheet and fix the header row "
                "(it must be exactly these lowercase column names, in this order) "
                "before sending."
            )
        for row in reader:
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
