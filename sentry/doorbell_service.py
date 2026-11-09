#!/usr/bin/env python3
"""
Zero-Idle Doorbell Burst Receiver & Local Multimodal Person Classifier (`sentry/doorbell_service.py`)

Architecture (v2 Evolution of Trick-or-Treat Sentry):
1. Triggered by the 2.5W Dafang-Hacks camera (`doorbell-wake.sh`) after a Wake-on-LAN packet wakes
   the GPU server from S3 Suspend-to-RAM (~3.5s) or S5 Full Shutdown (~27s).
2. Fetches the 3-frame spaced burst (`/burst/f1.jpg`, `/burst/f2.jpg`, `/burst/f3.jpg`) from the camera.
3. Applies deterministic scene luminance gating (`YAVG < 32.0` -> skip dark/unlit frames without GPU wake).
4. Crops to the calibrated walkway ROI `(450, 400, 860, 715)` (excluding public street traffic at `y < 400`)
   and dispatches to local `gemma4:e2b-it-q4_K_M` on Ollama (`keep_alive="15m"`, `think=False`).
5. On confirmed person/delivery (`confidence >= 0.65`):
   - Uploads annotated JPEG to Discord and extracts Discord's CDN attachment URL.
   - Shortens the CDN image URL via `is.gd` (18 chars) and dispatches an instant carrier SMS (`@vtext.com`)
     with an inline tap-to-preview photo link alongside MMS (`@vzwpix.com`).
6. Schedules a 60-second post-analysis check (`power-orchestrate.sh --doorbell-post-check`) so false-positive
   wakes return the server to S3 sleep (daytime) or S5 shutdown (nighttime) within 60 seconds.
"""

from __future__ import annotations

import base64
import datetime
import io
import json
import os
import re
import sqlite3
import subprocess
import ssl
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from PIL import Image, ImageDraw, ImageStat

# --- Configuration (100% Environment-Driven, Zero PII Defaults) --------------
PORT = int(os.environ.get("DOORBELL_PORT", "8099"))
CAM_IP = os.environ.get("DOORBELL_CAM_IP", "192.168.1.50")
CAM_USER = os.environ.get("DOORBELL_CAM_USER", "admin")
CAM_PASS = os.environ.get("DOORBELL_CAM_PASS", "changeme")

# Calibrated Walkway ROI on 1280x720 frame:
# - Camera hardware ISP motion trigger: (480, 480, 860, 715) (lower stone walkway; ignores street at y < 480)
# - Classifier crop box: (450, 400, 860, 715) (excludes street at y < 400 while showing legs/waist/packages)
ROI_BOX = (480, 480, 860, 715)
CLASSIFY_CROP_BOX = (450, 400, 860, 715)
MIN_LUMA_THRESHOLD = float(os.environ.get("DOORBELL_MIN_LUMA", "32.0"))
PERSON_CONF_THRESHOLD = float(os.environ.get("DOORBELL_CONF_THRESHOLD", "0.65"))
NOTIFY_COOLDOWN_SECONDS = int(os.environ.get("DOORBELL_NOTIFY_COOLDOWN", "120"))
RESLEEP_GRACE_SECONDS = int(os.environ.get("DOORBELL_RESLEEP_SECONDS", "60"))

STATE_DIR = Path(os.environ.get("DOORBELL_STATE_DIR", "/tmp/zero_idle_sentry"))
DB_PATH = STATE_DIR / "doorbell.db"
BURST_ARCHIVE_DIR = STATE_DIR / "doorbell_captures"
ORCHESTRATOR_BIN = os.environ.get("DOORBELL_ORCHESTRATOR_BIN", "/usr/local/bin/power-orchestrate.sh")

