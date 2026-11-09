"""
Unit tests for `zero-idle-ai-sentry`:
Verifies Green FinOps kWh/cost calculations, 5-Tier compute routing, Dafang CGI endpoints,
walkway ROI cropping, unlit night luma gating, Gemma 4 JSON fence stripping, and SMS photo links.
Compatible with both `pytest` and standard library `python -m unittest`.
"""

import unittest
from PIL import Image
from sentry.doorbell_service import (
    CLASSIFY_CROP_BOX,
    MIN_LUMA_THRESHOLD,
    ROI_BOX,
    compute_luma,
    format_sms_body,
    parse_gemma_json_response,
)
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
    assert build_dafang_camera_url("192.168.1.50", "snapshot") == "https://192.168.1.50/cgi-bin/currentpic.cgi"
    assert build_dafang_camera_url("192.168.1.50", "ir_led_off") == "https://192.168.1.50/cgi-bin/action.cgi?cmd=ir_led_off"
    try:
        build_dafang_camera_url("bad_ip", "snapshot")
        assert False, "Expected ValueError for invalid IP"
    except ValueError:
        pass


def test_walkway_roi_excludes_public_street():
    # Street is at y < 400 on a 1280x720 frame; both ROI_BOX and CLASSIFY_CROP_BOX must exclude y < 400
    assert ROI_BOX[1] >= 400
    assert CLASSIFY_CROP_BOX[1] >= 400
    frame = Image.new("RGB", (1280, 720), color=(120, 120, 120))
    cropped = frame.crop(CLASSIFY_CROP_BOX)
    assert cropped.size == (CLASSIFY_CROP_BOX[2] - CLASSIFY_CROP_BOX[0], CLASSIFY_CROP_BOX[3] - CLASSIFY_CROP_BOX[1])


def test_unlit_night_luma_gate():
    dark_frame = Image.new("RGB", (320, 180), color=(18, 18, 18))
    lit_frame = Image.new("RGB", (320, 180), color=(95, 95, 95))
    assert compute_luma(dark_frame) < MIN_LUMA_THRESHOLD
    assert compute_luma(lit_frame) >= MIN_LUMA_THRESHOLD


def test_gemma4_json_fence_stripping():
    fenced = '```json\n{"person": true, "confidence": 0.95, "description": "Delivery driver with package"}\n```'
    parsed = parse_gemma_json_response(fenced)
    assert parsed["person"] is True
    assert abs(parsed["confidence"] - 0.95) < 1e-6
    assert "package" in parsed["description"]


def test_sms_body_fits_carrier_160_char_limit_with_photo_link():
    sms = format_sms_body(
        "Person walking up the front stone walkway toward the porch with a package",
        "12:44 PM",
        "https://is.gd/example",
    )
    assert len(sms) <= 160
    assert "Photo: https://is.gd/example" in sms


class TestZeroIdleSentry(unittest.TestCase):
    def test_all(self):
        test_green_finops_saves_over_95_percent_energy()
        test_tier0_motion_ping_stays_on_camera()
        test_tier2_text_summarization_uses_minimax_without_waking_gpu()
        test_tier1_edge_vision_handles_standard_frames_on_gemma4()
        test_tier3_titan_requires_low_confidence_and_hitl_approval()
        test_dafang_cgi_url_builder_and_validation()
        test_walkway_roi_excludes_public_street()
        test_unlit_night_luma_gate()
        test_gemma4_json_fence_stripping()
        test_sms_body_fits_carrier_160_char_limit_with_photo_link()


if __name__ == "__main__":
    unittest.main()
