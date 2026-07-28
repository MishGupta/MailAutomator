#!/usr/bin/env bash
# Install (or remove) the LaunchAgent that sends the daily batch.
set -euo pipefail

LABEL="com.mishka.mail-automator"
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PYTHON="$PROJECT/.venv/bin/python"
TARGET="gui/$(id -u)/$LABEL"

usage() {
  echo "Usage: $0 [--uninstall]" >&2
  echo "  (no argument)   install/refresh the scheduler" >&2
  echo "  --uninstall     stop and remove the scheduler" >&2
}

if [ $# -gt 1 ]; then
  usage
  exit 1
fi

case "${1:-}" in
  "")
    ;;
  --uninstall)
    launchctl bootout "$TARGET" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Scheduler removed. Nothing will send automatically from now on."
    exit 0
    ;;
  *)
    # Anything else -- a typo'd flag like --uninstal, -u, or --off -- must
    # not silently fall through to installing. This is the one command whose
    # entire job is turning the scheduler off.
    usage
    exit 1
    ;;
esac

if [ ! -x "$PYTHON" ]; then
  echo "ERROR: no virtualenv python at $PYTHON" >&2
  echo "Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT/logs"

# Absolute paths are baked in because launchd runs with cwd=/ and no PATH.
# The replacement text has to be escaped for sed's own special characters --
# an unescaped "&" in the path would otherwise expand to the whole matched
# text (__PYTHON__ or __PROJECT__) instead of being inserted literally,
# leaving that placeholder still in the installed plist.
_sed_escape_replacement() {
  printf '%s' "$1" | sed -e 's/[&\]/\\&/g'
}
PYTHON_ESCAPED="$(_sed_escape_replacement "$PYTHON")"
PROJECT_ESCAPED="$(_sed_escape_replacement "$PROJECT")"
sed -e "s|__PYTHON__|$PYTHON_ESCAPED|g" -e "s|__PROJECT__|$PROJECT_ESCAPED|g" \
    "$PROJECT/scripts/$LABEL.plist.template" > "$PLIST"

launchctl bootout "$TARGET" 2>/dev/null || true   # replace any previous copy
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "Installed. Weekdays at 10:30, retrying hourly until 16:00."
echo "Log: $PROJECT/logs/scheduler.log"
launchctl print "$TARGET" | grep -E "state|program|runs" || true
