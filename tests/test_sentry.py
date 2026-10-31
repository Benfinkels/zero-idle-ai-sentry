"""
Unit tests for `zero-idle-ai-sentry`:
Verifies Green FinOps kWh/cost calculations, 5-Tier compute routing, and Dafang CGI endpoints.
"""

import pytest
from sentry.orchestrator import (
    build_dafang_camera_url,
    calculate_zero_idle_finops,
    select_compute_tier,
)


def test_green_finops_saves_over_95_percent_energy():
    report = calculate_zero_idle_finops(
        sentry_watts=2.5,
        edge_node_watts=140.0,
        titan_node_watts=450.0,
        daily_active_minutes_edge=25.0,
        daily_active_minutes_titan=5.0,
        s3_sleep_watts=3.0,
        electricity_rate_per_kwh=0.15,
    )
    assert report.always_on_kwh_per_year > 5000.0
    assert report.ephemeral_kwh_per_year < 150.0
    assert report.kwh_saved_per_year > 5000.0
    assert report.dollars_saved_per_year > 750.0
    assert report.efficiency_gain_pct > 97.0


def test_tier0_motion_ping_stays_on_camera():
    route = select_compute_tier("motion_ping", requires_vision=False)
    assert route["tier"] == 0
    assert route["estimated_watts"] == 2.5


def test_tier2_text_summarization_uses_minimax_without_waking_gpu():
    route = select_compute_tier("daily_digest", requires_vision=False)
    assert route["tier"] == 2
    assert route["model"] == "minimax-m2.7"


def test_tier1_edge_vision_handles_standard_frames_on_gemma4():
    route = select_compute_tier("driveway_motion", requires_vision=True, confidence_score=0.92, hitl_approved=False)
    assert route["tier"] == 1
    assert route["model"] == "gemma4:e2b-it-q4_K_M"


def test_tier3_titan_requires_low_confidence_and_hitl_approval():
    blocked = select_compute_tier("driveway_motion", requires_vision=True, confidence_score=0.40, hitl_approved=False)
    assert blocked["tier"] == 1  # Stays on Tier 1 without HITL approval

    approved = select_compute_tier("driveway_motion", requires_vision=True, confidence_score=0.40, hitl_approved=True)
    assert approved["tier"] == 3
    assert approved["model"] == "nemotron-3.5-bolt:latest"


def test_dafang_cgi_url_builder_and_validation():
    assert build_dafang_camera_url("192.168.86.42", "snapshot") == "https://192.168.86.42/cgi-bin/currentpic.cgi"
    assert build_dafang_camera_url("192.168.86.42", "ir_led_off") == "https://192.168.86.42/cgi-bin/action.cgi?cmd=ir_led_off"
    with pytest.raises(ValueError):
        build_dafang_camera_url("bad_ip", "snapshot")
