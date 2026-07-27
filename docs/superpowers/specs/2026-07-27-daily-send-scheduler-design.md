# Daily Send Scheduler — Design

**Date:** 2026-07-27
**Status:** Approved

## Purpose

Run `send_emails.py --send` automatically at 10:30 AM on weekdays, sending 50 emails per
run, until every contact in `contacts.csv` has been emailed — with no daily manual step
and no day silently skipped because the laptop happened to be asleep.

## Starting state (2026-07-27)

- `contacts.csv`: 1,842 contacts.
- `sent_log.csv`: 348 already sent.
- Pending: 1,494 → 30 runs at 50/day → finishes ~Friday 2026-09-04.
- `config.ini` already has `daily_limit = 50`, `delay_seconds = 8`.

## Confirmed requirements

- **Trigger:** macOS `launchd` LaunchAgent (not cron). Survives reboots; replays missed
  calendar events on wake.
- **Schedule:** Monday–Friday. First attempt 10:30 AM local time.
- **Retry:** hourly at :30 (10:30, 11:30, 12:30, 13:30, 14:30, 15:30). Any attempt at or
  after **16:00 is abandoned** until the next weekday.
- **Batch size:** 50 per day — unchanged `daily_limit` in `config.ini`.
- **Visibility:** append-only log file plus a macOS notification after each real run.
- **Completion:** when nothing is pending, notify, log, and unload the LaunchAgent so it
  stops firing.
- **Out of scope:** changing the template, contact list, batch size, delay, or any
  sending behaviour. This work adds a trigger around the existing tool.

## Architecture

launchd stays dumb; the runner holds all scheduling policy.

| Piece | Responsibility |
|---|---|
| `~/Library/LaunchAgents/com.mishka.mail-automator.plist` | Six plain daily fires at 10:30–15:30 |
| `mailauto/scheduler.py` | Four gates, log, notify, self-unload |
| `send_emails.py` | Unchanged sending behaviour |
| `scripts/install_scheduler.sh` | Install / uninstall the agent |

### Why the policy lives in Python, not the plist

launchd replays missed `StartCalendarInterval` events when the Mac wakes. A
weekday-filtered plist would therefore still fire on Saturday morning if the Mac slept
through Friday afternoon — launchd is replaying *Friday's* event. Only a check against
the actual current date and time can reject that, so weekday and cutoff rules live in
the runner. The plist becomes six identical time entries with no conditions, which also
avoids enumerating 6 times × 5 weekdays = 30 plist dictionaries.

### The four gates

Evaluated in order on every fire. Any failed gate exits 0 after one log line.

1. **Is today Mon–Fri?** — rejects weekend wake-up replays.
2. **Is it before 16:00?** — rejects the evening catch-up; the batch waits for the next
   weekday rather than landing at 6pm.
3. **Has today already succeeded?** — `logs/last_success` holds one `YYYY-MM-DD` line.
   Makes the 11:30–15:30 fires near-instant no-ops on a normal day.
4. **Is anything still pending?** — `select_pending(contacts, sent, None)` called directly;
   if zero, this is completion: notify, log, unload.

Only when all four pass does the runner connect to Gmail and send.

### Retry semantics

A failed or aborted run writes **no stamp**, so the next hourly fire retries. A run that
aborted after 20 of 50 emails resumes with the remaining 30, because `sent_log.csv` is
written per-email and `select_pending` already skips recorded addresses. Nobody is
emailed twice, and the retry needs no state of its own beyond the stamp file.

Partial success counts as success for stamping purposes only when the batch ran to
completion (individual recipient errors allowed). An aborted batch — `SendResult.aborted`
set — writes no stamp and is therefore retried.

## Changes to existing code

The runner calls `send_emails.cmd_send` **in-process**, not as a subprocess. It already
loads the same config and contacts to evaluate gate 4, so shelling out would parse
English prose for numbers it can hold as objects, and would lose the exception detail
that makes the log useful.

`cmd_send` currently returns only an exit code and prints its counts, so:

- `cmd_send` returns `SendResult(sent, failed, remaining, aborted)`; `main()` maps that to
  the existing exit codes. Printed output and CLI exit codes are unchanged.

That is the only change to existing code. No new CLI flags — `--pending-count` was
considered and dropped, since the runner shares the process and can call `select_pending`
directly.