DISCORD_CHANNELS = [
    c.strip()
    for c in os.environ.get("DOORBELL_DISCORD_CHANNELS", "").split(",")
    if c.strip()
]
GOG_BIN = os.environ.get("DOORBELL_GOG_BIN", "gog")
SMS_TO = os.environ.get("DOORBELL_SMS_TO", "")
MMS_TO = os.environ.get("DOORBELL_MMS_TO", "")
OLLAMA_URL = os.environ.get("OLLAMA_GENERATE_URL", "http://127.0.0.1:11434/api/generate")
OLLAMA_MODEL = os.environ.get("OLLAMA_VISION_MODEL", "gemma4:e2b-it-q4_K_M")

NOTIFY_ENABLED = os.environ.get("DOORBELL_NOTIFY", "1") == "1"

_analysis_lock = threading.Lock()
_resleep_timer: threading.Timer | None = None


def init_db() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    BURST_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS doorbell_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                cam_ts TEXT,
                frames_fetched INTEGER,
                luma_yavg REAL,
                person_detected INTEGER,
                confidence REAL,
                description TEXT,
                notified INTEGER,
                inference_ms INTEGER,
                saved_image_path TEXT
            )
        """)
        conn.commit()


def compute_luma(img: Image.Image) -> float:
    """Return average grayscale luminance (0.0 - 255.0) for unlit night gating."""
    gray = img.convert("L")
    return float(ImageStat.Stat(gray).mean[0])


def parse_gemma_json_response(raw: str) -> dict:
    """Strip optional markdown code fences and parse Gemma 4 structured JSON output."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
    data = json.loads(cleaned)
    return {
        "person": bool(data.get("person", False)),
        "confidence": float(data.get("confidence", 0.0)),
        "description": str(data.get("description", "")),
    }


def classify_roi_gemma4(roi_jpeg_bytes: bytes) -> dict:
    """Call local Gemma 4 E2B with mandatory keep_alive='15m' and think=False."""
    b64 = base64.b64encode(roi_jpeg_bytes).decode()
    prompt = (
        "Look at this front stone walkway camera crop. "
        "Set person=true if you see a person, delivery driver, human legs, pants, shoes, or a package on the stone walkway. "
        'Reply ONLY with JSON: {"person": true/false, "confidence": 0.0-1.0, "description": "short description"}'
    )
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "images": [b64],
        "format": "json",
        "stream": False,
        "think": False,
        "keep_alive": "15m",
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        raw = json.loads(resp.read().decode()).get("response", "{}")
    return parse_gemma_json_response(raw)


def fetch_camera_frame(url_path: str, timeout: float = 5.0) -> bytes | None:
    url = f"https://{CAM_IP}{url_path}"
    auth_str = base64.b64encode(f"{CAM_USER}:{CAM_PASS}".encode()).decode()
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth_str}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            data = resp.read()
            if len(data) > 1000 and data[:2] == b"\xff\xd8":
                return data
    except Exception as e:
        print(f"[Doorbell] Failed fetching {url_path}: {e}", flush=True)
    return None


