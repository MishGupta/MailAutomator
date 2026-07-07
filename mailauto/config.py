import configparser
import os
from dataclasses import dataclass


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


def load_config(path: str = "config.ini") -> Config:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Config file not found: {path}. Copy config.ini.example to config.ini and fill it in."
        )
    cp = configparser.ConfigParser()
    cp.read(path)
    try:
        address = cp["gmail"]["address"].strip()
        app_password = cp["gmail"]["app_password"].strip()
        resume_path = cp["files"]["resume"].strip()
        template_path = cp["files"].get("template", "email_template.txt").strip()
        contacts_path = cp["files"].get("contacts", "contacts.csv").strip()
        daily_limit = cp["send"].getint("daily_limit", 400)
        delay_seconds = cp["send"].getfloat("delay_seconds", 2.0)
        cc_self = cp["send"].getboolean("cc_self", False)
    except KeyError as e:
        raise ValueError(f"Missing required config value: {e}")

    for label, p in [("resume", resume_path), ("template", template_path), ("contacts", contacts_path)]:
        if not os.path.exists(p):
            raise FileNotFoundError(f"{label} file not found: {p}")

    return Config(address, app_password, resume_path, template_path,
                  contacts_path, daily_limit, delay_seconds, cc_self)