## New files

- `mailauto/scheduler.py` — gates, logging, notification, self-unload.
- `run_daily.py` — thin entry point invoked by launchd (`python run_daily.py`).
- `scripts/com.mishka.mail-automator.plist.template` — `WorkingDirectory` set to the
  project root and an absolute `.venv/bin/python` path, since launchd runs with `cwd=/`
  and a minimal environment.
- `scripts/install_scheduler.sh` — fills the template with real paths, writes it to
  `~/Library/LaunchAgents/`, and bootstraps it. `--uninstall` boots it out and removes it.
- `logs/` — gitignored; holds `scheduler.log` and `last_success`.

## Logging and notification

Every fire appends one timestamped entry to `logs/scheduler.log`: which gate stopped it,
or the counts if it ran, plus any error text. The log is append-only and never rotated —
at roughly six lines a day it stays trivially small for a run of this length.

Notifications fire only after a real send or at completion, never for a skipped gate:

```
Mail Automator — Sent 50, failed 0. 1,444 left.
Mail Automator — All 1,842 contacts complete. Scheduler stopped.
```

Delivered via `osascript -e 'display notification ...'`, which works because a
LaunchAgent runs inside the user's GUI session. A failed `osascript` is caught and
logged; it must never fail a run that already sent email.

## Error handling

- **Gmail unreachable / auth rejected:** `cmd_send` already reports this as a
  plain-English `ConnectionProblem`. The runner logs it, notifies the failure, writes no
  stamp, and lets the next hourly fire retry.
- **Config or file missing:** `_load_all` raises before any gate can run. The runner
  catches it, logs the cause, writes no stamp, and retries on the next fire; after 15:30
  it stops for the day.
- **Unexpected exception anywhere in the runner:** caught at the top level, logged with a
  traceback, notified as a failure. A crash must never leave a stamp behind, since that
  would skip the day.
- **`logs/` absent on first run:** created by the runner.
- **Corrupt `last_success`:** treated as "no success today" — worst case is one extra
  send attempt, which `sent_log.csv` makes harmless.
- **Two fires overlapping** (a long batch still running at the next :30): prevented by
  launchd, which will not start a second copy of a running LaunchAgent job.

## Testing

`tests/test_scheduler.py`, using an injected clock and a stubbed sender. No test opens a
socket or writes to the real log.

- Each gate rejects and passes: Saturday, 16:01, stamp-is-today, zero pending.
- A successful run writes the stamp; a failed run does not.
- An aborted mid-batch run leaves no stamp, and the next fire retries.
- Completion path notifies and calls unload exactly once.
- First run with no `logs/` directory creates it.
- A raising sender is caught, logged, and leaves no stamp.

Existing `tests/test_send_cli.py` is extended for `SendResult`, asserting `main()` still
returns the same exit codes it does today.

The plist and install script are verified once by hand with a temporary two-minutes-away
schedule, then reset to the real times — launchd installation cannot be meaningfully
unit-tested.

## Documentation

A "Run it automatically" section in `README.md`: install command, uninstall command,
where the log lives, the schedule, and how to check progress with `--dry-run`.

## Amendment (2026-07-27, during implementation)

Task 4's review found that the completion condition as specified above can never
be satisfied. `load_sent` counts only rows with status `sent`, so a contact whose
send fails is written as `error` and stays pending forever. One permanently dead
address — near-certain in a 1,842-row scraped list — would mean the scheduler
retries it every weekday indefinitely and never reaches "nothing pending", so it
never notifies completion and never stops itself.

The sent log already contains 8 such rows, though all 8 are from the 2026-07-13
incident where the SMTP socket died mid-batch. Those are transient failures that
*should* be retried, which rules out treating any single error as terminal.

**Decision: an address is retried across later runs up to 3 attempts total, then
treated as done.** Transient failures still recover; genuinely dead addresses stop
blocking completion. "Done" therefore means delivered *or* attempted 3 times, and
that is what both `select_pending` and `SendResult.remaining` now measure.

## Deliberately excluded

- cron, as a fallback or otherwise.
- Log rotation.
- Email or Slack summaries — the notification and log cover it.
- Any change to `daily_limit`. Raising it to 100 would halve the ~6-week run and stay
  under Gmail's cap, but that is a separate decision the user has not made.
