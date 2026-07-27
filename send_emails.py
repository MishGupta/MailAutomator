import argparse
import sys
import time
import smtplib
from dataclasses import dataclass

from mailauto.config import load_config
from mailauto.parsing import load_contacts_csv
from mailauto.templating import parse_template, render, strip_bold, to_html
from mailauto.sentlog import load_sent, load_done, append_result
from mailauto.planner import select_pending
from mailauto import mailer

SENT_LOG = "sent_log.csv"


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


class ConnectionProblem(Exception):
    """A connection or auth failure, phrased in terms the user can act on."""


def connect_or_explain(conf):
    """Connect to Gmail, announcing progress first.

    Connecting takes a couple of seconds; without output the terminal looks
    frozen and users interrupt it. OSError covers socket timeouts and DNS/
    network failures; SMTPException covers protocol-level ones.
    """
    print(f"Connecting to Gmail as {conf.address} ...", flush=True)
    try:
        smtp = mailer.connect(conf.address, conf.app_password)
    except smtplib.SMTPAuthenticationError:
        raise ConnectionProblem(
            "Gmail rejected the login. Check app_password in config.ini — it must be a "
            "16-character App Password (2-Step Verification required), not your normal "
            "Gmail password."
        )
    except (OSError, smtplib.SMTPException) as e:
        raise ConnectionProblem(
            f"Could not reach Gmail ({type(e).__name__}: {e}). Check your internet "
            "connection, or whether this network blocks outbound port 587."
        )
    print("Connected.", flush=True)
    return smtp


# Faults this one recipient owns: a bad address, a rejected message. The
# connection is fine, so log it and move to the next contact.
RECIPIENT_ERRORS = (
    smtplib.SMTPRecipientsRefused,
    smtplib.SMTPSenderRefused,
    smtplib.SMTPDataError,
    smtplib.SMTPNotSupportedError,
)

# A dead socket is a batch-level problem, not the recipient's fault. smtplib
# signals it with SMTPServerDisconnected ("connection reset by peer", and then
# "please run connect() first" on every later call); OSError covers the raw
# socket errors and timeouts underneath it.
#
# smtplib.SMTPException subclasses OSError, so this tuple would also swallow the
# recipient faults above. Every except-chain below must therefore test
# RECIPIENT_ERRORS *before* CONNECTION_ERRORS.
CONNECTION_ERRORS = (
    smtplib.SMTPServerDisconnected,
    smtplib.SMTPConnectError,
    smtplib.SMTPHeloError,
    OSError,
)

RECONNECT_ATTEMPTS = 3


def send_with_reconnect(smtp, conf, msg, attempts=RECONNECT_ATTEMPTS):
    """Send one message, rebuilding the connection if it has died.

    Gmail drops a long-lived SMTP connection for its own reasons, and a laptop
    suspending mid-batch kills it too. Once the socket is gone every subsequent
    send raises instantly, so without reconnecting here the rest of the batch
    would be written off one contact at a time against a connection that is
    never coming back.

    Returns the live SMTP session (a new one if it had to reconnect) so the
    caller keeps using it. Raises ConnectionProblem if Gmail stays unreachable.

    A reconnect re-sends the message that failed. If the connection died after
    Gmail accepted it but before acknowledging, that contact could get a
    duplicate -- far preferable to never being contacted at all.
    """
    for attempt in range(1, attempts + 1):
        try:
            mailer.send(smtp, msg)
            return smtp
        except smtplib.SMTPAuthenticationError:
            raise ConnectionProblem(
                "Gmail rejected the login while re-connecting. Check app_password in config.ini."
            )
        except RECIPIENT_ERRORS:
            raise  # this contact's problem, not the connection's; caller logs it
        except CONNECTION_ERRORS as e:
            if attempt == attempts:
                raise ConnectionProblem(
                    f"Lost the connection to Gmail and could not get it back after "
                    f"{attempts} attempts ({type(e).__name__}: {e})."
                )
            backoff = 5 * attempt
            print(f"  connection lost ({e}); reconnecting in {backoff}s ...", flush=True)
            try:
                smtp.close()
            except Exception:
                pass  # already dead; nothing to salvage
            time.sleep(backoff)
            try:
                smtp = mailer.connect(conf.address, conf.app_password)
                print("  reconnected.", flush=True)
            except CONNECTION_ERRORS + (smtplib.SMTPException,) as ce:
                print(f"  reconnect failed ({ce}).", flush=True)
                smtp = _DeadSMTP()  # keeps the retry loop honest until attempts run out


class _DeadSMTP:
    """Stand-in used when a reconnect fails, so the next attempt fails fast."""

    def send_message(self, msg):
        raise smtplib.SMTPServerDisconnected("no connection to Gmail")

    def close(self):
        pass

    def quit(self):
        pass


def render_parts(subject_t, body_t, contact):
    """Render one contact into (subject, plain body, html body).

    Subjects are always plain — mail clients show no formatting there, so any
    ** markers must be stripped rather than sent literally.
    """
    subject, body = render(subject_t, body_t, contact)
    return strip_bold(subject), strip_bold(body), to_html(body)


def _load_all(config_path):
    conf = load_config(config_path)
    with open(conf.template_path, encoding="utf-8") as f:
        subject_t, body_t = parse_template(f.read())
    contacts = load_contacts_csv(conf.contacts_path)
    sent = load_done(SENT_LOG)
    return conf, subject_t, body_t, contacts, sent


