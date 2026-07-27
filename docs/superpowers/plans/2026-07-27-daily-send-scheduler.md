# Daily Send Scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Send 50 outreach emails automatically at 10:30 AM every weekday, retrying hourly until 16:00, until every contact in `contacts.csv` has been emailed.

**Architecture:** A macOS `launchd` LaunchAgent fires a thin entry point six times a day (10:30–15:30). All scheduling policy — weekday, cutoff, already-ran-today, completion — lives in `mailauto/scheduler.py`, because launchd replays *missed* calendar events on wake and only a check against the real current time can reject those. The runner calls the existing `cmd_send` in-process and reports via a log file and a Notification Centre banner.

**Tech Stack:** Python 3.13 standard library only (`datetime`, `subprocess`, `os`), `launchd` via `launchctl`, `osascript` for notifications, `pytest` for tests. No new dependencies.

## Global Constraints

- **Design doc:** `docs/superpowers/specs/2026-07-27-daily-send-scheduler-design.md`. Read it first.
- **Never change sending behaviour.** `daily_limit = 50`, `delay_seconds = 8`, the template, and `contacts.csv` are all out of scope.
- **Never break the CLI.** `send_emails.py --send/--test/--dry-run/--preview` must print the same output and return the same exit codes after this work as before it.
- **No new dependencies.** `requirements.txt` is unchanged.
- **No test may open a socket, run `osascript`, run `launchctl`, or write outside `tmp_path`.**
- **Label:** `com.mishka.mail-automator` — used verbatim in the plist filename, the plist `Label`, the install script, and `scheduler.py`.
- **Times:** fires at 10:30, 11:30, 12:30, 13:30, 14:30, 15:30 local. Cutoff hour is 16.
- Run tests with `.venv/bin/python -m pytest -q` from the project root.

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `send_emails.py` | Modify | `cmd_send` returns `SendResult`; `_load_all` takes a path |
| `mailauto/scheduler.py` | Create | Gates, log, stamp, notification, self-stop, orchestration |
| `run_daily.py` | Create | Entry point launchd invokes — three lines, no logic |
| `scripts/com.mishka.mail-automator.plist.template` | Create | Six calendar entries, placeholder paths |
| `scripts/install_scheduler.sh` | Create | Fill template, bootstrap, `--uninstall` |
| `tests/test_scheduler.py` | Create | Every gate and every failure path, no I/O |
| `tests/test_send_cli.py` | Modify | Existing assertions move to `.exit_code` |
| `.gitignore` | Modify | Add `logs/` |
| `README.md` | Modify | "Run it automatically" section |

---

### Task 1: `SendResult` — give `cmd_send` a return value worth reading

The scheduler needs "sent 50, failed 0, 1,444 left" for its notification. Today `cmd_send` prints those numbers and returns a bare exit code, so the only way to get them is to scrape stdout. This task replaces the return value and leaves everything printed exactly as it is.

**Files:**
- Modify: `send_emails.py` (`_load_all` line 142, `cmd_send` lines 201-252, `main` lines 277-301)
- Test: `tests/test_send_cli.py` (existing assertions at lines 146, 163, 181)

**Interfaces:**
- Consumes: nothing.
- Produces: `SendResult(sent: int, failed: int, remaining: int, aborted: str | None)` with property `exit_code -> int`; `cmd_send(conf, subject_t, body_t, contacts, sent) -> SendResult`; `_load_all(config_path: str) -> (conf, subject_t, body_t, contacts, sent)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_send_cli.py`:

```python
def test_send_result_reports_counts_and_remaining(monkeypatch, tmp_path):
    """The scheduler needs real numbers, not a parsed sentence."""
    smtp = _FakeSMTP([None, None, None])
    conf, contacts, log, connects = _setup(monkeypatch, tmp_path, [smtp], n_contacts=5)
    conf.daily_limit = 3  # 5 pending, 3 go out, 2 must be reported as left

    result = send_emails.cmd_send(conf, "Hi {company}", "Dear {name}", contacts, set())

    assert result.sent == 3
    assert result.failed == 0
    assert result.remaining == 2
    assert result.aborted is None
    assert result.exit_code == 0


def test_send_result_remaining_counts_failures_as_still_pending(monkeypatch, tmp_path):
    """A refused address was not delivered, so it still counts as outstanding."""
    refused = smtplib.SMTPRecipientsRefused({"p1@acme.com": (550, b"no such user")})
    smtp = _FakeSMTP([None, refused, None])
    conf, contacts, log, connects = _setup(monkeypatch, tmp_path, [smtp], n_contacts=3)

    result = send_emails.cmd_send(conf, "Hi {company}", "Dear {name}", contacts, set())

    assert (result.sent, result.failed) == (2, 1)
    assert result.remaining == 1
    assert result.exit_code == 0


def test_send_result_aborted_carries_the_reason(monkeypatch, tmp_path):
    """An aborted batch must be distinguishable from a clean one."""
    dead = _FakeSMTP([None, smtplib.SMTPServerDisconnected("connection reset by peer")])
    conf, contacts, log, connects = _setup(
        monkeypatch, tmp_path, [dead], n_contacts=3, connect_fails_after=1
    )

    result = send_emails.cmd_send(conf, "Hi {company}", "Dear {name}", contacts, set())

    assert result.aborted is not None
    assert "gmail" in result.aborted.lower()
    assert result.sent == 1
    assert result.exit_code == 1


def test_send_result_empty_list_is_complete_not_aborted(monkeypatch, tmp_path):
    """Nothing pending is the finished state, and must not touch Gmail."""
    conf, contacts, log, connects = _setup(monkeypatch, tmp_path, [], n_contacts=0)

    result = send_emails.cmd_send(conf, "Hi {company}", "Dear {name}", contacts, set())

    assert (result.sent, result.failed, result.remaining) == (0, 0, 0)
    assert result.aborted is None
    assert connects == [], "an empty batch must never connect to Gmail"
```