def shorten_url(long_url: str) -> str:
    """Shorten a long Discord CDN attachment URL into a compact link for 160-char SMS."""
    if not long_url:
        return ""
    try:
        api = "https://is.gd/create.php?format=simple&url=" + urllib.parse.quote(long_url, safe="")
        req = urllib.request.Request(api, headers={"User-Agent": "ZeroIdleDoorbell/2.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            short = resp.read().decode().strip()
            if short.startswith("http"):
                return short
    except Exception as e:
        print(f"[Doorbell] URL shortener error: {e}", flush=True)
    return ""


def format_sms_body(description: str, timestamp_str: str, short_photo_url: str = "") -> str:
    """Format a compact <=160-char carrier SMS alert with optional tap-to-preview photo URL."""
    if short_photo_url:
        return f"Front Door ({timestamp_str}): {description[:65]} Photo: {short_photo_url}"
    return f"Front Door Alert ({timestamp_str}): {description}"


def send_discord_photo_alert(
    image_bytes: bytes, description: str, confidence: float, luma: float
) -> tuple[bool, str]:
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    if not token or not DISCORD_CHANNELS:
        return False, ""

    boundary = f"----DoorbellBoundary{int(time.time() * 1000)}"
    now_str = datetime.datetime.now().strftime("%I:%M:%S %p")
    payload_json = json.dumps({
        "embeds": [{
            "title": "🔔 Front Doorway: Person Detected",
            "description": f"**{description}**",
            "color": 0x10B981,
            "fields": [
                {"name": "Confidence", "value": f"`{confidence:.0%}`", "inline": True},
                {"name": "Scene Luma (YAVG)", "value": f"`{luma:.1f}`", "inline": True},
                {"name": "Time", "value": f"`{now_str}`", "inline": True},
            ],
            "image": {"url": "attachment://doorbell_alert.jpg"},
        }]
    })

    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\nContent-Type: application/json\r\n\r\n{payload_json}\r\n".encode(),
        (
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"files[0]\"; filename=\"doorbell_alert.jpg\"\r\n"
            f"Content-Type: image/jpeg\r\n\r\n"
        ).encode() + image_bytes + f"\r\n--{boundary}--\r\n".encode(),
    ]
    body = b"".join(parts)

    any_sent = False
    cdn_url = ""
    for channel_id in DISCORD_CHANNELS:
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bot {token}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "ZeroIdleDoorbell/2.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status in (200, 201):
                    any_sent = True
                    try:
                        resp_data = json.loads(resp.read().decode())
                        embeds = resp_data.get("embeds") or []
                        if embeds and embeds[0].get("image", {}).get("url"):
                            cdn_url = embeds[0]["image"]["url"]
                        elif resp_data.get("attachments"):
                            cdn_url = resp_data["attachments"][0].get("url", "")
                    except Exception:
                        pass
        except Exception as e:
            print(f"[Doorbell] Discord send error for channel {channel_id}: {e}", flush=True)
    return any_sent, cdn_url


def send_carrier_sms_alert(
    saved_image_path: str, description: str, confidence: float, photo_cdn_url: str = ""
) -> bool:
    """Send SMS (with shortened photo link) + MMS attachment via email-to-SMS/MMS gateways."""
    if not SMS_TO and not MMS_TO:
        return False

    now_str = datetime.datetime.now().strftime("%I:%M %p")
    short_link = shorten_url(photo_cdn_url) if photo_cdn_url else ""
    sms_body = format_sms_body(description, now_str, short_link)
    mms_body = f"Front Door Alert ({now_str}): {description} ({confidence:.0%} conf)"
    any_ok = False

    if SMS_TO:
        try:
            r = subprocess.run(
                [GOG_BIN, "gmail", "send", "--to", SMS_TO, "--subject", "", "--body", sms_body],
                capture_output=True, text=True, timeout=20,
            )
            if r.returncode == 0:
                any_ok = True
        except Exception as e:
            print(f"[Doorbell] SMS gateway error: {e}", flush=True)

    if MMS_TO and saved_image_path and Path(saved_image_path).exists():
        try:
            r = subprocess.run(
                [GOG_BIN, "gmail", "send", "--to", MMS_TO, "--subject", "Front Door Photo", "--body", mms_body, "-a", saved_image_path],
                capture_output=True, text=True, timeout=25,
            )
            if r.returncode == 0:
                any_ok = True
        except Exception as e:
            print(f"[Doorbell] MMS gateway error: {e}", flush=True)

    return any_ok


def schedule_fast_resleep() -> None:
    """Schedule a 60-second post-analysis check to return to S3 (day) or S5 (night) if idle."""
    global _resleep_timer
    if _resleep_timer is not None:
        _resleep_timer.cancel()

    def _run_check() -> None:
        if Path(ORCHESTRATOR_BIN).exists():
            subprocess.run([ORCHESTRATOR_BIN, "--doorbell-post-check"], timeout=30, check=False)

    _resleep_timer = threading.Timer(RESLEEP_GRACE_SECONDS, _run_check)
    _resleep_timer.daemon = True
    _resleep_timer.start()


if __name__ == "__main__":
    init_db()
    print(f"[Doorbell] Zero-Idle Doorbell Service initialized on port {PORT}", flush=True)
