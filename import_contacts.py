import argparse
import os
import sys

from mailauto.parsing import parse_pdf, write_contacts_csv


def main(argv=None):
    ap = argparse.ArgumentParser(description="Extract HR contacts from a PDF into contacts.csv")
    ap.add_argument("--pdf", default="HR_Contact_List.pdf", help="input PDF path")
    ap.add_argument("--out", default="contacts.csv", help="output CSV path")
    args = ap.parse_args(argv)

    if not os.path.exists(args.pdf):
        print(f"ERROR: PDF not found: {args.pdf}", file=sys.stderr)
        return 1
    if os.path.exists(args.out):
        print(f"WARNING: {args.out} already exists and will be overwritten.")

    contacts = parse_pdf(args.pdf)
    write_contacts_csv(args.out, contacts)
    print(f"Extracted {len(contacts)} contacts -> {args.out}")
    if contacts:
        c = contacts[0]
        print(f"First row: name={c.name!r} email={c.email!r} title={c.title!r} company={c.company!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