Update the three existing assertions so they test the exit code explicitly:

```python
# line ~146, in test_send_reconnects_and_still_delivers_after_socket_dies
    rc = send_emails.cmd_send(conf, "Hi {company}", "Dear {name}", contacts, set())
    assert rc.exit_code == 0

# line ~163, in test_send_aborts_rather_than_burning_contacts_when_reconnect_fails
    rc = send_emails.cmd_send(conf, "Hi {company}", "Dear {name}", contacts, set())
    assert rc.exit_code == 1, "an unreachable Gmail should be reported as a failed run"

# line ~181, in test_send_logs_bad_recipient_and_keeps_going
    rc = send_emails.cmd_send(conf, "Hi {company}", "Dear {name}", contacts, set())
    assert rc.exit_code == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_send_cli.py -q`
Expected: FAIL — `AttributeError: 'int' object has no attribute 'exit_code'`.

- [ ] **Step 3: Add `SendResult`**

In `send_emails.py`, after the imports and before `class ConnectionProblem`:

```python
from dataclasses import dataclass


@dataclass
class SendResult:
    """What one batch actually did.

    `remaining` counts everyone still un-emailed across the whole list, not
    just this batch, so a caller can tell "50 done, 1444 to go" from "finished".
    `aborted` holds the reason Gmail became unreachable, or None if the batch
    ran to the end -- individual refused recipients are failures, not aborts.
    """

    sent: int
    failed: int
    remaining: int
    aborted: str | None = None

    @property
    def exit_code(self) -> int:
        return 1 if self.aborted else 0
```

- [ ] **Step 4: Return it from `cmd_send`**

Replace the four exit points in `cmd_send`. First, compute the full pending count up front — `todays` is already capped at `daily_limit`, so it cannot answer "how many are left":

```python
def cmd_send(conf, subject_t, body_t, contacts, sent):
    pending = select_pending(contacts, sent, None)
    todays = select_pending(contacts, sent, conf.daily_limit)
    if not todays:
        print("Nothing to send — everyone pending is already done or the list is empty.")
        return SendResult(0, 0, 0)
    print(f"Sending {len(todays)} emails (limit {conf.daily_limit})...")
    try:
        smtp = connect_or_explain(conf)
    except ConnectionProblem as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return SendResult(0, 0, len(pending), aborted=str(e))
```

The body of the loop is unchanged. Replace the two closing returns:

```python
    if aborted:
        remaining = len(todays) - ok - failed
        print(f"\nERROR: {aborted}", file=sys.stderr)
        print(f"Stopped after {ok} sent, {failed} failed. The remaining {remaining} "
              f"contacts were not touched — just run --send again to pick up where "
              f"this left off.", file=sys.stderr)
        return SendResult(ok, failed, len(pending) - ok, aborted=str(aborted))

    print(f"\nDone. Sent {ok}, failed {failed}. Run again tomorrow for the next batch.")
    return SendResult(ok, failed, len(pending) - ok)
```

Note `len(pending) - ok`, not `- ok - failed`: a refused address was never delivered, so it is still outstanding and must be counted as remaining.

- [ ] **Step 5: Map it to an exit code in `main`, and simplify `_load_all`**

`_load_all` currently takes the whole argparse namespace just to read one attribute, which would force the scheduler to fabricate a fake namespace. Give it the path:

```python
def _load_all(config_path):
    conf = load_config(config_path)
    with open(conf.template_path, encoding="utf-8") as f:
        subject_t, body_t = parse_template(f.read())
    contacts = load_contacts_csv(conf.contacts_path)
    sent = load_sent(SENT_LOG)
    return conf, subject_t, body_t, contacts, sent
```

In `main`, update the call site and the `--send` branch:

```python
        conf, subject_t, body_t, contacts, sent = _load_all(args.config)
```

```python
        if args.send:
            return cmd_send(conf, subject_t, body_t, contacts, sent).exit_code
```

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS, all tests. If anything outside `test_send_cli.py` fails, the CLI contract has been broken — fix it rather than updating the assertion.

- [ ] **Step 7: Verify the CLI is genuinely unchanged**

Run: `.venv/bin/python send_emails.py --dry-run && echo "exit=$?"`
Expected: the same counts table as before, `exit=0`. This touches the real `contacts.csv` and `sent_log.csv` but sends nothing.

- [ ] **Step 8: Commit**

```bash
git add send_emails.py tests/test_send_cli.py
git commit -m "refactor: cmd_send returns SendResult so callers get real counts"
```

---

### Task 2: Scheduler gates, log, and stamp

The four decisions a fire must make, as pure functions over an injected clock, plus the two files that persist state. No sending, no notifications yet.

