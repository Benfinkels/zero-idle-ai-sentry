"""
Zero-Idle Ephemeral AI Sentry Orchestrator (`sentry/orchestrator.py`)

Implements the 5-Tier Ephemeral Compute Ladder:
- Tier 0: 2.5W Linux Camera Tripwire (Motion -> Wake-on-LAN)
- Tier 1: 8GB Edge GPU Multimodal Worker (`Gemma 4` Vision -> Tool Call)
- Tier 2: Cloud Text Workhorse (`MiniMax-M2.7` for log digests without waking 450W PSU)
- Tier 3: 24GB Local Titan (`Nemotron 3.5 Bolt` on RTX 4090 behind HITL gate)
- Green FinOps Calculator: Quantifies annual kWh & dollar savings vs. 24/7 idle servers.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class FinOpsReport:
    always_on_kwh_per_year: float
    ephemeral_kwh_per_year: float
    kwh_saved_per_year: float
    dollars_saved_per_year: float
    efficiency_gain_pct: float


def calculate_zero_idle_finops(
    sentry_watts: float = 2.5,
    edge_node_watts: float = 140.0,
    titan_node_watts: float = 450.0,
    daily_active_minutes_edge: float = 25.0,
    daily_active_minutes_titan: float = 5.0,
    s3_sleep_watts: float = 3.0,
    electricity_rate_per_kwh: float = 0.15,
) -> FinOpsReport:
    """
    Compare 24/7 always-on homelab power draw against the Zero-Idle Ephemeral Wake-on-LAN architecture.
    """
    hours_per_year = 365.0 * 24.0
    always_on_watts = sentry_watts + edge_node_watts + titan_node_watts
    always_on_kwh = (always_on_watts * hours_per_year) / 1000.0

    edge_awake_hours = (daily_active_minutes_edge / 60.0) * 365.0
    titan_awake_hours = (daily_active_minutes_titan / 60.0) * 365.0
    edge_sleep_hours = hours_per_year - edge_awake_hours
    titan_sleep_hours = hours_per_year - titan_awake_hours

    ephemeral_wh = (
        (sentry_watts * hours_per_year)
        + (edge_node_watts * edge_awake_hours)
        + (s3_sleep_watts * edge_sleep_hours)
        + (titan_node_watts * titan_awake_hours)
        + (s3_sleep_watts * titan_sleep_hours)
    )
    ephemeral_kwh = ephemeral_wh / 1000.0
    saved_kwh = max(0.0, always_on_kwh - ephemeral_kwh)
    saved_dollars = saved_kwh * electricity_rate_per_kwh
    gain_pct = (saved_kwh / always_on_kwh) * 100.0 if always_on_kwh > 0 else 0.0

    return FinOpsReport(
        always_on_kwh_per_year=round(always_on_kwh, 1),
        ephemeral_kwh_per_year=round(ephemeral_kwh, 1),
        kwh_saved_per_year=round(saved_kwh, 1),
        dollars_saved_per_year=round(saved_dollars, 2),
        efficiency_gain_pct=round(gain_pct, 2),
    )


def select_compute_tier(
    event_type: str,
    requires_vision: bool,
    confidence_score: float = 0.95,
    hitl_approved: bool = False,
) -> dict[str, Any]:
    """
    Deterministic routing policy across the 5-Tier Intelligence Hierarchy.
    """
    ev = event_type.strip().lower()
    if ev == "motion_ping" and not requires_vision:
        return {
            "tier": 0,
            "node": "wyze-dafang-sentry",
            "model": "none",
            "action": "toggle_floodlight_and_send_wol",
            "estimated_watts": 2.5,
        }
    if not requires_vision:
        return {
            "tier": 2,
            "node": "sheldon-litellm",
            "model": "minimax-m2.7",
            "action": "cloud_text_digest",
            "estimated_watts": 15.0,
        }
    # Vision task: default to Tier 1 (Sheldon RTX 2080 Gemma 4) unless confidence is low and HITL is approved
    if confidence_score >= 0.75 or not hitl_approved:
        return {
            "tier": 1,
            "node": "sheldon-rtx2080",
            "model": "gemma4:e2b-it-q4_K_M",
            "action": "edge_vision_tool_dispatch",
            "estimated_watts": 140.0,
        }
    return {
        "tier": 3,
        "node": "hyperion-rtx4090",
        "model": "nemotron-3.5-bolt:latest",
        "action": "deep_multimodal_security_audit",
        "estimated_watts": 450.0,
    }


def build_dafang_camera_url(camera_ip: str, action: str) -> str:
    """Build verified Dafang-Hacks CGI endpoint URLs for PTZ motor & night-vision glare control."""
    if not re.fullmatch(r"[0-9]{1,3}(\.[0-9]{1,3}){3}", camera_ip):
        raise ValueError(f"Invalid IPv4 address: {camera_ip!r}")
    routes = {
        "snapshot": f"https://{camera_ip}/cgi-bin/currentpic.cgi",
        "pan_left": f"https://{camera_ip}/cgi-bin/action.cgi?cmd=motor_left",
        "pan_right": f"https://{camera_ip}/cgi-bin/action.cgi?cmd=motor_right",
        "ir_led_off": f"https://{camera_ip}/cgi-bin/action.cgi?cmd=ir_led_off",
        "ir_led_on": f"https://{camera_ip}/cgi-bin/action.cgi?cmd=ir_led_on",
    }
    if action not in routes:
        raise ValueError(f"Unsupported camera action: {action!r}")
    return routes[action]


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m sentry.orchestrator",
        description="Calculate annual kWh and electricity savings from waking your GPU server on demand.",
    )
    parser.add_argument("--camera-watts", type=float, default=2.5, help="Always-on edge camera draw in watts (default: 2.5)")
    parser.add_argument("--server-watts", type=float, default=140.0, help="GPU server idle/active draw when awake in watts (default: 140)")
    parser.add_argument("--workstation-watts", type=float, default=0.0, help="Optional secondary GPU workstation watts if left on 24/7 (default: 0)")
    parser.add_argument("--active-minutes", type=float, default=25.0, help="Average awake minutes per day for the GPU server (default: 25)")
    parser.add_argument("--sleep-watts", type=float, default=2.5, help="S3 sleep power draw in watts (default: 2.5)")
    parser.add_argument("--rate", type=float, default=0.18, help="Electricity rate in $/kWh (default: 0.18)")
    args = parser.parse_args(argv)

    rep = calculate_zero_idle_finops(
        sentry_watts=args.camera_watts,
        edge_node_watts=args.server_watts,
        titan_node_watts=args.workstation_watts,
        daily_active_minutes_edge=args.active_minutes,
        daily_active_minutes_titan=0.0,
        s3_sleep_watts=args.sleep_watts,
        electricity_rate_per_kwh=args.rate,
    )
    print(f"Always-on (24/7):   {rep.always_on_kwh_per_year:,.1f} kWh/yr  (${rep.always_on_kwh_per_year * args.rate:,.2f}/yr)")
    print(f"Zero-idle (S3/WoL): {rep.ephemeral_kwh_per_year:,.1f} kWh/yr  (${rep.ephemeral_kwh_per_year * args.rate:,.2f}/yr)")
    print(f"Saved:              {rep.kwh_saved_per_year:,.1f} kWh/yr  (${rep.dollars_saved_per_year:,.2f}/yr, -{rep.efficiency_gain_pct:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
