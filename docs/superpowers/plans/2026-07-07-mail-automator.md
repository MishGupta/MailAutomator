# Mail Automator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python command-line tool that reads HR contacts from a PDF and sends each one a personalized, resume-attached email from a Gmail account, in daily batches that never double-email anyone.

**Architecture:** Two CLI entry points (`import_contacts.py`, `send_emails.py`) over a small focused package (`mailauto/`) of pure, independently testable modules: PDF/CSV contact handling, template rendering, config loading, sent-log tracking, and message building/SMTP sending. All personalization is plain token replacement; all sending state lives in `sent_log.csv` so runs are resumable and idempotent.

**Tech Stack:** Python 3.13 (stdlib `smtplib`, `email`, `csv`, `configparser`, `argparse`), `pdfplumber` for PDF table extraction, `pytest` for tests.

## Global Constraints

- Python 3.13 (installed). Only external runtime dependency: `pdfplumber`. Dev dependency: `pytest`.
- Sender is a Gmail account (`infogupta007@gmail.com`) via `smtp.gmail.com:587` STARTTLS + app password.
- Gmail free-tier limit ~500/day → default per-run cap `daily_limit = 400`.
- Personalization tokens are exactly: `{name}`, `{company}`, `{title}`, `{email}`.
- App password lives ONLY in `config.ini`, which MUST be gitignored (never committed).
- The resume file is attached to every real email.
- Sending is idempotent: `sent_log.csv` records every send; already-sent recipients are skipped on later runs.
- `--preview` is the DEFAULT mode; actually sending requires the explicit `--send` flag.
- Email address comparison for "already sent" is case-insensitive (lowercased).

---

## File Structure

```
Mail_Automator/
  HR_Contact_List.pdf        # existing input
  requirements.txt           # pdfplumber
  .gitignore                 # ignores config.ini, sent_log.csv, resume, venv, contacts.csv
  config.ini.example         # template config the user copies to config.ini
  email_template.txt         # sample template the user edits
  import_contacts.py         # CLI: PDF -> contacts.csv
  send_emails.py             # CLI: preview/test/send orchestration
  mailauto/
    __init__.py
    parsing.py               # Contact model, email validation, PDF parse, CSV read/write
    templating.py            # parse_template, render
    config.py                # Config dataclass, load_config
    sentlog.py               # load_sent, append_result
    mailer.py                # build_message, connect, send
  tests/
    test_parsing.py
    test_templating.py
    test_config.py
    test_sentlog.py
    test_mailer.py
    test_planner.py
  README.md
  docs/superpowers/...       # spec + this plan
```

---

## Task 1: Project scaffolding, git, and dependencies

**Files:**
- Create: `.gitignore`, `requirements.txt`, `mailauto/__init__.py`, `tests/__init__.py`, `config.ini.example`, `email_template.txt`
- Create: `tests/test_smoke.py`

**Interfaces:**
- Consumes: nothing.
- Produces: an installed environment with `pdfplumber` + `pytest` importable, and the `mailauto` package importable.

- [ ] **Step 1: Initialize git**

The folder is not yet a git repo.

Run:
```bash
cd /Users/mishka/Documents/Mail_Automator && git init
```
Expected: `Initialized empty Git repository ...`

- [ ] **Step 2: Create `.gitignore`** (secrets and generated files must never be committed)

```
# secrets & generated
config.ini
sent_log.csv
contacts.csv
*.resume.pdf
resume.pdf

# python
.venv/
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 3: Create `requirements.txt`**

```
pdfplumber
pytest
```

- [ ] **Step 4: Create the virtual environment and install deps**

Run:
```bash
cd /Users/mishka/Documents/Mail_Automator && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```
Expected: pip installs `pdfplumber`, `pytest` and their dependencies with no errors.

- [ ] **Step 5: Create package + test package markers**

`mailauto/__init__.py`:
```python
```
(empty file)

`tests/__init__.py`:
```python
```
(empty file)

- [ ] **Step 6: Create `config.ini.example`**

```ini
[gmail]
address = infogupta007@gmail.com
app_password = xxxx xxxx xxxx xxxx

[files]
resume = resume.pdf
template = email_template.txt
contacts = contacts.csv

[send]
daily_limit = 400
delay_seconds = 2
cc_self = false
```

- [ ] **Step 7: Create `email_template.txt`** (the sample the user edits)

```
Subject: Application for opportunities at {company}

Dear {name},

I came across your profile as {title} at {company} and wanted to reach out.
I'm keen to contribute to {company} and have attached my resume for your
consideration.

Thank you for your time.

Best regards,
Your Name
```

- [ ] **Step 8: Write a smoke test**

`tests/test_smoke.py`:
```python
def test_imports():
    import mailauto  # noqa: F401
    import pdfplumber  # noqa: F401
