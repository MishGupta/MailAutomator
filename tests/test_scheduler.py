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


def test_unparseable_stamp_is_treated_as_not_run(tmp_path):
    """Readable text that isn't today's date fails the plain string
    comparison and returns False -- no exception involved."""
    (tmp_path / "last_success").write_text("not a date at all")
    assert scheduler.already_ran_today(dt(), str(tmp_path)) is False


def test_undecodable_stamp_is_treated_as_not_run(tmp_path):
    """Worst case is one extra send attempt, and sent_log.csv makes that
    harmless. Treating garbage as 'already ran' would silently skip a day."""
    (tmp_path / "last_success").write_bytes(b"\xff\xfe\x00\x01garbage")
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


# --- the production entry path -------------------------------------------------
#
# Every test above passes `now` explicitly and overrides all three injectable
# defaults, so none of them exercise what launchd actually calls: `now=None`
# defaulting to the real clock, run_daily.py's import, or _real_send's body.
# These three close that gap. A Saturday is used for the default-clock test so
# that even a broken injection could not reach the real sender.

def test_default_clock_is_used_when_now_is_omitted(tmp_path, monkeypatch):
    """Deleting `now = now or datetime.datetime.now()` would still pass every
    other test in this file, since they all pass `now` explicitly."""
    class FixedDatetime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.datetime(2026, 8, 1, 10, 30)  # a Saturday

    monkeypatch.setattr(scheduler.datetime, "datetime", FixedDatetime)
    rec = Recorder(result())
    exit_code = scheduler.run_scheduled(
        log_dir=str(tmp_path), send=rec.send,
        notify_fn=rec.notify, stop_fn=rec.stop,
    )
    assert exit_code == 0
    assert rec.sends == 0
    assert "weekend" in (tmp_path / "scheduler.log").read_text()


def test_run_daily_imports_the_real_run_scheduled():
    """Importing run_daily must not execute anything (the __main__ guard), but
    it must wire up the exact function launchd will invoke."""
    import run_daily
    assert run_daily.run_scheduled is scheduler.run_scheduled


def test_real_send_wires_load_all_into_cmd_send(monkeypatch):
    """No network, no real config file: _load_all and cmd_send are both faked,
    so this only proves _real_send threads the 5-tuple through correctly."""
    import send_emails

    sentinel = ("conf", "subject_t", "body_t", "contacts", "sent")
    captured = {}

    def fake_load_all(config_path):
        captured["config_path"] = config_path
        return sentinel

    def fake_cmd_send(conf, subject_t, body_t, contacts, sent):
        captured["args"] = (conf, subject_t, body_t, contacts, sent)
        return send_emails.SendResult(1, 0, 0)

    monkeypatch.setattr(send_emails, "_load_all", fake_load_all)
    monkeypatch.setattr(send_emails, "cmd_send", fake_cmd_send)

    outcome = scheduler._real_send("some/config.ini")

    assert captured["config_path"] == "some/config.ini"
    assert captured["args"] == sentinel
    assert outcome == send_emails.SendResult(1, 0, 0)
