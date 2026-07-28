# Mail Automator

Send personalized, resume-attached outreach emails to HR contacts from a PDF list,
in daily batches, from your Gmail account. Already-emailed people are remembered and
never contacted twice.

## One-time setup

1. Install dependencies:
   ```bash
   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   ```
2. Turn on 2-Step Verification on the Gmail account you'll send from, then create an
   **App Password** at https://myaccount.google.com/apppasswords (a 16-character code).
   Use that, NOT your normal Gmail password.
3. Copy the example config and fill it in:
   ```bash
   cp config.ini.example config.ini
   ```
   Set `address` (e.g. `infogupta007@gmail.com`) and `app_password` under `[gmail]`.
4. Put your resume in the folder (default name `resume.pdf`, or point `resume` in
   `config.ini` at another file).
5. Edit `email_template.txt`. Keep the `Subject:` first line, then a blank line, then
   the body. Use `{name}`, `{company}`, `{title}`, `{email}` anywhere you want that
   contact's real value inserted.

## Build the contact list (run once)

```bash
.venv/bin/python import_contacts.py      # HR_Contact_List.pdf -> contacts.csv
```

Open `contacts.csv` in a spreadsheet and remove or fix any rows you don't want.

## Send (repeat daily until done)

```bash
.venv/bin/python send_emails.py --preview   # show 3 finished sample emails (sends NOTHING)
.venv/bin/python send_emails.py --test      # send ONE test email to yourself first
.venv/bin/python send_emails.py --dry-run   # counts: total / already sent / pending / would-send
.venv/bin/python send_emails.py --send      # send today's batch (default 400), then stop
```

- `--preview` is the default, so running with no flag never sends.
- Do `--test` at least once and check the email arrived (formatting + attachment) before
  your first real `--send`.
- Already-emailed people are recorded in `sent_log.csv` and skipped automatically, so you
  just run `--send` once a day until the list is finished (~1,842 ÷ 400 ≈ 5 days).
- Send fewer in one run: `--send --limit 200`. `--limit` must be a positive number.

## Run it automatically

```bash
./scripts/install_scheduler.sh              # turn it on
./scripts/install_scheduler.sh --uninstall  # turn it off
```

Once installed, 50 emails go out at **10:30 AM, Monday to Friday**, with no action
from you, until the whole list is finished.

- If the Mac is asleep or off at 10:30, the batch runs as soon as it wakes.
- If that fails (no wifi, Gmail unreachable), it retries hourly — 11:30, 12:30, and
  so on — and gives up at **16:00**, leaving the batch for the next weekday. Nobody
  is ever emailed twice, because `sent_log.csv` is written as each email goes out.
- A notification tells you the result of each run; `logs/scheduler.log` keeps the
  full history.
- It stops itself once nothing is left to do: every contact has either been emailed,
  or — after 3 failed tries — given up on. When that happens, you get a notification
  saying how many (if any) could not be reached, and the scheduler switches itself
  off.

Check progress at any time with `.venv/bin/python send_emails.py --dry-run`.

## Config reference (`config.ini`)

```ini
[gmail]
address = you@gmail.com
app_password = xxxx xxxx xxxx xxxx

[files]
resume = resume.pdf
template = email_template.txt
contacts = contacts.csv

[send]
daily_limit = 400      ; per-run cap (Gmail free accounts allow ~500/day)
delay_seconds = 2      ; pause between emails
cc_self = false        ; set true to Cc yourself on every email
```

The `[send]` section is optional — omit it and the defaults above are used.

## Notes

- `config.ini`, `sent_log.csv`, `contacts.csv`, and `resume.pdf` are gitignored — they
  hold secrets or personal data and should never be committed.
- Gmail free accounts cap at ~500 sends/day; Google Workspace accounts ~2,000. Keep
  `daily_limit` under your cap.
- If Gmail rejects the login, the tool tells you plainly — it almost always means the
  App Password is wrong or 2-Step Verification isn't enabled.
- If `sent_log.csv` ever gets corrupted, the tool refuses to send rather than risk
  emailing people twice; inspect/repair the file and re-run.

## Tests

```bash
.venv/bin/pytest -q
```
