import configparser
import os
from dataclasses import dataclass

# Gmail's SMTP endpoint, used when the config names no other provider. Kept as
# the default because this started as a Gmail-only tool and existing config.ini
# files have no host/port keys at all.
DEFAULT_SMTP_HOST = "smtp.gmail.com"
DEFAULT_SMTP_PORT = 587

# How many times launchd fires the scheduler in one day (10:30 through 15:30,
# see scripts/com.mishka.mail-automator.plist.template). It matters here
# because a failed run records no success stamp, so the next fire takes a
# *fresh* batch of daily_limit: the true worst-case daily volume is
# daily_limit * MAX_DAILY_FIRES, not daily_limit.
MAX_DAILY_FIRES = 6

# 50 * 6 fires = 300 worst case, safely under the ~500/day Gmail allows a free
# account. Raising this raises the worst case by the same multiple.
DEFAULT_DAILY_LIMIT = 50


@dataclass
class Config:
    address: str
    app_password: str
    resume_path: str
    template_path: str
    contacts_path: str
    daily_limit: int
    delay_seconds: float
    cc_self: bool
    smtp_host: str = DEFAULT_SMTP_HOST
    smtp_port: int = DEFAULT_SMTP_PORT


def _credentials_section(cp) -> str:
    """Return the section holding address/app_password.

    Prefers [smtp]; falls back to the original [gmail] so config.ini files
    written before the rename keep working untouched.
    """
    if cp.has_section("smtp"):
        return "smtp"
    if cp.has_section("gmail"):
        return "gmail"
    raise ValueError(
        "Missing required config section: expected [smtp] (or the older "
        "[gmail]). Copy config.ini.example to config.ini and fill it in."
    )


def load_config(path: str = "config.ini") -> Config:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Config file not found: {path}. Copy config.ini.example to config.ini and fill it in."
        )
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(path)

    section = _credentials_section(cp)

    # Required values: absence is a hard error.
    try:
        address = cp[section]["address"].strip()
        app_password = cp[section]["app_password"].strip()
        resume_path = cp["files"]["resume"].strip()
    except KeyError as e:
        raise ValueError(f"Missing required config value: {e}")

    # Server defaults to Gmail so an existing [gmail] config needs no edits.
    smtp_host = cp.get(section, "host", fallback=DEFAULT_SMTP_HOST).strip()
    try:
        smtp_port = cp.getint(section, "port", fallback=DEFAULT_SMTP_PORT)
    except ValueError:
        raise ValueError(
            f"[{section}] port must be a whole number, e.g. 587."
        )

    # Optional values: fall back even when the whole section is absent.
    template_path = cp.get("files", "template", fallback="email_template.txt").strip()
    contacts_path = cp.get("files", "contacts", fallback="contacts.csv").strip()
    daily_limit = cp.getint("send", "daily_limit", fallback=DEFAULT_DAILY_LIMIT)
    delay_seconds = cp.getfloat("send", "delay_seconds", fallback=2.0)
    cc_self = cp.getboolean("send", "cc_self", fallback=False)

    for label, p in [("resume", resume_path), ("template", template_path), ("contacts", contacts_path)]:
        if not os.path.exists(p):
            raise FileNotFoundError(f"{label} file not found: {p}")

    return Config(address, app_password, resume_path, template_path,
                  contacts_path, daily_limit, delay_seconds, cc_self,
                  smtp_host, smtp_port)
