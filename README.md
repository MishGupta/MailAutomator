# Mail Automator

Send personalized, resume-attached outreach emails from your own email account, in
daily batches, working down a contact list you already have. Works with Gmail,
Outlook, Yahoo, Zoho, or any provider that speaks SMTP.

You point it at a PDF of contacts (the kind of table a recruiter list or a career-fair
handout usually comes as), it pulls out name / email / title / company, and then sends
each person an individually personalized email with your resume attached. Everyone it
emails is recorded, so nobody is ever contacted twice — even if you stop halfway and
pick it up a week later.

Built for a job search, but it works for any outreach you'd otherwise do by hand:
internship drives, freelance pitches, conference or academic outreach.

**What makes it different from a mail-merge script:**

- **Resumable by design.** Progress lives in `sent_log.csv`, written as each email goes
  out. Kill it mid-run, reboot, come back next month — it picks up exactly where it
  stopped and never re-sends.
- **Nothing sends by accident.** The default action is a preview. You have to pass
  `--send` explicitly, and there's a `--test` mode that mails only you.
- **It can run itself.** An optional scheduler sends a batch every weekday morning,
  retries when your wifi is down, notifies you of each result, and switches itself off
  when the list is finished. *(macOS only — see below.)*

## Requirements

- **Python 3.9+**
- **An email account you can send from** — Gmail, Outlook, Yahoo, Zoho, your own
  domain, anything with SMTP. Gmail is the default and needs 2-Step Verification
  enabled so you can create an App Password.
- **Your contacts as a PDF** containing a table with an email column
- **Your resume** as a PDF

Sending works on **macOS, Linux, and Windows**. The automatic scheduler is
**macOS only** — it's built on launchd. On Linux or Windows you run the send command
yourself (or wire it into cron / Task Scheduler).

## Setup

```bash
git clone https://github.com/MishGupta/MailAutomator.git
cd MailAutomator
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

**1. Get an app password for your email account.**

*Gmail:* turn on 2-Step Verification, then generate an App Password at
https://myaccount.google.com/apppasswords — a 16-character code. Use that, **not** your
normal Gmail password.

*Other providers:* most require an app-specific password too. You'll also need your
provider's SMTP host and port:

| Provider | host | port |
|---|---|---|
| Gmail | `smtp.gmail.com` | 587 |
| Outlook / Hotmail | `smtp-mail.outlook.com` | 587 |
| Yahoo | `smtp.mail.yahoo.com` | 587 |
| Zoho | `smtp.zoho.com` | 587 |

Anything else: search your provider's docs for "SMTP settings". Ports other than 587 are
fine as long as the server supports STARTTLS.

**2. Fill in your config.**

```bash
cp config.ini.example config.ini
```

Set `address` and `app_password` under `[smtp]`. If you're not on Gmail, also set
`host` and `port` from the table above. This file is gitignored and must never be
committed.

**3. Add your resume.** Drop it in the folder as `resume.pdf`, or point `resume` in
`config.ini` at another path.

**4. Write your email.** Edit `email_template.txt`. Keep the `Subject:` line first, then
a blank line, then the body. Use `{name}`, `{company}`, `{title}`, and `{email}`
anywhere you want that contact's real value substituted in.

```
Subject: Application for openings at {company}

Hi {name},

