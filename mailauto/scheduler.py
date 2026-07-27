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
