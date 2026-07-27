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
