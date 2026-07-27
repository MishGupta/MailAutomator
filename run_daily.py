"""Entry point launchd invokes. Every decision lives in mailauto.scheduler."""

import sys

from mailauto.scheduler import run_scheduled

if __name__ == "__main__":
    raise SystemExit(run_scheduled())
