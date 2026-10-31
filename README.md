# 🛡️ Zero-Idle AI Sentry: 2.5W Edge Camera $\rightarrow$ Wake-on-LAN $\rightarrow$ Multimodal Vision Pipeline

[![CI](https://github.com/Benfinkels/zero-idle-ai-sentry/actions/workflows/ci.yml/badge.svg)](https://github.com/Benfinkels/zero-idle-ai-sentry/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Standby Power](https://img.shields.io/badge/Standby_Draw-2.5_Watts-2ea44f)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

An **ephemeral, zero-idle-power physical AI security & homelab orchestration pipeline**. Instead of burning **~590W 24/7** (~5,190 kWh/year) keeping multi-GPU servers awake waiting for camera events, a liberated **2.5W Ingenic T20 Linux camera (`Dafang-Hacks`)** acts as an always-on physical sentry—waking sleeping GPU workstations via **Wake-on-LAN** in 2–4 seconds only when real physical events require multimodal intelligence.

---

## ⚡ Ephemeral Architecture & Signal Flow

```mermaid
flowchart TD
    Cam["📷 Tier 0: 2.5W Linux Camera Sentry<br/>(Ingenic T20 MIPS / RTSP / Dafang CGI)"]
    WoL["⚡ UDP Wake-on-LAN Magic Packet<br/>(firmware_hooks/wake_node.sh)"]
    Edge["🟢 Tier 1: 8GB Edge GPU Node (Sheldon)<br/>Gemma 4 Vision + Tool Calling (~2s)"]
    Workhorse["🔵 Tier 2: Cloud Text Workhorse<br/>MiniMax-M2.7 (Log Digests without GPU Wake)"]
    HITL🔒 Low Confidence?<br/>Discord HITL Gate
    Titan["🟣 Tier 3: 24GB Local Titan (Hyperion)<br/>RTX 4090 Nemotron 3.5 Bolt 74B MoE"]
    Sleep["💤 Return Nodes to ACPI S3 Sleep<br/>(Standby returns to ~2.5W)"]

    Cam -->|"Motion Tripwire"| WoL
    WoL --> Edge
    Edge -->|"Text / Digest Only"| Workhorse
    Edge -->|"95% Standard Frames"| Sleep
    Edge -->|"Ambiguous Frame"| HITL
    HITL -->|"Approved"| Titan
    Titan --> Sleep
```

---



---

## 📂 Repository Structure

* **[`firmware_hooks/wake_node.sh`](firmware_hooks/wake_node.sh):** Drop-in Dafang-Hacks `/system/sdcard/config/userscripts/motiondetection/` script for Ingenic T20 cameras to broadcast a Wake-on-LAN packet on motion detection.
* **[`sentry/orchestrator.py`](sentry/orchestrator.py):**
  * `calculate_zero_idle_finops()`: Computes annual kWh and dollar savings of S3 sleep + Wake-on-LAN vs. 24/7 idle GPU servers (**>97% energy reduction / ~$750+ saved per year**).
  * `select_compute_tier()`: Routes events across Tier 0 (2.5W Camera), Tier 1 (`Gemma 4` 8GB Edge Vision), Tier 2 (`MiniMax-M2.7` Cloud Text Workhorse), and Tier 3 (`Nemotron 3.5 Bolt` 24GB RTX 4090 behind HITL).
  * `build_dafang_camera_url()`: Validated CGI control builder for snapshot capture, PTZ motor panning, and through-window IR glare suppression (`ir_led_off`).
* **[`tests/test_sentry.py`](tests/test_sentry.py):** Deterministic `pytest` suite covering FinOps calculations, tier routing, and camera CGI safety.

---

## 🧪 Quickstart

```bash
pip install -r requirements.txt
pytest -v
```