**Files:**
- Create: `mailauto/scheduler.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `is_workday(now) -> bool`; `within_window(now) -> bool`; `already_ran_today(now, log_dir) -> bool`; `record_success(now, log_dir) -> None`; `log(message, now, log_dir) -> None`; constants `LOG_DIR = "logs"`, `CUTOFF_HOUR = 16`, `LAUNCH_AGENT_LABEL = "com.mishka.mail-automator"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scheduler.py`:

```python
import datetime

from mailauto import scheduler


def dt(y=2026, m=7, d=27, hour=10, minute=30):
    """2026-07-27 is a Monday — the reference weekday for these tests."""
    return datetime.datetime(y, m, d, hour, minute)


# --- gate 1: weekdays only ----------------------------------------------------
#
# launchd replays a missed calendar event when the Mac wakes, so a laptop that
# slept through Friday afternoon fires on Saturday morning. Filtering weekdays
# in the plist would not catch that -- launchd is replaying Friday's event.
# Only a test against today's real date can reject it.

def test_monday_is_a_workday():
    assert scheduler.is_workday(dt(d=27)) is True


def test_friday_is_a_workday():
    assert scheduler.is_workday(dt(d=31)) is True


def test_saturday_is_not_a_workday():
    assert scheduler.is_workday(dt(m=8, d=1)) is False


def test_sunday_is_not_a_workday():
    assert scheduler.is_workday(dt(m=8, d=2)) is False


# --- gate 2: the 16:00 cutoff -------------------------------------------------

def test_first_fire_is_within_the_window():
    assert scheduler.within_window(dt(hour=10, minute=30)) is True


def test_last_scheduled_fire_is_within_the_window():
    assert scheduler.within_window(dt(hour=15, minute=30)) is True


def test_four_pm_exactly_is_past_the_cutoff():
    assert scheduler.within_window(dt(hour=16, minute=0)) is False


def test_evening_wakeup_is_past_the_cutoff():
    """The case that motivated the cutoff: a Mac waking at 6pm."""
    assert scheduler.within_window(dt(hour=18, minute=5)) is False


# --- gate 3: the success stamp ------------------------------------------------

def test_no_stamp_means_not_run_today(tmp_path):
    assert scheduler.already_ran_today(dt(), str(tmp_path)) is False


def test_stamp_from_today_means_already_run(tmp_path):
    scheduler.record_success(dt(), str(tmp_path))
    assert scheduler.already_ran_today(dt(hour=11, minute=30), str(tmp_path)) is True


def test_stamp_from_yesterday_means_not_run(tmp_path):
    scheduler.record_success(dt(d=26), str(tmp_path))
    assert scheduler.already_ran_today(dt(d=27), str(tmp_path)) is False


def test_corrupt_stamp_is_treated_as_not_run(tmp_path):
    """Worst case is one extra send attempt, and sent_log.csv makes that
    harmless. Treating garbage as 'already ran' would silently skip a day."""
    (tmp_path / "last_success").write_text("\x00 not a date at all")
    assert scheduler.already_ran_today(dt(), str(tmp_path)) is False


def test_record_success_creates_a_missing_log_dir(tmp_path):
    target = tmp_path / "logs"
    scheduler.record_success(dt(), str(target))
    assert (target / "last_success").read_text().strip() == "2026-07-27"


# --- the log ------------------------------------------------------------------

def test_log_appends_with_a_timestamp(tmp_path):
    scheduler.log("first thing", dt(hour=10, minute=30), str(tmp_path))
    scheduler.log("second thing", dt(hour=11, minute=30), str(tmp_path))
    text = (tmp_path / "scheduler.log").read_text()
    assert "2026-07-27T10:30:00  first thing" in text
    assert "2026-07-27T11:30:00  second thing" in text
    assert text.count("\n") == 2, "entries must append, never overwrite"


def test_log_creates_a_missing_log_dir(tmp_path):
    target = tmp_path / "logs"
    scheduler.log("hello", dt(), str(target))
    assert (target / "scheduler.log").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_scheduler.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'mailauto.scheduler'`.

- [ ] **Step 3: Write the module**

Create `mailauto/scheduler.py`:

```python
"""Decides whether a launchd fire should actually send today's batch.

launchd is deliberately dumb here: it fires six times every day, and every
scheduling rule lives in this module. That split exists because launchd replays
calendar events it missed while the Mac was asleep -- a Friday-afternoon event
can arrive on Saturday morning -- so the only trustworthy answer to "should
this run?" comes from checking the clock now, not from what launchd was asked
to do.
"""

import os

LOG_DIR = "logs"
CUTOFF_HOUR = 16
WEEKEND = (5, 6)  # datetime.weekday(): Saturday, Sunday
LAUNCH_AGENT_LABEL = "com.mishka.mail-automator"


def stamp_path(log_dir=LOG_DIR):
    return os.path.join(log_dir, "last_success")


def log_file_path(log_dir=LOG_DIR):
    return os.path.join(log_dir, "scheduler.log")


def is_workday(now):
    """Gate 1: Monday-Friday only."""
    return now.weekday() not in WEEKEND


def within_window(now):
    """Gate 2: nothing goes out at or after 16:00.

    Guards the wake-up replay: a Mac that wakes at 6pm would otherwise send a
    batch at 6pm. Better to leave it for the next weekday.
    """
    return now.hour < CUTOFF_HOUR