I came across your profile as {title} at {company} and wanted to reach out...
```

## Build your contact list

```bash
.venv/bin/python import_contacts.py --pdf your_list.pdf   # -> contacts.csv
```

The parser looks for an email address in each table row and works out name, title, and
company from the surrounding cells, so it handles most contact-table layouts rather than
one specific format. `--pdf` defaults to `contacts.pdf` and `--out` defaults to
`contacts.csv`.

**Open `contacts.csv` in a spreadsheet afterwards and check it.** Fix anything the
parser got wrong and delete rows you don't want to contact. Keep the header row exactly
as it is — `name,email,title,company` — the tool refuses to run if it's been altered.

You can also skip the PDF entirely and write `contacts.csv` by hand, or export it from a
spreadsheet, as long as the header matches.

## Send

```bash
.venv/bin/python send_emails.py --preview   # show 3 finished sample emails (sends NOTHING)
.venv/bin/python send_emails.py --test      # send ONE test email to yourself
.venv/bin/python send_emails.py --dry-run   # counts: total / already sent / pending / would-send
.venv/bin/python send_emails.py --send      # send today's batch, then stop
```

- `--preview` is the default, so running with no flag never sends anything.
- **Do `--test` at least once** and check the email actually arrived — formatting and
  attachment — before your first real `--send`.
- Send fewer in one run with `--send --limit 20`. `--limit` must be a positive number.
- Already-emailed people are skipped automatically, so you just run `--send` once a day
  until the list is finished. Check progress any time with `--dry-run`.

## Run it automatically (macOS only)

```bash
./scripts/install_scheduler.sh              # turn it on
./scripts/install_scheduler.sh --uninstall  # turn it off
```

Once installed, a batch goes out at **10:30 AM, Monday to Friday**, with no action from
you, until the whole list is finished.

- **Do not run `--send` by hand while the scheduler is installed.** Both read the same
  pending list, so a manual run overlapping a scheduled one can re-send to the same
  people before either has recorded the other's results.
- If the Mac is asleep or off at 10:30, the batch runs as soon as it wakes — but only if
  it wakes before **16:00**. A Mac that stays closed past 16:00 loses that whole day; the
  batch simply waits for the next weekday.
- If a run fails (no wifi, mail server unreachable), it retries hourly — 11:30, 12:30,
  and so on — up to the same 16:00 cutoff.
- **Each attempt takes a fresh batch of `daily_limit`.** A run only marks the day done
  once it succeeds, so a day with failures can send several batches. With up to 6 fires
  a day, worst-case daily volume is `daily_limit × 6` — at the default 50 that's 300,
  safely under Gmail's ~500/day cap. **If you raise `daily_limit`, multiply by 6 and
  check the result against your provider's limit**; exceeding it can get your account
  suspended.
- A notification tells you the result of each run; `logs/scheduler.log` keeps the full
  history.
- It stops itself once nothing is left to do: every contact has either been emailed, or
  — after 3 failed tries — given up on. You get a notification saying how many (if any)
  couldn't be reached, and the scheduler switches itself off.

**One known edge case:** if the server drops the connection in the instant between accepting
a message and confirming it, that message is re-sent on reconnect and that person
receives it twice. Sending twice was judged better than never contacting them at all.

## Config reference (`config.ini`)

```ini
[smtp]
address = you@gmail.com
app_password = xxxx xxxx xxxx xxxx
host = smtp.gmail.com
port = 587

[files]
resume = resume.pdf
template = email_template.txt
contacts = contacts.csv

[send]
daily_limit = 50
delay_seconds = 2
cc_self = false
```

| key | meaning |
|---|---|
| `host` / `port` | SMTP server. Optional; defaults to Gmail. |
| `daily_limit` | Per-run cap. Default 50 — see the warning below before raising it. |
| `delay_seconds` | Pause between emails. Default 2. |
| `cc_self` | Set `true` to Cc yourself on every email. Default false. |

Both `[send]` and the `host`/`port` keys are optional — omit them and the defaults above
are used.

**Put comments on their own line.** `configparser` does not strip trailing comments, so
`daily_limit = 50  ; per-run cap` is read as the literal string and the run fails.

A `[gmail]` section is still accepted in place of `[smtp]`, so config files written for
earlier versions keep working.

## Responsible use

This sends real email to real people from your own account, under your own name. Use it
for outreach you'd be comfortable sending by hand:

- **Contact people you have a genuine reason to contact.** Don't use scraped or
  purchased lists.
- **Honor opt-outs immediately.** If someone asks not to be contacted, remove them from
  `contacts.csv` — and note that once someone is in `sent_log.csv` they're never
  selected again anyway.
- **Stay inside your provider's limits.** Free Gmail caps around 500 sends/day, Workspace
  around 2,000. Remember the scheduler's `daily_limit × 6` worst case when choosing
  a value; exceeding your provider's cap can get the account temporarily suspended.
- **Personalize properly.** A template that obviously wasn't read by a human gets
  reported as spam, which hurts your sending reputation more than it helps.

You're responsible for how you use this, including compliance with anti-spam law in your
jurisdiction (CAN-SPAM, GDPR, and equivalents).

## Troubleshooting

- **The server rejects the login** — on Gmail this is almost always a wrong App
  Password or 2-Step Verification not enabled; regenerate it and paste all 16
  characters. On other providers, check that you're using an app-specific password and
  that `host`/`port` match your provider's SMTP settings.
- **`invalid literal for int()` on startup** — you have a trailing `;` comment in
  `config.ini`. Move it to its own line.
- **`contacts.csv has the wrong header`** — the header row must be exactly
  `name,email,title,company`, lowercase, in that order. Spreadsheets often capitalize
  or reorder them on save.
- **The parser found no contacts** — your PDF's table may not be machine-readable
  (a scanned image, for instance). Check with
  `.venv/bin/python -c "import pdfplumber; print(pdfplumber.open('your_list.pdf').pages[0].extract_tables()[0][:3])"`.
  If that prints nothing, build `contacts.csv` by hand instead.
- **It refuses to send, citing `sent_log.csv`** — that's deliberate. A corrupted log
  means it can't tell who's already been emailed, and it stops rather than risk
  double-sending. Inspect and repair the file, then re-run.

## Files it creates

`config.ini`, `contacts.csv`, `sent_log.csv`, `resume.pdf`, and `logs/` are all
gitignored. They hold your credentials and other people's personal data — don't commit
them.

## Tests

```bash
.venv/bin/python -m pytest -q
```

## License

MIT — see [LICENSE](LICENSE). Free to use, modify, and distribute; just keep the
copyright notice.
