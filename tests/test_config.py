import pytest
from mailauto.config import load_config, Config, DEFAULT_DAILY_LIMIT


def _write_config(tmp_path, resume, template, contacts, extra="daily_limit = 250\ndelay_seconds = 1.5\ncc_self = true"):
    cfg = tmp_path / "config.ini"
    cfg.write_text(
        "[gmail]\n"
        "address = you@gmail.com\n"
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
    assert conf.address == "you@gmail.com"
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


def test_load_config_defaults_when_send_section_absent(tmp_path):
    r = tmp_path / "resume.pdf"; r.write_text("x")
    t = tmp_path / "email_template.txt"; t.write_text("Subject: hi\n\nbody")
    c = tmp_path / "contacts.csv"; c.write_text("name,email,title,company\n")
    cfg = tmp_path / "config.ini"
    cfg.write_text(
        "[gmail]\naddress = a@b.com\napp_password = pw\n"
        f"[files]\nresume = {r}\ntemplate = {t}\ncontacts = {c}\n"
    )
    conf = load_config(str(cfg))
    assert conf.daily_limit == DEFAULT_DAILY_LIMIT
    assert conf.delay_seconds == 2.0
    assert conf.cc_self is False


def test_load_config_missing_address_raises_value_error(tmp_path):
    r = tmp_path / "resume.pdf"; r.write_text("x")
    t = tmp_path / "email_template.txt"; t.write_text("Subject: hi\n\nbody")
    c = tmp_path / "contacts.csv"; c.write_text("name,email,title,company\n")
    cfg = tmp_path / "config.ini"
    cfg.write_text(
        "[gmail]\napp_password = pw\n"
        f"[files]\nresume = {r}\ntemplate = {t}\ncontacts = {c}\n"
    )
    with pytest.raises(ValueError):
        load_config(str(cfg))


def test_load_config_allows_percent_in_password(tmp_path):
    r = tmp_path / "resume.pdf"; r.write_text("x")
    t = tmp_path / "email_template.txt"; t.write_text("Subject: hi\n\nbody")
    c = tmp_path / "contacts.csv"; c.write_text("name,email,title,company\n")
    cfg = tmp_path / "config.ini"
    cfg.write_text(
        "[gmail]\naddress = a@b.com\napp_password = ab%cd\n"
        f"[files]\nresume = {r}\ntemplate = {t}\ncontacts = {c}\n"
    )
    conf = load_config(str(cfg))
    assert conf.app_password == "ab%cd"


def _write_smtp_config(tmp_path, resume, template, contacts, gmail_section):
    cfg = tmp_path / "config.ini"
    cfg.write_text(
        f"{gmail_section}"
        "[files]\n"
        f"resume = {resume}\n"
        f"template = {template}\n"
        f"contacts = {contacts}\n"
    )
    return cfg


def _files(tmp_path):
    r = tmp_path / "resume.pdf"; r.write_text("x")
    t = tmp_path / "email_template.txt"; t.write_text("Subject: hi\n\nbody")
    c = tmp_path / "contacts.csv"; c.write_text("name,email,title,company\n")
    return r, t, c


def test_smtp_section_supports_any_provider(tmp_path):
    r, t, c = _files(tmp_path)
    cfg = _write_smtp_config(tmp_path, r, t, c,
        "[smtp]\n"
        "address = me@outlook.com\n"
        "app_password = pw\n"
        "host = smtp-mail.outlook.com\n"
        "port = 587\n")
    conf = load_config(str(cfg))
    assert conf.address == "me@outlook.com"
    assert conf.smtp_host == "smtp-mail.outlook.com"
    assert conf.smtp_port == 587


def test_smtp_host_defaults_to_gmail(tmp_path):
    r, t, c = _files(tmp_path)
    cfg = _write_smtp_config(tmp_path, r, t, c,
        "[smtp]\naddress = a@b.com\napp_password = pw\n")
    conf = load_config(str(cfg))
    assert conf.smtp_host == "smtp.gmail.com"
    assert conf.smtp_port == 587


def test_legacy_gmail_section_still_works(tmp_path):
    """Existing config.ini files must keep working after the rename."""
    r, t, c = _files(tmp_path)
    cfg = _write_smtp_config(tmp_path, r, t, c,
        "[gmail]\naddress = a@gmail.com\napp_password = pw\n")
    conf = load_config(str(cfg))
    assert conf.address == "a@gmail.com"
    assert conf.smtp_host == "smtp.gmail.com"


def test_daily_limit_default_is_safe_under_scheduler_retries(tmp_path):
    """The default must survive the scheduler taking a fresh batch per retry.

    A failed run leaves the day open, so up to MAX_DAILY_FIRES batches can go
    out in one day. default * fires must stay under Gmail's ~500/day cap.
    """
    from mailauto.config import MAX_DAILY_FIRES
    r, t, c = _files(tmp_path)
    cfg = _write_smtp_config(tmp_path, r, t, c,
        "[smtp]\naddress = a@b.com\napp_password = pw\n")
    conf = load_config(str(cfg))
    assert conf.daily_limit == 50
    assert conf.daily_limit * MAX_DAILY_FIRES < 500


def test_shipped_example_config_actually_parses(tmp_path):
    """config.ini.example must load, and must agree with the code defaults.

    Guards two bugs the example previously shipped with: a daily_limit that
    had drifted to 8x the documented value, and trailing ";" comments that
    configparser does not strip -- so a user copying the documented block
    verbatim got a crash on the first run.
    """
    import configparser
    from mailauto.config import DEFAULT_DAILY_LIMIT

    cp = configparser.ConfigParser(interpolation=None)
    cp.read("config.ini.example")

    assert cp.getint("send", "daily_limit") == DEFAULT_DAILY_LIMIT
    cp.getfloat("send", "delay_seconds")
    cp.getboolean("send", "cc_self")
    assert cp.has_section("smtp")
    assert "@" in cp["smtp"]["address"]