def already_ran_today(now, log_dir=LOG_DIR):
    """Gate 3: did a batch already succeed today?

    Makes the 11:30-15:30 fires near-instant no-ops on a normal day. Anything
    unreadable or unparseable counts as "no" -- one redundant attempt is
    harmless because sent_log.csv prevents duplicate emails, whereas trusting a
    corrupt file would skip the day entirely.
    """
    try:
        with open(stamp_path(log_dir), encoding="utf-8") as f:
            return f.read().strip() == now.date().isoformat()
    except (OSError, UnicodeDecodeError):
        return False


def record_success(now, log_dir=LOG_DIR):
    os.makedirs(log_dir, exist_ok=True)
    with open(stamp_path(log_dir), "w", encoding="utf-8") as f:
        f.write(now.date().isoformat() + "\n")


def log(message, now, log_dir=LOG_DIR):
    """Append one timestamped line. Six lines a day needs no rotation."""
    os.makedirs(log_dir, exist_ok=True)
    with open(log_file_path(log_dir), "a", encoding="utf-8") as f:
        f.write(f"{now.isoformat(timespec='seconds')}  {message}\n")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_scheduler.py -q`
Expected: PASS, 15 tests.

- [ ] **Step 5: Commit**

```bash
git add mailauto/scheduler.py tests/test_scheduler.py
git commit -m "feat: scheduler gates, success stamp, and run log"
```

---

### Task 3: Notification and self-stop

The two side effects that reach outside Python. Both must fail softly — a missing notification must never fail a run that already sent 50 emails.

**Files:**
- Modify: `mailauto/scheduler.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `LAUNCH_AGENT_LABEL` from Task 2.
- Produces: `notify(message: str, title: str = APP_TITLE) -> bool`; `stop_agent(label=LAUNCH_AGENT_LABEL, plist=AGENT_PLIST, uid=None) -> bool`; `_osa_quote(s: str) -> str`; constants `APP_TITLE`, `AGENT_PLIST`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scheduler.py`:

```python
# --- notifications ------------------------------------------------------------

def test_notify_shells_out_to_osascript(monkeypatch):
    calls = []
    monkeypatch.setattr(scheduler.subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd))
    assert scheduler.notify("Sent 50, failed 0. 1444 left.") is True
    assert calls[0][0] == "osascript"
    joined = " ".join(calls[0])
    assert "display notification" in joined
    assert "Sent 50, failed 0. 1444 left." in joined
    assert "Mail Automator" in joined


def test_notify_survives_osascript_blowing_up(monkeypatch):
    """A failed banner must never fail a run that already sent email."""
    def boom(cmd, **kw):
        raise FileNotFoundError("osascript: not found")
    monkeypatch.setattr(scheduler.subprocess, "run", boom)
    assert scheduler.notify("anything") is False


def test_osa_quote_escapes_quotes_and_backslashes():
    """Company names carry apostrophes and the odd backslash; an unescaped one
    turns the AppleScript into a syntax error and loses the notification."""
    assert scheduler._osa_quote('say "hi"') == '"say \\"hi\\""'
    assert scheduler._osa_quote("back\\slash") == '"back\\\\slash"'


# --- stopping the agent when the list is finished -----------------------------

def test_stop_agent_removes_the_plist_before_booting_out(tmp_path, monkeypatch):
    """Order matters twice over: bootout can terminate this very process, and a
    plist left on disk is reloaded at the next login."""
    plist = tmp_path / "com.mishka.mail-automator.plist"
    plist.write_text("<plist/>")
    events = []
    monkeypatch.setattr(scheduler.subprocess, "run",
                        lambda cmd, **kw: events.append(("ran", plist.exists())))

    assert scheduler.stop_agent(plist=str(plist), uid=501) is True
    assert events == [("ran", False)], "plist must already be gone by bootout"
    assert not plist.exists()


def test_stop_agent_targets_the_gui_domain(tmp_path, monkeypatch):
    plist = tmp_path / "p.plist"
    plist.write_text("<plist/>")
    calls = []
    monkeypatch.setattr(scheduler.subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd))
    scheduler.stop_agent(plist=str(plist), uid=501)
    assert calls[0] == ["launchctl", "bootout", "gui/501/com.mishka.mail-automator"]


def test_stop_agent_survives_launchctl_failing(tmp_path, monkeypatch):
    plist = tmp_path / "p.plist"
    plist.write_text("<plist/>")
    def boom(cmd, **kw):
        raise OSError("launchctl exploded")
    monkeypatch.setattr(scheduler.subprocess, "run", boom)
    assert scheduler.stop_agent(plist=str(plist), uid=501) is False
    assert not plist.exists(), "the plist is gone either way, so login won't reload it"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_scheduler.py -q`
Expected: FAIL — `AttributeError: module 'mailauto.scheduler' has no attribute 'subprocess'`.

- [ ] **Step 3: Implement both side effects**

Add `import subprocess` to the imports in `mailauto/scheduler.py`, then append:

```python
APP_TITLE = "Mail Automator"
AGENT_PLIST = os.path.expanduser(f"~/Library/LaunchAgents/{LAUNCH_AGENT_LABEL}.plist")


