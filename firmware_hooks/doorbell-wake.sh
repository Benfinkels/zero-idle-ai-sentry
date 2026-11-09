#!/bin/sh
# /system/sdcard/config/userscripts/motiondetection/doorbell-wake.sh
# Triggered by Dafang-Hacks (Ingenic T20 MIPS 2.5W camera) when hardware ISP motion
# occurs inside the calibrated walkway ROI (region_of_interest=480,480,860,715).
#
# Key Engineering Design:
# 1. Short 12s burst debounce (NOT a 180s blindfold) so an arriving delivery van on the
#    street never locks out the camera before the driver steps onto the walkway.
# 2. Immediate Wake-on-LAN broadcast at t=0s so the sleeping GPU server starts its ~3.5s
#    S3 resume in parallel with camera frame capture.
# 3. Spaced 3-frame burst (t=0s, 1.0s, 3.0s) written to RAM/SD (/system/sdcard/www/burst/)
#    so visitors stepping off the curb are mid-walkway by frame 2/3.

SENTRY_MAC="${SENTRY_TARGET_MAC:-00:11:22:33:44:55}"
SENTRY_IP="${SENTRY_SERVER_IP:-192.168.1.100}"
SENTRY_PORT="${SENTRY_SERVER_PORT:-8099}"
COOLDOWN_FILE="/tmp/doorbell_wake.ts"
COOLDOWN_SEC=12
LOG_FILE="/tmp/doorbell_wake.log"
BURST_DIR="/system/sdcard/www/burst"

if [ "$1" != "on" ]; then
    exit 0
fi

NOW=$(date +%s)
if [ -f "$COOLDOWN_FILE" ]; then
    LAST=$(cat "$COOLDOWN_FILE" 2>/dev/null || echo 0)
    if [ $(( NOW - LAST )) -lt "$COOLDOWN_SEC" ]; then
        exit 0
    fi
fi
echo "$NOW" > "$COOLDOWN_FILE"

echo "[$(date)] Motion in walkway ROI -> broadcasting WoL to GPU node ($SENTRY_MAC)..." >> "$LOG_FILE"

# 1. Immediately broadcast Wake-on-LAN Magic Packet (3x for reliability over Wi-Fi)
for i in 1 2 3; do
    /system/sdcard/bin/busybox ether-wake -b -i wlan0 "$SENTRY_MAC" 2>/dev/null
    /system/sdcard/bin/busybox ether-wake -i wlan0 "$SENTRY_MAC" 2>/dev/null
done

# 2. Capture 3-frame burst spaced across 3.0s (t=0s, 1.0s, 3.0s) while server resumes from S3
mkdir -p "$BURST_DIR"
/system/sdcard/bin/getimage > "$BURST_DIR/f1.jpg" 2>/dev/null
sleep 1
/system/sdcard/bin/getimage > "$BURST_DIR/f2.jpg" 2>/dev/null
sleep 2
/system/sdcard/bin/getimage > "$BURST_DIR/f3.jpg" 2>/dev/null

# 3. Poll server's doorbell receiver until it wakes (S3 ~3.5s, S5 cold boot ~27s)
MAX_WAIT=35
ELAPSED=0
while [ "$ELAPSED" -lt "$MAX_WAIT" ]; do
    if /system/sdcard/bin/busybox wget -q -T 2 -O /dev/null "http://${SENTRY_IP}:${SENTRY_PORT}/api/doorbell/trigger?ts=${NOW}" 2>/dev/null; then
        echo "[$(date)] Delivered burst ts=${NOW} to ${SENTRY_IP}:${SENTRY_PORT} on attempt ${ELAPSED}" >> "$LOG_FILE"
        exit 0
    fi
    /system/sdcard/bin/busybox ether-wake -b -i wlan0 "$SENTRY_MAC" 2>/dev/null
    sleep 1
    ELAPSED=$(( ELAPSED + 1 ))
done

echo "[$(date)] ERROR: GPU server did not respond within ${MAX_WAIT}s" >> "$LOG_FILE"
exit 1
