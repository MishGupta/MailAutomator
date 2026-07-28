#!/usr/bin/env bash
# Install (or remove) the LaunchAgent that sends the daily batch.
set -euo pipefail

LABEL="com.mishka.mail-automator"
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PYTHON="$PROJECT/.venv/bin/python"
TARGET="gui/$(id -u)/$LABEL"

if [ "${1:-}" = "--uninstall" ]; then
  launchctl bootout "$TARGET" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Scheduler removed. Nothing will send automatically from now on."
  exit 0
fi

if [ ! -x "$PYTHON" ]; then
  echo "ERROR: no virtualenv python at $PYTHON" >&2
  echo "Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT/logs"

# Absolute paths are baked in because launchd runs with cwd=/ and no PATH.
sed -e "s|__PYTHON__|$PYTHON|g" -e "s|__PROJECT__|$PROJECT|g" \
    "$PROJECT/scripts/$LABEL.plist.template" > "$PLIST"

launchctl bootout "$TARGET" 2>/dev/null || true   # replace any previous copy
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "Installed. Weekdays at 10:30, retrying hourly until 16:00."
echo "Log: $PROJECT/logs/scheduler.log"
launchctl print "$TARGET" | grep -E "state|program|runs" || true
