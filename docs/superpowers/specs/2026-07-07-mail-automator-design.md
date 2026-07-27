# Mail Automator — Design

**Date:** 2026-07-07
**Status:** Approved

## Purpose

Send personalized cold-outreach emails to a large list of HR contacts (job-search
outreach). Contacts come from a PDF; each email is personalized per recipient using
fill-in placeholders, carries a resume attachment, and is sent from the user's Gmail
in daily batches that respect Gmail's ~500/day limit — without ever emailing the same
person twice.

## Confirmed requirements

- **Sender:** `infogupta007@gmail.com` via Gmail SMTP using an app password.
- **Contacts source:** `HR_Contact_List.pdf` (~1,842 rows: Name, Email, Title, Company).
- **Personalization:** fill-in placeholders `{name}`, `{company}`, `{title}` in a
  user-editable template. No AI generation.
- **Attachment:** one resume file (PDF) attached to every email.
- **Send flow:** preview samples → send in daily batches (~400) → skip anyone already
  emailed. Two-step (review the parsed contacts before sending).

## Stack

- **Python 3** (3.13.5 already installed).
- **Standard library** `smtplib` + `email` for sending (no external send dependency).
- **PDF parsing:** `pdfplumber` (pip) preferred for robust table extraction, with the
  already-installed `pdftotext -layout` (poppler) as a fallback parsing path. Output is
  reviewed by the user as CSV, so parsing need only be good-enough + human-verified.
- Terminal scripts run from the project folder. No web app, no server.

## Components

### 1. `import_contacts.py`  (run once)
- Input: `HR_Contact_List.pdf`
- Output: `contacts.csv` with columns `name, email, title, company`.
- Extracts each row; email column is validated by regex (must contain a valid address).
- User reviews/edits `contacts.csv` in a spreadsheet before sending.
- Re-runnable (overwrites `contacts.csv`; warns if it already exists).

### 2. `send_emails.py`  (run daily until done)
- Inputs: `contacts.csv`, `email_template.txt`, `config.ini`, resume file, `sent_log.csv`.
- Modes:
  - `--preview` (DEFAULT): render 3 fully-personalized sample emails to the terminal;
    send nothing.
  - `--test`: send one/a few emails to the user's own address to verify formatting +
    attachment before any real outreach.
  - `--send`: send today's batch (up to the daily limit), then stop.
  - `--limit N`: override the per-run cap (default 400, safely under 500).
  - `--dry-run`: like preview but over the whole pending set (counts only, no send).
- Behavior:
  - Loads `sent_log.csv` and skips every already-sent recipient.
  - Renders template placeholders per contact.
  - Sends via Gmail SMTP (TLS) with the resume attached.
  - Small delay (~2s) between sends.
  - Appends every result to `sent_log.csv` (timestamp, email, status, error-if-any).

### User-supplied files (no code editing)
- `email_template.txt` — first line `Subject: ...`, blank line, then body with
  `{name}` / `{company}` / `{title}` placeholders.
- `config.ini` — `[gmail] address`, `app_password`; `[files] resume`, `template`,
  `contacts`; `[send] daily_limit`, `delay_seconds`, optional `cc_self`.
  Kept separate so the app password never lives in code.
- Resume PDF — placed in the folder, referenced from `config.ini`.

## Data flow

```
HR_Contact_List.pdf
      │  import_contacts.py
      ▼
  contacts.csv  ──(user reviews)──┐
                                  │
email_template.txt ──┐            │
config.ini ──────────┼─ send_emails.py ──SMTP──> Gmail
resume.pdf ──────────┘            │
                                  ▼
                             sent_log.csv  ──(skip on next run)──┐
                                  ▲                              │
                                  └──────────────────────────────┘
```

## Error handling & safety

- **Preview is the default**; sending requires an explicit `--send`.
- **Test-to-self first**: verify formatting/attachment before real outreach.
- **Idempotent**: `sent_log.csv` guarantees no recipient is emailed twice, even across
  interrupted runs.
- Invalid/missing email → skipped and logged; run continues.
- Single send failure → logged; run continues (one bad address won't halt the batch).
- SMTP auth failure → stop immediately with a plain-English message (bad app password).
- Missing resume/template/config → refuse to start with a clear message.
- Per-run cap prevents accidentally exceeding Gmail's daily limit.

## Testing

- Unit test: template rendering fills all placeholders correctly (incl. missing-field
  handling).
- Unit test: PDF/CSV parsing extracts `name/email/title/company` from a small sample.
- Manual: `--preview` then `--test` before the first real `--send`.

## Out of scope (YAGNI)

- AI-generated per-company sentences.
- Multiple/other sending providers (SendGrid/Resend), custom domains.
- Reply tracking, open tracking, scheduling/cron, GUI.
- Per-recipient different attachments.

## Operational notes

- App password setup: the Gmail account needs 2-Step Verification enabled, then an
  "App password" generated at the Google Account security page; that 16-char password
  goes in `config.ini` (not your normal Gmail password).
- ~1,842 contacts at ~400/day ≈ 5 daily runs to finish.
- This is personal job-search outreach; recipients are professional HR contacts.
```

