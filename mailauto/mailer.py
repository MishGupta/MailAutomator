import mimetypes
import os
import smtplib
from email.message import EmailMessage


def build_message(from_addr, to_addr, subject, body, resume_path, cc_self=None):
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    if cc_self:
        msg["Cc"] = cc_self
    msg["Subject"] = subject
    msg.set_content(body)

    ctype, _ = mimetypes.guess_type(resume_path)
    maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
    with open(resume_path, "rb") as f:
        data = f.read()
    msg.add_attachment(data, maintype=maintype, subtype=subtype,
                       filename=os.path.basename(resume_path))
    return msg


# Seconds to wait on any SMTP socket operation before giving up, so a hung
# Gmail connection can't stall an entire send batch indefinitely.
SMTP_TIMEOUT = 30


def connect(address, app_password, timeout=SMTP_TIMEOUT):
    smtp = smtplib.SMTP("smtp.gmail.com", 587, timeout=timeout)
    smtp.starttls()
    smtp.login(address, app_password)
    return smtp


def send(smtp, message):
    smtp.send_message(message)