```

- [ ] **Step 9: Run the smoke test**

Run:
```bash
cd /Users/mishka/Documents/Mail_Automator && .venv/bin/pytest tests/test_smoke.py -q
```
Expected: PASS (1 passed).

- [ ] **Step 10: Commit**

```bash
cd /Users/mishka/Documents/Mail_Automator && git add .gitignore requirements.txt mailauto tests config.ini.example email_template.txt && git commit -m "chore: project scaffolding and dependencies"
```

---

## Task 2: Contact model, email validation, and CSV read/write

**Files:**
- Create: `mailauto/parsing.py`
- Test: `tests/test_parsing.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Contact` dataclass with str fields `name`, `email`, `title`, `company`.
  - `is_valid_email(s: str) -> bool`
  - `write_contacts_csv(path: str, contacts: list[Contact]) -> None` (columns: `name,email,title,company`)
  - `load_contacts_csv(path: str) -> list[Contact]`

- [ ] **Step 1: Write the failing tests**

`tests/test_parsing.py`:
```python
from mailauto.parsing import Contact, is_valid_email, write_contacts_csv, load_contacts_csv


def test_is_valid_email():
    assert is_valid_email("akanksha.puri@sourcefuse.com")
    assert is_valid_email("ak@8kmiles.com")
    assert not is_valid_email("not-an-email")
    assert not is_valid_email("")
    assert not is_valid_email("foo@bar")  # no TLD


def test_csv_round_trip(tmp_path):
    contacts = [
        Contact("Akanksha Puri", "akanksha.puri@sourcefuse.com",
                "Associate Director HR", "SourceFuse Technologies"),
        Contact("Akhil Jogiparthi", "akhil@ibhubs.co",
                "Vice President - Talent Accelerator", "iB Hubs"),
    ]
    p = tmp_path / "contacts.csv"
    write_contacts_csv(str(p), contacts)
    loaded = load_contacts_csv(str(p))
    assert loaded == contacts
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/mishka/Documents/Mail_Automator && .venv/bin/pytest tests/test_parsing.py -q
```
Expected: FAIL (ImportError / cannot import `Contact`).

- [ ] **Step 3: Write minimal implementation**

`mailauto/parsing.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/mishka/Documents/Mail_Automator && .venv/bin/pytest tests/test_parsing.py -q
```
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
cd /Users/mishka/Documents/Mail_Automator && git add mailauto/parsing.py tests/test_parsing.py && git commit -m "feat: contact model, email validation, csv io"
```

---

## Task 3: PDF row parsing heuristic

**Files:**
- Modify: `mailauto/parsing.py`
- Test: `tests/test_parsing.py`

**Interfaces:**
- Consumes: `Contact` from Task 2.
- Produces:
  - `find_email(cells: list[str]) -> tuple[int, str]` (index of the cell containing an email + the email, or `(-1, "")`)
  - `parse_rows(rows: list[list[str]]) -> list[Contact]` (row = list of cell strings; anchors on the email cell)
  - `parse_pdf(path: str) -> list[Contact]` (uses `pdfplumber` to extract table rows, then `parse_rows`)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_parsing.py`:
```python
from mailauto.parsing import find_email, parse_rows


def test_find_email():
    assert find_email(["1", "Jane", "jane@acme.com", "HR", "Acme"]) == (2, "jane@acme.com")
    assert find_email(["SNo", "Name", "Email", "Title", "Company"]) == (-1, "")


def test_parse_rows_normal():
    rows = [
        ["SNo", "Name", "Email", "Title", "Company"],  # header, skipped
        ["1", "Akanksha Puri", "akanksha.puri@sourcefuse.com",
         "Associate Director HR", "SourceFuse Technologies"],
    ]
    out = parse_rows(rows)
    assert len(out) == 1
    assert out[0] == Contact("Akanksha Puri", "akanksha.puri@sourcefuse.com",
                             "Associate Director HR", "SourceFuse Technologies")


def test_parse_rows_skips_rows_without_email():
    rows = [["5", "John Doe", "not-an-email", "Head HR", "Acme"]]
    assert parse_rows(rows) == []


def test_parse_rows_split_title_cells():
    # pdfplumber sometimes splits a long title across cells; company is always last
    rows = [["3", "Akhil", "akhil@ibhubs.co",
             "Vice President -", "Talent Accelerator", "iB Hubs"]]
    out = parse_rows(rows)
    assert out[0].title == "Vice President - Talent Accelerator"
    assert out[0].company == "iB Hubs"
    assert out[0].name == "Akhil"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/mishka/Documents/Mail_Automator && .venv/bin/pytest tests/test_parsing.py -q