def _osa_quote(s):
    """Quote a Python string as an AppleScript string literal.

    Backslash first -- escaping quotes first would then double the backslashes
    this step introduces.
    """
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify(message, title=APP_TITLE):
    """Show a Notification Centre banner. Returns whether it worked.

    Works because a LaunchAgent runs inside the user's GUI session. Never
    raises: losing a banner is trivial next to failing a run that already
    delivered email.
    """
    script = (f"display notification {_osa_quote(message)} "
              f"with title {_osa_quote(title)}")
    try:
        subprocess.run(["osascript", "-e", script],
                       check=True, capture_output=True, timeout=15)
        return True
    except Exception:
        return False


def stop_agent(label=LAUNCH_AGENT_LABEL, plist=AGENT_PLIST, uid=None):
    """Stop the scheduler for good, once every contact has been emailed.

    The plist is deleted *before* the bootout for two reasons: bootout
    terminates the running job, which is this very process, so nothing after it
    is guaranteed to run; and launchd reloads any plist still sitting in
    ~/Library/LaunchAgents at the next login, which would quietly restart a
    scheduler that has nothing left to do.
    """
    uid = os.getuid() if uid is None else uid
    try:
        os.remove(plist)
    except OSError:
        pass  # already gone, or never installed from this path
    try:
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"],
                       check=True, capture_output=True, timeout=15)
        return True
    except Exception:
        return False
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_scheduler.py -q`
Expected: PASS, 21 tests.

- [ ] **Step 5: Commit**

```bash
git add mailauto/scheduler.py tests/test_scheduler.py
git commit -m "feat: notification banner and self-stop for the scheduler"
```

---

### Task 4: `run_scheduled` — the orchestration

Wires the gates to the sender. The one design note: gate 4 ("anything still pending?") is answered by `SendResult.remaining` rather than a separate `select_pending` call, because `cmd_send` already returns without connecting when nothing is pending. Same behaviour as the spec describes, one less way to ask the same question.

**Files:**
- Modify: `mailauto/scheduler.py`
- Create: `run_daily.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: everything from Tasks 2 and 3; `send_emails.SendResult`, `send_emails.cmd_send`, `send_emails._load_all` from Task 1.
- Produces: `run_scheduled(now=None, *, log_dir=LOG_DIR, config_path="config.ini", send=None, notify_fn=notify, stop_fn=stop_agent) -> int`; `_real_send(config_path) -> SendResult`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scheduler.py`:

```python
# --- orchestration ------------------------------------------------------------

class Recorder:
    """Captures the side effects instead of performing them."""

    def __init__(self, result=None, raises=None):
        self.result = result
        self.raises = raises
        self.sends = 0
        self.messages = []
        self.stopped = 0

    def send(self, config_path):
        self.sends += 1
        if self.raises:
            raise self.raises
        return self.result

    def notify(self, message, title="Mail Automator"):
        self.messages.append(message)
        return True

    def stop(self):
        self.stopped += 1
        return True


def result(sent=50, failed=0, remaining=1444, aborted=None):
    from send_emails import SendResult
    return SendResult(sent, failed, remaining, aborted)


def run(rec, now, tmp_path):
    return scheduler.run_scheduled(
        now, log_dir=str(tmp_path), send=rec.send,
        notify_fn=rec.notify, stop_fn=rec.stop,
    )


def test_weekend_fire_sends_nothing(tmp_path):
    rec = Recorder(result())
    assert run(rec, dt(m=8, d=1), tmp_path) == 0
    assert rec.sends == 0
    assert rec.messages == [], "a skipped gate is not worth a banner"
    assert "weekend" in (tmp_path / "scheduler.log").read_text()


def test_fire_after_the_cutoff_sends_nothing(tmp_path):
    rec = Recorder(result())
    assert run(rec, dt(hour=18), tmp_path) == 0
    assert rec.sends == 0
    assert "cutoff" in (tmp_path / "scheduler.log").read_text()


def test_second_fire_of_the_day_sends_nothing(tmp_path):
    rec = Recorder(result())
    assert run(rec, dt(hour=10, minute=30), tmp_path) == 0
    assert run(rec, dt(hour=11, minute=30), tmp_path) == 0
    assert rec.sends == 1, "11:30 must be a no-op after 10:30 succeeded"


def test_successful_run_stamps_notifies_and_logs(tmp_path):
    rec = Recorder(result(sent=50, failed=0, remaining=1444))
    assert run(rec, dt(), tmp_path) == 0
    assert rec.sends == 1
    assert scheduler.already_ran_today(dt(), str(tmp_path)) is True
    assert "Sent 50, failed 0" in rec.messages[0]
    assert "1444 left" in rec.messages[0]
    assert rec.stopped == 0


def test_aborted_run_leaves_no_stamp_so_the_next_fire_retries(tmp_path):
    """The whole point of the hourly retries."""
    rec = Recorder(result(sent=20, failed=0, remaining=1474, aborted="Gmail unreachable"))
    assert run(rec, dt(hour=10, minute=30), tmp_path) == 1
    assert scheduler.already_ran_today(dt(), str(tmp_path)) is False

    rec.result = result(sent=30, failed=0, remaining=1444)
    assert run(rec, dt(hour=11, minute=30), tmp_path) == 0
    assert rec.sends == 2, "11:30 must retry after a 10:30 abort"
    assert scheduler.already_ran_today(dt(), str(tmp_path)) is True


