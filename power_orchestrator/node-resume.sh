#!/bin/sh
# power_orchestrator/node-resume.sh
# Install to: /usr/lib/systemd/system-sleep/node-resume.sh
# Distinguishes 23:00 RTC night-shutdown wakes from Wake-on-LAN wakes and records
# `last_resume_ts` so overdue 5-minute systemd timers respect the 180s post-wake grace window.

STATE_DIR="${SENTRY_STATE_DIR:-/var/tmp/zero_idle_sentry}"
WAKE_FILE="$STATE_DIR/wake_alarm_ts"
ORCHESTRATOR_BIN="${SENTRY_ORCHESTRATOR_BIN:-/usr/local/bin/power-orchestrate.sh}"

case "$1/$2" in
  pre/suspend)
    # Keep services alive in RAM for <3.5s instant resume (avoids 42s cold-start blind spot)
    exit 0
    ;;
  post/suspend)
    NOW=$(date +%s)
    mkdir -p "$STATE_DIR"
    echo "$NOW" > "$STATE_DIR/last_resume_ts"
    if [ -f "$WAKE_FILE" ]; then
      WAKE_TS=$(cat "$WAKE_FILE" 2>/dev/null || echo 0)
      if [ "$WAKE_TS" -gt 0 ] && [ "$NOW" -ge $(( WAKE_TS - 60 )) ]; then
        # Woken by 23:00 RTC alarm for night S5 shutdown: evaluate shutdown immediately
        "$ORCHESTRATOR_BIN" --check-shutdown >/dev/null 2>&1 || true
        exit 0
      fi
    fi
    ;;
esac
