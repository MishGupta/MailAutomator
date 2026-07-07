import pytest
from mailauto.config import load_config, Config


def _write_config(tmp_path, resume, template, contacts, extra="daily_limit = 250\ndelay_seconds = 1.5\ncc_self = true"):
    cfg = tmp_path / "config.ini"
    cfg.write_text(
        "[gmail]\n"
        "address = infogupta007@gmail.com\n"
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
    assert conf.address == "infogupta007@gmail.com"
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