def test_crashing_sender_is_caught_and_leaves_no_stamp(tmp_path):
    """A stamp written by a crash would silently skip the whole day."""
    rec = Recorder(raises=FileNotFoundError("config.ini not found"))
    assert run(rec, dt(), tmp_path) == 1
    assert scheduler.already_ran_today(dt(), str(tmp_path)) is False
    assert "FileNotFoundError" in (tmp_path / "scheduler.log").read_text()
    assert "failed" in rec.messages[0].lower()


def test_finishing_the_list_stops_the_scheduler(tmp_path):
    rec = Recorder(result(sent=44, failed=0, remaining=0))
    assert run(rec, dt(), tmp_path) == 0
    assert rec.stopped == 1
    assert "complete" in rec.messages[-1].lower()
    assert "complete" in (tmp_path / "scheduler.log").read_text().lower()


def test_already_finished_list_stops_without_sending(tmp_path):
    """cmd_send returns an empty result without connecting when nothing pends."""
    rec = Recorder(result(sent=0, failed=0, remaining=0))
    assert run(rec, dt(), tmp_path) == 0
    assert rec.stopped == 1


def test_completion_logs_before_stopping(tmp_path, monkeypatch):
    """stop_agent terminates this process, so anything logged after it is lost."""
    seen = {}
    rec = Recorder(result(sent=44, failed=0, remaining=0))
    def stop():
        seen["log_at_stop"] = (tmp_path / "scheduler.log").read_text()
        return True
    rec.stop = stop
    run(rec, dt(), tmp_path)
    assert "complete" in seen["log_at_stop"].lower()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_scheduler.py -q`
Expected: FAIL — `AttributeError: module 'mailauto.scheduler' has no attribute 'run_scheduled'`.

- [ ] **Step 3: Implement `run_scheduled`**

Add `import datetime` to the imports in `mailauto/scheduler.py`, then append:

```python
def _real_send(config_path="config.ini"):
    """Run one batch through the ordinary CLI code path.

    Imported here rather than at module scope: send_emails is a top-level
    script that imports this package's siblings, and keeping the dependency
    inside the call avoids an import cycle at load time.
    """
    import send_emails
    conf, subject_t, body_t, contacts, sent = send_emails._load_all(config_path)
    return send_emails.cmd_send(conf, subject_t, body_t, contacts, sent)


def run_scheduled(now=None, *, log_dir=LOG_DIR, config_path="config.ini",
                  send=None, notify_fn=notify, stop_fn=stop_agent):
    """One launchd fire. Returns a process exit code.

    Every gate that rejects exits 0 and logs a single line -- a skipped fire is
    normal operation, not an error, and launchd should not treat it as one.
    """
    now = now or datetime.datetime.now()
    send = send or _real_send

    if not is_workday(now):
        log("skipped: weekend", now, log_dir)
        return 0
    if not within_window(now):
        log(f"skipped: past the {CUTOFF_HOUR}:00 cutoff", now, log_dir)
        return 0
    if already_ran_today(now, log_dir):
        log("skipped: today's batch already went out", now, log_dir)
        return 0

    try:
        result = send(config_path)
    except Exception as e:
        # No stamp: a crash must leave the day open for the next hourly fire.
        log(f"FAILED: {type(e).__name__}: {e}", now, log_dir)
        notify_fn(f"Run failed: {e}")
        return 1

    if result.aborted:
        log(f"aborted after {result.sent} sent, {result.failed} failed: {result.aborted}",
            now, log_dir)
        notify_fn(f"Stopped after {result.sent} sent — retrying within the hour.")
        return 1

    record_success(now, log_dir)
    log(f"sent {result.sent}, failed {result.failed}, {result.remaining} left",
        now, log_dir)

    if result.remaining == 0:
        # Log before stopping: stop_agent boots out this very process.
        log("all contacts complete — stopping the scheduler", now, log_dir)
        notify_fn("All contacts complete. Scheduler stopped.")
        stop_fn()
        return 0

    notify_fn(f"Sent {result.sent}, failed {result.failed}. {result.remaining} left.")
    return 0
```

- [ ] **Step 4: Write the entry point**

Create `run_daily.py`:

```python
"""Entry point launchd invokes. Every decision lives in mailauto.scheduler."""

import sys

from mailauto.scheduler import run_scheduled

if __name__ == "__main__":
    raise SystemExit(run_scheduled())
