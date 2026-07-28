"""Decides whether a launchd fire should actually send today's batch.

launchd is deliberately dumb here: it fires six times every day, and every
scheduling rule lives in this module. That split exists because launchd replays
calendar events it missed while the Mac was asleep -- a Friday-afternoon event
can arrive on Saturday morning -- so the only trustworthy answer to "should
this run?" comes from checking the clock now, not from what launchd was asked
to do.
"""

import datetime
import os
import subprocess

from mailauto.sentlog import MAX_ATTEMPTS

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


def _real_send(config_path="config.ini"):
    """Run one batch through the ordinary CLI code path.

    Imported here rather than at module scope: send_emails is a top-level
    script that imports this package's siblings, and keeping the dependency
    inside the call avoids an import cycle at load time.
    """
    import send_emails
    conf, subject_t, body_t, contacts, sent = send_emails._load_all(config_path)
    return send_emails.cmd_send(conf, subject_t, body_t, contacts, sent)


def _real_abandoned():
    """Addresses retired at the retry cap without ever being delivered.

    Imported here rather than at module scope for the same reason as
    _real_send: send_emails is a top-level script and importing it at load
    time would create a cycle.
    """
    import send_emails
    from mailauto.sentlog import load_abandoned
    return load_abandoned(send_emails.SENT_LOG)


def run_scheduled(now=None, *, log_dir=LOG_DIR, config_path="config.ini",
                  send=None, notify_fn=notify, stop_fn=stop_agent,
                  abandoned_fn=None):
    """One launchd fire. Returns a process exit code.

    Every gate that rejects exits 0 and logs a single line -- a skipped fire is
    normal operation, not an error, and launchd should not treat it as one.
    """
    now = now or datetime.datetime.now()
    send = send or _real_send
    abandoned_fn = abandoned_fn or _real_abandoned

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
        notify_fn(f"Stopped after {result.sent} sent — will retry on the next scheduled run.")
        return 1

    record_success(now, log_dir)
    log(f"sent {result.sent}, failed {result.failed}, {result.remaining} left",
        now, log_dir)

    if result.remaining == 0:
        # Losing the abandoned count must never prevent the scheduler from
        # switching itself off, so a raising abandoned_fn is swallowed here.
        try:
            abandoned = abandoned_fn()
        except Exception as e:
            log(f"could not determine abandoned contacts: {type(e).__name__}: {e}",
                now, log_dir)
            abandoned = set()

        # Log before stopping: stop_agent boots out this very process.
        if abandoned:
            log("all contacts complete — stopping the scheduler. "
                f"never reached after {MAX_ATTEMPTS} attempts: {sorted(abandoned)}",
                now, log_dir)
            notify_fn(f"All contacts done. {len(abandoned)} could not be reached "
                      f"after {MAX_ATTEMPTS} attempts. Scheduler stopped.")
        else:
            log("all contacts complete — stopping the scheduler", now, log_dir)
            notify_fn("All contacts complete. Scheduler stopped.")
        stop_fn()
        return 0

    notify_fn(f"Sent {result.sent}, failed {result.failed}. {result.remaining} left.")
    return 0
