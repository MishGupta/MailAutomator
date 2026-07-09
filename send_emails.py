import argparse
import sys
import time
import smtplib

from mailauto.config import load_config
from mailauto.parsing import load_contacts_csv
from mailauto.templating import parse_template, render
from mailauto.sentlog import load_sent, append_result
from mailauto.planner import select_pending
from mailauto import mailer

SENT_LOG = "sent_log.csv"


def _load_all(args):
    conf = load_config(args.config)
    with open(conf.template_path, encoding="utf-8") as f:
        subject_t, body_t = parse_template(f.read())
    contacts = load_contacts_csv(conf.contacts_path)
    sent = load_sent(SENT_LOG)
    return conf, subject_t, body_t, contacts, sent


def cmd_preview(conf, subject_t, body_t, contacts, sent, n=3):
    pending = select_pending(contacts, sent, None)
    print(f"{len(contacts)} contacts, {len(sent)} already sent, {len(pending)} pending.\n")
    for c in pending[:n]:
        subject, body = render(subject_t, body_t, c)
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
    subject, body = render(subject_t, body_t, sample)
    msg = mailer.build_message(conf.address, conf.address, f"[TEST] {subject}",
                               body, conf.resume_path,
                               cc_self=None)
    try:
        smtp = mailer.connect(conf.address, conf.app_password)
    except smtplib.SMTPAuthenticationError:
        print("ERROR: Gmail rejected the login. Check the app password in config.ini "
              "(needs 2-Step Verification + an App Password, not your normal password).",
              file=sys.stderr)
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
    todays = select_pending(contacts, sent, conf.daily_limit)
    if not todays:
        print("Nothing to send — everyone pending is already done or the list is empty.")
        return 0
    print(f"Sending {len(todays)} emails (limit {conf.daily_limit})...")
    try:
        smtp = mailer.connect(conf.address, conf.app_password)
    except smtplib.SMTPAuthenticationError:
        print("ERROR: Gmail rejected the login. Check the app password in config.ini.",
              file=sys.stderr)
        return 1
    ok = 0
    failed = 0
    try:
        for i, c in enumerate(todays, 1):
            subject, body = render(subject_t, body_t, c)
            cc = conf.address if conf.cc_self else None
            try:
                msg = mailer.build_message(conf.address, c.email, subject, body,
                                           conf.resume_path, cc_self=cc)
                mailer.send(smtp, msg)
                append_result(SENT_LOG, c.email, "sent")
                ok += 1
                print(f"  [{i}/{len(todays)}] sent -> {c.email}")
            except Exception as e:  # one bad address must not stop the batch
                append_result(SENT_LOG, c.email, "error", str(e))
                failed += 1
                print(f"  [{i}/{len(todays)}] FAILED -> {c.email}: {e}", file=sys.stderr)
            time.sleep(conf.delay_seconds)
    finally:
        smtp.quit()
    print(f"\nDone. Sent {ok}, failed {failed}. Run again tomorrow for the next batch.")
    return 0


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
        conf, subject_t, body_t, contacts, sent = _load_all(args)
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

    if args.send:
        return cmd_send(conf, subject_t, body_t, contacts, sent)
    if args.test:
        return cmd_test(conf, subject_t, body_t, contacts)
    if args.dry_run:
        cmd_dry_run(conf, contacts, sent)
        return 0
    # default: preview
    cmd_preview(conf, subject_t, body_t, contacts, sent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