```

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS, all tests including the 30 in `test_scheduler.py`.

- [ ] **Step 6: Prove the gates work against the real code**

The stamp makes this safe — it sends nothing because it is a Saturday:

```bash
.venv/bin/python -c "
import datetime
from mailauto.scheduler import run_scheduled
print('exit', run_scheduled(datetime.datetime(2026, 8, 1, 10, 30)))
"
cat logs/scheduler.log
```

Expected: `exit 0` and a log line reading `skipped: weekend`. **No email is sent.**

- [ ] **Step 7: Commit**

```bash
git add mailauto/scheduler.py run_daily.py tests/test_scheduler.py
git commit -m "feat: run_scheduled ties the gates to the sender"
```

---

### Task 5: LaunchAgent, installer, and docs

Everything needed to actually turn it on. This is the only task with a manual verification step, because launchd installation cannot be meaningfully unit-tested.

**Files:**
- Create: `scripts/com.mishka.mail-automator.plist.template`
- Create: `scripts/install_scheduler.sh`
- Modify: `.gitignore`
- Modify: `README.md`

**Interfaces:**
- Consumes: `run_daily.py` from Task 4; `LAUNCH_AGENT_LABEL` from Task 2 (the label must match exactly, or `stop_agent` boots out nothing).
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Write the plist template**

Create `scripts/com.mishka.mail-automator.plist.template`. Six entries, no weekday filtering — the runner owns that rule:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.mishka.mail-automator</string>

  <key>ProgramArguments</key>
  <array>
    <string>__PYTHON__</string>
    <string>__PROJECT__/run_daily.py</string>
  </array>

  <!-- launchd runs jobs with cwd=/ and a minimal environment, so every path
       the tool resolves relatively (config.ini, contacts.csv, sent_log.csv,
       logs/) depends on this being set. -->
  <key>WorkingDirectory</key>
  <string>__PROJECT__</string>

  <key>StandardOutPath</key>
  <string>__PROJECT__/logs/launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>__PROJECT__/logs/launchd.err.log</string>

  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>10</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>11</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>13</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>14</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>15</integer><key>Minute</key><integer>30</integer></dict>
  </array>
</dict>
</plist>
```

- [ ] **Step 2: Write the installer**

Create `scripts/install_scheduler.sh`:

```bash
#!/usr/bin/env bash
# Install (or remove) the LaunchAgent that sends the daily batch.
set -euo pipefail

LABEL="com.mishka.mail-automator"
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PYTHON="$PROJECT/.venv/bin/python"
TARGET="gui/$(id -u)/$LABEL"

if [ "${1:-}" = "--uninstall" ]; then
  launchctl bootout "$TARGET" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Scheduler removed. Nothing will send automatically from now on."
  exit 0
fi

if [ ! -x "$PYTHON" ]; then
  echo "ERROR: no virtualenv python at $PYTHON" >&2
  echo "Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT/logs"

# Absolute paths are baked in because launchd runs with cwd=/ and no PATH.
sed -e "s|__PYTHON__|$PYTHON|g" -e "s|__PROJECT__|$PROJECT|g" \
    "$PROJECT/scripts/$LABEL.plist.template" > "$PLIST"

launchctl bootout "$TARGET" 2>/dev/null || true   # replace any previous copy
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "Installed. Weekdays at 10:30, retrying hourly until 16:00."
echo "Log: $PROJECT/logs/scheduler.log"
launchctl print "$TARGET" | grep -E "state|program|runs" || true
```

Then: `chmod +x scripts/install_scheduler.sh`

- [ ] **Step 3: Ignore the log directory**

Append to `.gitignore`, under the `# secrets & generated` block:

```
logs/
```

`logs/` records who was emailed and when, which is the same personal data `sent_log.csv` holds and is already ignored for the same reason.

- [ ] **Step 4: Verify the installer end to end, with the clock rigged**

This is the one step that touches the real LaunchAgent. Install it, then confirm launchd actually runs the job — using a Saturday so the runner's own gate guarantees nothing is sent:

```bash
./scripts/install_scheduler.sh
launchctl print "gui/$(id -u)/com.mishka.mail-automator" | grep -E "state|path"
launchctl kickstart -p "gui/$(id -u)/com.mishka.mail-automator"
sleep 5
cat logs/scheduler.log
```

Expected: `launchctl print` shows the job loaded with the right program path, and `kickstart` produces a fresh log line. Because `kickstart` runs it now — a Monday afternoon during implementation — the line will be either `sent N, ...` **or** a skip line, depending on the real clock and whether today's stamp exists.

**If it is a weekday and before 16:00 when you run this, the kickstart WILL SEND 50 REAL EMAILS.** To verify without sending, either run it outside the window, or temporarily set the stamp first:

```bash
mkdir -p logs && date +%F > logs/last_success   # makes gate 3 reject the run
launchctl kickstart -p "gui/$(id -u)/com.mishka.mail-automator"
sleep 5
tail -1 logs/scheduler.log     # expect: skipped: today's batch already went out
rm logs/last_success           # remove so tomorrow's 10:30 runs normally
```

- [ ] **Step 5: Document it**

Add to `README.md`, after the "Send (repeat daily until done)" section:

````markdown
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
- When the last contact has been emailed, it notifies you and switches itself off.

Check progress at any time with `.venv/bin/python send_emails.py --dry-run`.
````

- [ ] **Step 6: Run the full suite one last time**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS, all tests.

- [ ] **Step 7: Commit**

```bash
git add scripts/ .gitignore README.md
git commit -m "feat: launchd agent, installer, and docs for the daily scheduler"
```

---

## Done when

- `.venv/bin/python -m pytest -q` passes.
- `launchctl print "gui/$(id -u)/com.mishka.mail-automator"` shows the job loaded.
- `logs/scheduler.log` has at least one line from a launchd-triggered run.
- `.venv/bin/python send_emails.py --dry-run` still prints its counts and exits 0.
- No `logs/` directory, `config.ini`, or `sent_log.csv` in `git status`.

---

### Task 6: Attempt cap — let the list actually finish

Task 4's review found the completion condition is unsatisfiable as designed. `load_sent` counts only rows whose status is `sent`, so a contact whose send fails is recorded as `error` and remains pending forever. One permanently dead address means `remaining` never reaches 0: the scheduler reconnects to Gmail every weekday to re-attempt the same dead addresses, never notifies completion, and never stops itself.

