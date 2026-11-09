#!/bin/sh
# Dafang-Hacks / Ingenic T20 (2.5W Linux Camera) Motion Hook
# Place at: /system/sdcard/config/userscripts/motiondetection/wake_node.sh
# Automatically broadcasts a Wake-on-LAN Magic Packet to wake the sleeping AI Agent node.

TARGET_MAC="${SENTRY_TARGET_MAC:-00:11:22:33:44:55}"
BROADCAST_IP="${SENTRY_BROADCAST_IP:-192.168.1.255}"

# BusyBox ether-wake or raw UDP magic packet
if command -v ether-wake >/dev/null 2>&1; then
    ether-wake -b "$TARGET_MAC"
else
    /system/sdcard/bin/busybox ether-wake "$TARGET_MAC" 2>/dev/null
fi

logger -t zero-idle-sentry "Motion tripwire fired: sent Wake-on-LAN to $TARGET_MAC ($BROADCAST_IP)"