def cmd_preview(conf, subject_t, body_t, contacts, sent, n=3):
    pending = select_pending(contacts, sent, None)
    print(f"{len(contacts)} contacts, {len(sent)} already sent, {len(pending)} pending.\n")
    for c in pending[:n]:
        subject, body, _ = render_parts(subject_t, body_t, c)
        print("=" * 60)
        print(f"To: {c.email}")
        print(f"Subject: {subject}")
        print(f"[attachment: {conf.resume_path}]")
        print("-" * 60)
        print(body)
        print()
    print(f"(Preview only — nothing sent. Showed {min(n, len(pending))} of {len(pending)}.)")


def cmd_dry_run(conf, contacts, sent):
    pending = select_pending(contacts, sent, None)
    todays = select_pending(contacts, sent, conf.daily_limit)
    print(f"Total contacts:   {len(contacts)}")
    print(f"Already sent:     {len(sent)}")
    print(f"Pending:          {len(pending)}")
    print(f"Daily limit:      {conf.daily_limit}")
    print(f"This run would send: {len(todays)}")


def cmd_test(conf, subject_t, body_t, contacts):
    sample = contacts[0] if contacts else None
    if sample is None:
        print("No contacts to build a sample from.", file=sys.stderr)
        return 1
    subject, body, html = render_parts(subject_t, body_t, sample)
    msg = mailer.build_message(conf.address, conf.address, f"[TEST] {subject}",
                               body, conf.resume_path,
                               cc_self=None, html_body=html)
    try:
        smtp = connect_or_explain(conf)
    except ConnectionProblem as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    try:
        mailer.send(smtp, msg)
    except Exception as e:
        print(f"ERROR: test send failed: {e}", file=sys.stderr)
        return 1
    finally:
        smtp.quit()
    print(f"Test email sent to yourself ({conf.address}). Check your inbox.")
    return 0


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
    ok = 0
    failed = 0
    aborted = None
    try:
        for i, c in enumerate(todays, 1):
            subject, body, html = render_parts(subject_t, body_t, c)
            cc = conf.address if conf.cc_self else None
            try:
                msg = mailer.build_message(conf.address, c.email, subject, body,
                                           conf.resume_path, cc_self=cc,
                                           html_body=html)
                smtp = send_with_reconnect(smtp, conf, msg)
                append_result(SENT_LOG, c.email, "sent")
                ok += 1
                print(f"  [{i}/{len(todays)}] sent -> {c.email}")
            except ConnectionProblem as e:
                # Gmail is gone for good. Stop here and leave every remaining
                # contact unrecorded, so the next run picks them up untouched.
                aborted = e
                break
            except Exception as e:  # one bad address must not stop the batch
                append_result(SENT_LOG, c.email, "error", str(e))
                failed += 1
                print(f"  [{i}/{len(todays)}] FAILED -> {c.email}: {e}", file=sys.stderr)
            time.sleep(conf.delay_seconds)
    finally:
        try:
            smtp.quit()
        except Exception:
            pass  # a dead connection has nothing to close politely

    if aborted:
        remaining = len(todays) - ok - failed
        print(f"\nERROR: {aborted}", file=sys.stderr)
        print(f"Stopped after {ok} sent, {failed} failed. The remaining {remaining} "
              f"contacts were not touched — just run --send again to pick up where "
              f"this left off.", file=sys.stderr)
        return SendResult(ok, failed, len(pending) - ok, aborted=str(aborted))

    print(f"\nDone. Sent {ok}, failed {failed}. Run again tomorrow for the next batch.")
    return SendResult(ok, failed, len(pending) - ok)


def validate_limit(limit):
    """Return limit unchanged if None or a positive int; raise ValueError otherwise.
    Prevents `--limit 0`/negative from silently disabling the daily cap and
    sending to the entire contact list at once."""
    if limit is None:
        return None
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError(f"--limit must be a positive whole number (got {limit!r}).")
    return limit


def main(argv=None):
    ap = argparse.ArgumentParser(description="Send personalized HR outreach emails.")
    ap.add_argument("--config", default="config.ini")
    ap.add_argument("--limit", type=int, default=None, help="override daily_limit for this run")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--preview", action="store_true", help="show sample emails (default)")
    mode.add_argument("--dry-run", action="store_true", help="show counts only")
    mode.add_argument("--test", action="store_true", help="send one test email to yourself")
    mode.add_argument("--send", action="store_true", help="actually send today's batch")
    args = ap.parse_args(argv)

    try:
        conf, subject_t, body_t, contacts, sent = _load_all(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    try:
        validated = validate_limit(args.limit)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    if validated is not None:
        conf.daily_limit = validated

    try:
        if args.send:
            return cmd_send(conf, subject_t, body_t, contacts, sent).exit_code
        if args.test:
            return cmd_test(conf, subject_t, body_t, contacts)
        if args.dry_run:
            cmd_dry_run(conf, contacts, sent)
            return 0
        # default: preview
        cmd_preview(conf, subject_t, body_t, contacts, sent)
        return 0
    except KeyboardInterrupt:
        # Already-sent emails stay recorded in sent_log.csv, so a resumed run skips them.
        print("\nCancelled. Nothing further was sent.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