```
Expected: FAIL (cannot import `find_email` / `parse_rows`).

- [ ] **Step 3: Write minimal implementation**

Append to `mailauto/parsing.py`:
```python
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
            company = after[-1].strip()
        elif len(after) == 1:
            title = ""
            company = after[0].strip()
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/mishka/Documents/Mail_Automator && .venv/bin/pytest tests/test_parsing.py -q
```
Expected: PASS (all parsing tests pass).

- [ ] **Step 5: Commit**

```bash
cd /Users/mishka/Documents/Mail_Automator && git add mailauto/parsing.py tests/test_parsing.py && git commit -m "feat: pdf row parsing heuristic"
```

---

## Task 4: `import_contacts.py` CLI + real-PDF verification

**Files:**
- Create: `import_contacts.py`

**Interfaces:**
- Consumes: `parse_pdf`, `write_contacts_csv` from `mailauto.parsing`.
- Produces: `contacts.csv` in the project root.

- [ ] **Step 1: Write the CLI**

`import_contacts.py`:
```python
import argparse
import os
import sys

from mailauto.parsing import parse_pdf, write_contacts_csv


def main(argv=None):
    ap = argparse.ArgumentParser(description="Extract HR contacts from a PDF into contacts.csv")
    ap.add_argument("--pdf", default="HR_Contact_List.pdf", help="input PDF path")
    ap.add_argument("--out", default="contacts.csv", help="output CSV path")
    args = ap.parse_args(argv)

    if not os.path.exists(args.pdf):
        print(f"ERROR: PDF not found: {args.pdf}", file=sys.stderr)
        return 1
    if os.path.exists(args.out):
        print(f"WARNING: {args.out} already exists and will be overwritten.")

    contacts = parse_pdf(args.pdf)
    write_contacts_csv(args.out, contacts)
    print(f"Extracted {len(contacts)} contacts -> {args.out}")
    if contacts:
        c = contacts[0]
        print(f"First row: name={c.name!r} email={c.email!r} title={c.title!r} company={c.company!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run it against the real PDF**

Run:
```bash
cd /Users/mishka/Documents/Mail_Automator && .venv/bin/python import_contacts.py
```
Expected: prints `Extracted <N> contacts -> contacts.csv` where N is close to 1842, and a plausible first row.

- [ ] **Step 3: Sanity-check the output**

Run:
```bash
cd /Users/mishka/Documents/Mail_Automator && .venv/bin/python -c "from mailauto.parsing import load_contacts_csv; cs=load_contacts_csv('contacts.csv'); print('rows',len(cs)); [print(c) for c in cs[:3]]; import sys; bad=[c for c in cs if '@' not in c.email]; print('rows missing email:',len(bad))"
```
Expected: row count ≈ 1842, first 3 rows have sensible name/email/title/company, and `rows missing email: 0`.

**If parsing looks wrong** (columns merged/shifted, low row count): inspect what pdfplumber returns with
`.venv/bin/python -c "import pdfplumber; p=pdfplumber.open('HR_Contact_List.pdf'); print(p.pages[0].extract_tables()[0][:3])"`
and adjust `parse_rows` / the `extract_tables` settings in Task 3 (e.g. pass explicit `table_settings`), then re-run the Task 3 tests before continuing.

- [ ] **Step 4: Commit** (contacts.csv is gitignored, so only the script is committed)

```bash
cd /Users/mishka/Documents/Mail_Automator && git add import_contacts.py && git commit -m "feat: import_contacts CLI (pdf -> contacts.csv)"
```

---

## Task 5: Template parsing and rendering

**Files:**
- Create: `mailauto/templating.py`
- Test: `tests/test_templating.py`

**Interfaces:**
- Consumes: `Contact` from `mailauto.parsing`.
- Produces:
  - `parse_template(text: str) -> tuple[str, str]` returns `(subject_template, body_template)`; raises `ValueError` if the first line is not `Subject: ...`.
  - `render(subject_template: str, body_template: str, contact: Contact) -> tuple[str, str]` returns the filled `(subject, body)` via replacement of `{name}`, `{company}`, `{title}`, `{email}`.

- [ ] **Step 1: Write the failing tests**

`tests/test_templating.py`:
```python
from mailauto.parsing import Contact
from mailauto.templating import parse_template, render
import pytest


TEMPLATE = """Subject: Application for opportunities at {company}

Dear {name},

I saw your role as {title} at {company}. Reach me at {email}.
"""


def test_parse_template_splits_subject_and_body():
    subject, body = parse_template(TEMPLATE)
    assert subject == "Application for opportunities at {company}"
    assert body.startswith("Dear {name},")
    assert "{title}" in body


def test_parse_template_requires_subject():
    with pytest.raises(ValueError):
        parse_template("No subject line here\n\nBody")


def test_render_fills_all_tokens():
    subject_t, body_t = parse_template(TEMPLATE)
    c = Contact("Akanksha Puri", "akanksha.puri@sourcefuse.com",
                "Associate Director HR", "SourceFuse Technologies")
    subject, body = render(subject_t, body_t, c)
    assert subject == "Application for opportunities at SourceFuse Technologies"
    assert "Dear Akanksha Puri," in body
    assert "Associate Director HR" in body
    assert "akanksha.puri@sourcefuse.com" in body
    assert "{" not in body  # no leftover tokens


def test_render_handles_empty_field():
    subject_t, body_t = parse_template(TEMPLATE)
    c = Contact("Jane", "jane@acme.com", "", "Acme")
    subject, body = render(subject_t, body_t, c)
    assert "role as  at Acme" in body  # empty title collapses cleanly
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/mishka/Documents/Mail_Automator && .venv/bin/pytest tests/test_templating.py -q
```
Expected: FAIL (cannot import `mailauto.templating`).

- [ ] **Step 3: Write minimal implementation**

`mailauto/templating.py`:
```python
def parse_template(text: str) -> tuple:
    lines = text.splitlines()
    if not lines or not lines[0].lower().startswith("subject:"):
        raise ValueError("Template must start with 'Subject: ...' on the first line")
    subject_template = lines[0].split(":", 1)[1].strip()
    rest = lines[1:]
    i = 0
    while i < len(rest) and rest[i].strip() == "":
        i += 1
    body_template = "\n".join(rest[i:])
    return subject_template, body_template


def _fill(template: str, contact) -> str:
    return (template
            .replace("{name}", contact.name)
            .replace("{company}", contact.company)
            .replace("{title}", contact.title)
            .replace("{email}", contact.email))


def render(subject_template: str, body_template: str, contact) -> tuple:
    return _fill(subject_template, contact), _fill(body_template, contact)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/mishka/Documents/Mail_Automator && .venv/bin/pytest tests/test_templating.py -q
```
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
cd /Users/mishka/Documents/Mail_Automator && git add mailauto/templating.py tests/test_templating.py && git commit -m "feat: template parsing and rendering"
```

---

## Task 6: Config loader

**Files:**
- Create: `mailauto/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Config` dataclass: `address, app_password, resume_path, template_path, contacts_path, daily_limit(int), delay_seconds(float), cc_self(bool)`.
  - `load_config(path: str = "config.ini") -> Config`; raises `FileNotFoundError` if config or any referenced file (resume/template/contacts) is missing, `ValueError` if a required key is absent.

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`:
```python
import pytest
from mailauto.config import load_config, Config


def _write_config(tmp_path, resume, template, contacts, extra="daily_limit = 250\ndelay_seconds = 1.5\ncc_self = true"):
    cfg = tmp_path / "config.ini"
    cfg.write_text(
        "[gmail]\n"
        "address = infogupta007@gmail.com\n"
        "app_password = abcd efgh ijkl mnop\n"
        "[files]\n"
        f"resume = {resume}\n"
        f"template = {template}\n"
        f"contacts = {contacts}\n"
        "[send]\n"
        f"{extra}\n"
    )
    return cfg


def test_load_config_ok(tmp_path):
    r = tmp_path / "resume.pdf"; r.write_text("x")
    t = tmp_path / "email_template.txt"; t.write_text("Subject: hi\n\nbody")
    c = tmp_path / "contacts.csv"; c.write_text("name,email,title,company\n")
    cfg = _write_config(tmp_path, r, t, c)
    conf = load_config(str(cfg))
    assert isinstance(conf, Config)
    assert conf.address == "infogupta007@gmail.com"
    assert conf.app_password == "abcd efgh ijkl mnop"
    assert conf.daily_limit == 250
    assert conf.delay_seconds == 1.5
    assert conf.cc_self is True


def test_load_config_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(str(tmp_path / "nope.ini"))


def test_load_config_missing_resume(tmp_path):
    t = tmp_path / "email_template.txt"; t.write_text("Subject: hi\n\nbody")
    c = tmp_path / "contacts.csv"; c.write_text("name,email,title,company\n")
    cfg = _write_config(tmp_path, tmp_path / "missing.pdf", t, c)
    with pytest.raises(FileNotFoundError):
        load_config(str(cfg))
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/mishka/Documents/Mail_Automator && .venv/bin/pytest tests/test_config.py -q
```
Expected: FAIL (cannot import `mailauto.config`).

- [ ] **Step 3: Write minimal implementation**

`mailauto/config.py`:
```python
import configparser
import os
from dataclasses import dataclass


@dataclass
class Config:
    address: str
    app_password: str
    resume_path: str
    template_path: str
    contacts_path: str
    daily_limit: int
    delay_seconds: float
    cc_self: bool


def load_config(path: str = "config.ini") -> Config:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Config file not found: {path}. Copy config.ini.example to config.ini and fill it in."
        )
    cp = configparser.ConfigParser()
    cp.read(path)
    try:
        address = cp["gmail"]["address"].strip()
        app_password = cp["gmail"]["app_password"].strip()
        resume_path = cp["files"]["resume"].strip()
        template_path = cp["files"].get("template", "email_template.txt").strip()
        contacts_path = cp["files"].get("contacts", "contacts.csv").strip()
        daily_limit = cp["send"].getint("daily_limit", 400)
        delay_seconds = cp["send"].getfloat("delay_seconds", 2.0)
        cc_self = cp["send"].getboolean("cc_self", False)
    except KeyError as e:
        raise ValueError(f"Missing required config value: {e}")

    for label, p in [("resume", resume_path), ("template", template_path), ("contacts", contacts_path)]:
        if not os.path.exists(p):
            raise FileNotFoundError(f"{label} file not found: {p}")

    return Config(address, app_password, resume_path, template_path,
                  contacts_path, daily_limit, delay_seconds, cc_self)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/mishka/Documents/Mail_Automator && .venv/bin/pytest tests/test_config.py -q
```
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
cd /Users/mishka/Documents/Mail_Automator && git add mailauto/config.py tests/test_config.py && git commit -m "feat: config loader with validation"
```

---

## Task 7: Sent-log tracking

**Files:**
- Create: `mailauto/sentlog.py`
- Test: `tests/test_sentlog.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `load_sent(path: str = "sent_log.csv") -> set[str]` — lowercased emails whose `status == "sent"`; empty set if file missing.
  - `append_result(path: str, email: str, status: str, error: str = "") -> None` — appends one row; writes a header if the file is new. Columns: `timestamp,email,status,error`.

- [ ] **Step 1: Write the failing tests**

`tests/test_sentlog.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/mishka/Documents/Mail_Automator && .venv/bin/pytest tests/test_sentlog.py -q
```
Expected: FAIL (cannot import `mailauto.sentlog`).

- [ ] **Step 3: Write minimal implementation**

`mailauto/sentlog.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/mishka/Documents/Mail_Automator && .venv/bin/pytest tests/test_sentlog.py -q
```
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
cd /Users/mishka/Documents/Mail_Automator && git add mailauto/sentlog.py tests/test_sentlog.py && git commit -m "feat: sent-log tracking"
```

---

## Task 8: Mailer — build message and SMTP send

**Files:**
- Create: `mailauto/mailer.py`
- Test: `tests/test_mailer.py`

**Interfaces:**
- Consumes: nothing (operates on primitives).
- Produces:
  - `build_message(from_addr, to_addr, subject, body, resume_path, cc_self=None) -> email.message.EmailMessage` with the resume attached (filename = basename of `resume_path`); sets `Cc` when `cc_self` is truthy.
  - `connect(address, app_password) -> smtplib.SMTP` — connects to `smtp.gmail.com:587`, STARTTLS, logs in.
  - `send(smtp, message) -> None` — `smtp.send_message(message)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_mailer.py`:
```python
import smtplib
from mailauto import mailer


def test_build_message_has_headers_body_and_attachment(tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fake")
    msg = mailer.build_message(
        "me@gmail.com", "hr@acme.com", "Hello Acme", "Body text here",
        str(resume), cc_self="me@gmail.com",
    )
    assert msg["From"] == "me@gmail.com"
    assert msg["To"] == "hr@acme.com"
    assert msg["Cc"] == "me@gmail.com"
    assert msg["Subject"] == "Hello Acme"
    assert "Body text here" in msg.get_body(preferencelist=("plain",)).get_content()
    atts = list(msg.iter_attachments())
    assert len(atts) == 1
    assert atts[0].get_filename() == "resume.pdf"


def test_build_message_no_cc(tmp_path):
    resume = tmp_path / "resume.pdf"; resume.write_bytes(b"x")
    msg = mailer.build_message("me@gmail.com", "hr@acme.com", "S", "B", str(resume))
    assert msg["Cc"] is None


class _FakeSMTP:
    calls = []

    def __init__(self, host, port):
        _FakeSMTP.calls.append(("init", host, port))

    def starttls(self):
        _FakeSMTP.calls.append(("starttls",))

    def login(self, addr, pw):
        _FakeSMTP.calls.append(("login", addr, pw))

    def send_message(self, msg):
        _FakeSMTP.calls.append(("send_message", msg["To"]))


def test_connect_and_send(monkeypatch):
    _FakeSMTP.calls = []
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    smtp = mailer.connect("me@gmail.com", "app pass word here")
    assert ("init", "smtp.gmail.com", 587) in _FakeSMTP.calls
    assert ("starttls",) in _FakeSMTP.calls
    assert ("login", "me@gmail.com", "app pass word here") in _FakeSMTP.calls

    class M(dict):
        pass
    m = M(); m["To"] = "hr@acme.com"
    mailer.send(smtp, m)
    assert ("send_message", "hr@acme.com") in _FakeSMTP.calls
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/mishka/Documents/Mail_Automator && .venv/bin/pytest tests/test_mailer.py -q
```
Expected: FAIL (cannot import `mailauto.mailer`).

- [ ] **Step 3: Write minimal implementation**

`mailauto/mailer.py`:
```python
import mimetypes
import os
import smtplib
from email.message import EmailMessage


def build_message(from_addr, to_addr, subject, body, resume_path, cc_self=None):
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    if cc_self:
        msg["Cc"] = cc_self
    msg["Subject"] = subject
    msg.set_content(body)

    ctype, _ = mimetypes.guess_type(resume_path)
    maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
    with open(resume_path, "rb") as f:
        data = f.read()
    msg.add_attachment(data, maintype=maintype, subtype=subtype,
                       filename=os.path.basename(resume_path))
    return msg


def connect(address, app_password):
    smtp = smtplib.SMTP("smtp.gmail.com", 587)
    smtp.starttls()
    smtp.login(address, app_password)
    return smtp


def send(smtp, message):
    smtp.send_message(message)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/mishka/Documents/Mail_Automator && .venv/bin/pytest tests/test_mailer.py -q
```
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
cd /Users/mishka/Documents/Mail_Automator && git add mailauto/mailer.py tests/test_mailer.py && git commit -m "feat: mailer (build message + smtp send)"
```

---

## Task 9: Pending-selection helper

**Files:**
- Create: `mailauto/planner.py`
- Test: `tests/test_planner.py`

**Interfaces:**
- Consumes: `Contact`, `is_valid_email` from `mailauto.parsing`.
- Produces: `select_pending(contacts: list[Contact], sent_lower: set[str], limit: int | None) -> list[Contact]` — drops invalid emails and already-sent (case-insensitive), preserves order, caps at `limit` when `limit` is a positive int.

- [ ] **Step 1: Write the failing tests**

`tests/test_planner.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/mishka/Documents/Mail_Automator && .venv/bin/pytest tests/test_planner.py -q
```
Expected: FAIL (cannot import `mailauto.planner`).

- [ ] **Step 3: Write minimal implementation**

`mailauto/planner.py`:
```python
from mailauto.parsing import is_valid_email


def select_pending(contacts: list, sent_lower: set, limit) -> list:
    pending = [
        c for c in contacts
        if is_valid_email(c.email) and c.email.strip().lower() not in sent_lower
    ]
    if isinstance(limit, int) and limit > 0:
        return pending[:limit]
    return pending
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/mishka/Documents/Mail_Automator && .venv/bin/pytest tests/test_planner.py -q
```
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
cd /Users/mishka/Documents/Mail_Automator && git add mailauto/planner.py tests/test_planner.py && git commit -m "feat: pending-selection helper"
```

---

## Task 10: `send_emails.py` orchestration CLI

**Files:**
- Create: `send_emails.py`

**Interfaces:**
- Consumes: `load_config` (config), `parse_template`/`render` (templating), `load_contacts_csv` (parsing), `load_sent`/`append_result` (sentlog), `build_message`/`connect`/`send` (mailer), `select_pending` (planner).
- Produces: the CLI with modes `--preview` (default), `--dry-run`, `--test`, `--send`, and `--limit N`.

- [ ] **Step 1: Write the CLI**

`send_emails.py`:
```python
import argparse
import sys
import time
import smtplib

from mailauto.config import load_config
from mailauto.parsing import load_contacts_csv
from mailauto.templating import parse_template, render
from mailauto.sentlog import load_sent, append_result
from mailauto.planner import select_pending
from mailauto import mailer


def _load_all(args):
    conf = load_config(args.config)
    with open(conf.template_path, encoding="utf-8") as f:
        subject_t, body_t = parse_template(f.read())
    contacts = load_contacts_csv(conf.contacts_path)
    sent = load_sent()
    return conf, subject_t, body_t, contacts, sent


def cmd_preview(conf, subject_t, body_t, contacts, sent, n=3):
    pending = select_pending(contacts, sent, None)
    print(f"{len(contacts)} contacts, {len(sent)} already sent, {len(pending)} pending.\n")
    for c in pending[:n]:
        subject, body = render(subject_t, body_t, c)
        print("=" * 60)
        print(f"To: {c.email}")
        print(f"Subject: {subject}")
        print(f"[attachment: {conf.resume_path}]")
        print("-" * 60)
        print(body)
        print()
    print(f"(Preview only — nothing sent. Showed {min(n, len(pending))} of {len(pending)}.)")


def cmd_dry_run(conf, contacts, sent):
    pending = select_pending(contacts, sent, None)
    todays = select_pending(contacts, sent, conf.daily_limit)
    print(f"Total contacts:   {len(contacts)}")
    print(f"Already sent:     {len(sent)}")
    print(f"Pending:          {len(pending)}")
    print(f"Daily limit:      {conf.daily_limit}")
    print(f"This run would send: {len(todays)}")


def cmd_test(conf, subject_t, body_t, contacts):
    sample = contacts[0] if contacts else None
    if sample is None:
        print("No contacts to build a sample from.", file=sys.stderr)
        return 1
    subject, body = render(subject_t, body_t, sample)
    msg = mailer.build_message(conf.address, conf.address, f"[TEST] {subject}",
                               body, conf.resume_path,
                               cc_self=None)
    try:
        smtp = mailer.connect(conf.address, conf.app_password)
    except smtplib.SMTPAuthenticationError:
        print("ERROR: Gmail rejected the login. Check the app password in config.ini "
              "(needs 2-Step Verification + an App Password, not your normal password).",
              file=sys.stderr)
        return 1
    try:
        mailer.send(smtp, msg)
    finally:
        smtp.quit()
    print(f"Test email sent to yourself ({conf.address}). Check your inbox.")
    return 0


def cmd_send(conf, subject_t, body_t, contacts, sent):
    todays = select_pending(contacts, sent, conf.daily_limit)
    if not todays:
        print("Nothing to send — everyone pending is already done or the list is empty.")
        return 0
    print(f"Sending {len(todays)} emails (limit {conf.daily_limit})...")
    try:
        smtp = mailer.connect(conf.address, conf.app_password)
    except smtplib.SMTPAuthenticationError:
        print("ERROR: Gmail rejected the login. Check the app password in config.ini.",
              file=sys.stderr)
        return 1
    ok = 0
    failed = 0
    try:
        for i, c in enumerate(todays, 1):
            subject, body = render(subject_t, body_t, c)
            cc = conf.address if conf.cc_self else None
            try:
                msg = mailer.build_message(conf.address, c.email, subject, body,
                                           conf.resume_path, cc_self=cc)
                mailer.send(smtp, msg)
                append_result("sent_log.csv", c.email, "sent")
                ok += 1
                print(f"  [{i}/{len(todays)}] sent -> {c.email}")
            except Exception as e:  # one bad address must not stop the batch
                append_result("sent_log.csv", c.email, "error", str(e))
                failed += 1
                print(f"  [{i}/{len(todays)}] FAILED -> {c.email}: {e}", file=sys.stderr)
            time.sleep(conf.delay_seconds)
    finally:
        smtp.quit()
    print(f"\nDone. Sent {ok}, failed {failed}. Run again tomorrow for the next batch.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Send personalized HR outreach emails.")
    ap.add_argument("--config", default="config.ini")
    ap.add_argument("--limit", type=int, default=None, help="override daily_limit for this run")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--preview", action="store_true", help="show sample emails (default)")
    mode.add_argument("--dry-run", action="store_true", help="show counts only")
    mode.add_argument("--test", action="store_true", help="send one test email to yourself")
    mode.add_argument("--send", action="store_true", help="actually send today's batch")
    args = ap.parse_args(argv)

    try:
        conf, subject_t, body_t, contacts, sent = _load_all(args)
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if args.limit is not None:
        conf.daily_limit = args.limit

    if args.send:
        return cmd_send(conf, subject_t, body_t, contacts, sent)
    if args.test:
        return cmd_test(conf, subject_t, body_t, contacts)
    if args.dry_run:
        cmd_dry_run(conf, contacts, sent)
        return 0
    # default: preview
    cmd_preview(conf, subject_t, body_t, contacts, sent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Verify the full test suite still passes**

Run:
```bash
cd /Users/mishka/Documents/Mail_Automator && .venv/bin/pytest -q
```
Expected: PASS (all tests from Tasks 1–9 pass).

- [ ] **Step 3: Manually verify preview + dry-run with a dummy resume**

Run:
```bash
cd /Users/mishka/Documents/Mail_Automator && cp config.ini.example config.ini && printf '%%PDF-1.4 dummy' > resume.pdf && .venv/bin/python send_emails.py --preview && .venv/bin/python send_emails.py --dry-run
```
Expected: `--preview` prints 3 fully-rendered sample emails with real company names swapped in and `[attachment: resume.pdf]`; `--dry-run` prints counts with "This run would send: 400". (No email is sent — the app password is still a placeholder.)

- [ ] **Step 4: Commit** (config.ini and resume.pdf are gitignored)

```bash
cd /Users/mishka/Documents/Mail_Automator && git add send_emails.py && git commit -m "feat: send_emails orchestration CLI"
```

---

## Task 11: README and end-to-end usage docs

**Files:**
- Create: `README.md`

**Interfaces:**
- Consumes: everything above.
- Produces: the human runbook.

- [ ] **Step 1: Write the README**

`README.md`:
```markdown
# Mail Automator

Send personalized, resume-attached outreach emails to HR contacts from a PDF list,
in daily batches, from your Gmail account.

## One-time setup

1. Install: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
2. Turn on 2-Step Verification on the Gmail account, then create an **App Password**
   at https://myaccount.google.com/apppasswords (16 characters).
3. `cp config.ini.example config.ini` and fill in `address` + `app_password`.
4. Put your resume in the folder (default name `resume.pdf`, or set `resume` in config.ini).
5. Edit `email_template.txt` — keep the `Subject:` first line and use `{name}`,
   `{company}`, `{title}`, `{email}` where you want values inserted.

## Build the contact list (once)

```bash
.venv/bin/python import_contacts.py      # HR_Contact_List.pdf -> contacts.csv
```
Open `contacts.csv` in a spreadsheet and remove/fix any bad rows.

## Send (repeat daily until done)

```bash
.venv/bin/python send_emails.py --preview   # see 3 finished sample emails (sends nothing)
.venv/bin/python send_emails.py --test      # send ONE test email to yourself
.venv/bin/python send_emails.py --dry-run   # counts: pending / would-send
.venv/bin/python send_emails.py --send      # send today's batch (default 400), then stop
```

- Already-emailed people are recorded in `sent_log.csv` and skipped automatically.
- ~1,842 contacts ÷ 400/day ≈ 5 daily runs.
- Override the batch size for one run: `--send --limit 200`.

## Notes
- `config.ini`, `sent_log.csv`, `contacts.csv`, and `resume.pdf` are gitignored
  (they contain secrets or personal data).
- Gmail free accounts cap at ~500 sends/day; Workspace accounts ~2,000.
```

- [ ] **Step 2: Final full-suite run**

Run:
```bash
cd /Users/mishka/Documents/Mail_Automator && .venv/bin/pytest -q
```
Expected: PASS (entire suite green).

- [ ] **Step 3: Commit**

```bash
cd /Users/mishka/Documents/Mail_Automator && git add README.md && git commit -m "docs: usage README"
```

---

## Self-Review Notes

**Spec coverage:**
- Sender via Gmail app password → Tasks 6 (config), 8 (mailer). ✓
- PDF → contacts → Tasks 3, 4. ✓
- Placeholder personalization `{name}/{company}/{title}` (+ `{email}`) → Task 5. ✓
- Resume attached to every email → Task 8 `build_message`, wired in Task 10. ✓
- Preview default, `--send` required → Task 10. ✓
- Test-to-self before real send → Task 10 `cmd_test`, README. ✓
- Daily batching ~400 → Tasks 6 (`daily_limit`), 9 (`select_pending`), 10. ✓
- Never double-email (idempotent) → Task 7 (sentlog), 9, 10. ✓
- Per-contact error isolation, auth-failure message, missing-file refusal → Tasks 6, 10. ✓
- CC-self optional toggle → Tasks 6 (`cc_self`), 8, 10. ✓
- Tests for template rendering + PDF/CSV parsing → Tasks 2, 3, 5. ✓

**Type consistency:** `Contact(name, email, title, company)` used identically across Tasks 2–10. `select_pending(contacts, sent_lower, limit)`, `load_sent`→lowercased set, `build_message(..., cc_self=)`, `connect`/`send` names match between definition (Task 8) and use (Task 10). ✓

**Placeholder scan:** No TBD/TODO; every code step contains complete code. ✓

---

## Post-Implementation Amendments

During subagent review, three defects latent in this plan's example code were caught
and fixed in the shipped implementation. If this plan is ever re-run, apply these:

- **Task 6 (config):** `cp["send"].getint(...)` raises `KeyError` when the whole
  `[send]` section is absent, wrongly failing a valid minimal config. Shipped code uses
  `cp.getint("send", key, fallback=...)` (which defaults on a missing section too) and
  `ConfigParser(interpolation=None)` so a `%` in a password/path can't crash. (commit `ebdc397`)
- **Task 7 (sentlog):** a crash leaving a 0-byte `sent_log.csv` could make `load_sent`
  misparse and silently return an empty set → mass duplicate sends. Shipped code treats
  a 0-byte file as new (writes the header) and raises `ValueError` on a malformed header
  rather than continuing. (commit `f94f2ef`)
- **Task 10 (send CLI):** `--limit 0`/negative disabled the daily cap entirely (`select_pending`
  treats non-positive as "no cap") and would email the whole list at once. Shipped code
  adds `validate_limit()` rejecting non-positive `--limit`, guards `--test`'s send, and
  centralizes the `sent_log.csv` path. (commit `6edd128`)
```

