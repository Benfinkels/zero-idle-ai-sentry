#!/usr/bin/env bash
# power_orchestrator/node-sleep.sh
# Clean delayed S3 Suspend-to-RAM (~2.5W, wakes in ~3.5s via Wake-on-LAN or RTC alarm)
#
# Key Root-Cause Fix:
# Disarms duplicate-named PCIe/USB ACPI wake sources (e.g., ASMedia USB 3.1 `PXSX` and PCIe
# root ports `RP01/RP07/RP09/RP17/RP21`) via `/sys/bus/pci/devices/<bdf>/power/wakeup` first,
# then `/proc/acpi/wakeup`, leaving ONLY `GLAN` (Intel I219-V Ethernet) enabled for Wake-on-LAN.
# This eliminates 1-second spurious wake storms and `xhci_hcd` USB resume resets.
set -uo pipefail

WAKE_TARGET="${1:-}"
RTC_WAKEALARM="/sys/class/rtc/rtc0/wakealarm"
STATE_DIR="${SENTRY_STATE_DIR:-/var/tmp/zero_idle_sentry}"
mkdir -p "$STATE_DIR"

# 1. Arm and verify hardware RTC wake alarm if epoch target specified
if [ -n "$WAKE_TARGET" ] && [ "$WAKE_TARGET" -gt 1000000000 ] 2>/dev/null; then
  sudo -n sh -c "echo 0 > $RTC_WAKEALARM && echo $WAKE_TARGET > $RTC_WAKEALARM" 2>/dev/null || true
  HW_VAL=$(cat "$RTC_WAKEALARM" 2>/dev/null || echo "")
  if [ "$HW_VAL" = "$WAKE_TARGET" ]; then
    echo "$WAKE_TARGET" > "$STATE_DIR/wake_alarm_ts"
  fi
fi

# 2. Disable all enabled ACPI wake sources EXCEPT GLAN (Ethernet Wake-on-LAN)
if [ -f /proc/acpi/wakeup ]; then
  for bdf in $(awk '$3 == "*enabled" && $1 != "GLAN" && $4 ~ /^pci:/ {sub(/^pci:/, "", $4); print $4}' /proc/acpi/wakeup); do
    sudo -n tee "/sys/bus/pci/devices/${bdf}/power/wakeup" <<< "disabled" >/dev/null 2>&1 || true
  done
  for dev in $(awk '$3 == "*enabled" && $1 != "GLAN" {print $1}' /proc/acpi/wakeup | sort -u); do
    sudo -n tee /proc/acpi/wakeup <<< "$dev" >/dev/null 2>&1 || true
  done
fi

if grep -q "^GLAN.*\*disabled" /proc/acpi/wakeup 2>/dev/null; then
  sudo -n tee /proc/acpi/wakeup <<< "GLAN" >/dev/null 2>&1 || true
fi

# 3. Schedule systemctl suspend via systemd-run so caller turns complete cleanly
sudo -n systemd-run --on-active=3s /bin/systemctl suspend >/dev/null 2>&1
echo "{\"status\": \"suspending_to_s3\", \"delay_seconds\": 3}"