Approved decision: **an address is retried across later runs up to 3 attempts total, then treated as done.** The 8 error rows currently in `sent_log.csv` are all from the 2026-07-13 socket-death incident — transient failures that should still be retried — which is why a single error cannot be treated as terminal.

Execute this task BEFORE Task 5, so Task 5's README describes the final behaviour.

**Files:**
- Modify: `mailauto/sentlog.py`
- Modify: `send_emails.py` (`_load_all` only)
- Test: `tests/test_sentlog.py`

**Interfaces:**
- Consumes: `load_sent(path) -> set` (unchanged, still used by tests).
- Produces: `MAX_ATTEMPTS = 3`; `load_done(path, max_attempts=MAX_ATTEMPTS) -> set` returning the lowercased addresses that must not be contacted again.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_sentlog.py`:

```python
from mailauto.sentlog import load_done, append_result, MAX_ATTEMPTS


def _log(tmp_path, rows):
    p = tmp_path / "sent_log.csv"
    for email, status in rows:
        append_result(str(p), email, status, "boom" if status == "error" else "")
    return str(p)


def test_delivered_address_is_done(tmp_path):
    p = _log(tmp_path, [("a@x.com", "sent")])
    assert load_done(p) == {"a@x.com"}


def test_one_failure_is_not_done_so_it_retries(tmp_path):
    """The 8 real failures on record died to a dropped socket, not a bad
    address. Giving up after one error would silently discard live contacts."""
    p = _log(tmp_path, [("a@x.com", "error")])
    assert load_done(p) == set()


def test_two_failures_are_not_done(tmp_path):
    p = _log(tmp_path, [("a@x.com", "error"), ("a@x.com", "error")])
    assert load_done(p) == set()


def test_three_failures_are_done(tmp_path):
    """Three strikes: a dead address must stop blocking completion, or the
    scheduler retries it every weekday forever and never switches off."""
    p = _log(tmp_path, [("a@x.com", "error")] * 3)
    assert load_done(p) == {"a@x.com"}


def test_more_than_three_failures_stay_done(tmp_path):
    p = _log(tmp_path, [("a@x.com", "error")] * 5)
    assert load_done(p) == {"a@x.com"}


def test_success_after_failures_is_done(tmp_path):
    p = _log(tmp_path, [("a@x.com", "error"), ("a@x.com", "sent")])
    assert load_done(p) == {"a@x.com"}


def test_failures_are_counted_per_address(tmp_path):
    p = _log(tmp_path, [
        ("a@x.com", "error"), ("a@x.com", "error"), ("a@x.com", "error"),
        ("b@x.com", "error"),
    ])
    assert load_done(p) == {"a@x.com"}


def test_addresses_are_matched_case_insensitively(tmp_path):
    """contacts.csv and the log disagree on case; three attempts must count
    as three even when the address is spelled differently each time."""
    p = _log(tmp_path, [("A@x.com", "error"), ("a@X.com", "error"), (" a@x.com ", "error")])
    assert load_done(p) == {"a@x.com"}


def test_missing_log_means_nothing_is_done(tmp_path):
    assert load_done(str(tmp_path / "nope.csv")) == set()


def test_max_attempts_is_three():
    assert MAX_ATTEMPTS == 3


def test_load_done_rejects_a_malformed_log(tmp_path):
    """Same refusal as load_sent: a corrupt log must never be guessed at."""
    p = tmp_path / "sent_log.csv"
    p.write_text("wrong,header\n1,2\n")
    with pytest.raises(ValueError):
        load_done(str(p))
```

Ensure `import pytest` is present at the top of the file.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_sentlog.py -q`
Expected: FAIL — `ImportError: cannot import name 'load_done'`.

- [ ] **Step 3: Implement `load_done`**

In `mailauto/sentlog.py`, add the constant next to `FIELDS`:

```python
MAX_ATTEMPTS = 3
```

Then add, after `load_sent`:

```python
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
```

Factor the shared parsing out of `load_sent` so both functions validate the header identically, and rewrite `load_sent` in terms of it:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_sentlog.py -q`
Expected: PASS. The pre-existing `load_sent` tests must still pass unchanged — if any fails, `_read_rows` changed behaviour and that is a bug, not a test to update.

- [ ] **Step 5: Use it in the send path**

In `send_emails.py`, change the import and the one line in `_load_all`:

```python
from mailauto.sentlog import load_sent, load_done, append_result
```

```python
    sent = load_done(SENT_LOG)
```

Leave the variable named `sent` and leave `cmd_send`'s signature alone — it takes a set of addresses to skip, and the meaning of that set is `_load_all`'s business. `load_sent` stays exported because the tests use it to assert what was actually delivered.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS, all tests.

- [ ] **Step 7: Confirm the real list is unaffected today**

Run: `.venv/bin/python send_emails.py --dry-run`
Expected: pending is unchanged from before this task (the 8 recorded failures each have 1 attempt, well under 3, so they remain pending and will be retried). Sends nothing.

- [ ] **Step 8: Commit**

```bash
git add mailauto/sentlog.py send_emails.py tests/test_sentlog.py
git commit -m "fix: give up on an address after 3 failed attempts so the list can finish"
```
