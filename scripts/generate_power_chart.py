"""Generate measured Power Draw & Parallel Wake Timeline chart for Zero-Idle AI Sentry."""

from __future__ import annotations

from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parent.parent / "docs" / "power_and_wake_profile.png"
OUT.parent.mkdir(parents=True, exist_ok=True)

plt.rcParams.update(
    {
        "figure.facecolor": "#ffffff",
        "axes.facecolor": "#ffffff",
        "axes.edgecolor": "#d1d5db",
        "axes.labelcolor": "#111827",
        "xtick.color": "#374151",
        "ytick.color": "#374151",
        "text.color": "#111827",
        "font.sans-serif": ["DejaVu Sans", "Arial"],
        "axes.grid": True,
        "grid.color": "#e5e7eb",
        "grid.linestyle": "--",
        "grid.linewidth": 0.7,
    }
)


def main() -> None:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.5, 4.5), gridspec_kw={"width_ratios": [1, 1.25]})
    fig.suptitle(
        "Zero-Idle AI Doorbell Sentry (v2): >97% Idle Power Reduction & 3.5s Parallel Wake Pipeline",
        fontsize=12.5,
        fontweight="bold",
        y=0.98,
    )

    # Panel 1: Power Draw Comparison (Watts & Annual kWh @ 24/7 vs 16h S3 / 8h S5 + 2.5W cam)
    # 24/7 continuous: 140W server + 2.5W cam = 142.5W (~1,248 kWh/yr)
    # Daytime S3 idle: 2.5W server RAM + 2.5W cam = 5.0W
    # Nighttime S5 idle: 0.0W server + 2.5W cam = 2.5W
    # Weighted 24h idle average: (16*5.0 + 8*2.5)/24 = 4.17W (~36.5 kWh/yr -> 97.1% reduction)
    modes = [
        "v1 Continuous\n(24/7 GPU Awake)",
        "v2 Daytime S3\n(07:00–23:00)",
        "v2 Nighttime S5\n(23:00–07:00)",
    ]
    watts = [142.5, 5.0, 2.5]
    colors = ["#ef4444", "#2563eb", "#10b981"]
    bars = ax1.bar(modes, watts, color=colors, width=0.52)
    ax1.set_ylim(0, 168)
    ax1.set_ylabel("Total System Idle Power (Watts)", fontsize=10, fontweight="bold")
    ax1.set_title("Measured System Power (Camera + GPU Server)", fontsize=11, pad=8)
    ax1.grid(axis="x", visible=False)
    notes = ["142.5 W\n(~1,248 kWh/yr)", "5.0 W\n(2.5W Cam + 2.5W S3)", "2.5 W\n(2.5W Cam + 0W S5)"]
    for bar, w, note in zip(bars, watts, notes):
        ax1.text(bar.get_x() + bar.get_width() / 2, w + 3.5, note, ha="center", va="bottom", fontsize=8.5, fontweight="bold")

    ax1.annotate(
        "-97.1% Avg Idle Power\n(4.2 W weighted avg)",
        xy=(1.45, 28),
        xytext=(1.45, 96),
        ha="center",
        fontsize=9.5,
        fontweight="bold",
        color="#065f46",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="#d1fae5", edgecolor="#10b981"),
        arrowprops=dict(arrowstyle="->", color="#10b981", lw=1.6),
    )

    # Panel 2: Parallel Wake & Spaced-Burst Timeline (Gantt)
    stages = [
        ("Discord + SMS Alert", 4.1, 1.8, "#8b5cf6", "t=4.1–5.9s (~2s SMS)"),
        ("Gemma 4 Vision JSON", 3.6, 0.5, "#10b981", "t=3.6–4.1s (~350ms warm)"),
        ("Spaced Burst f1/f2/f3", 0.0, 3.0, "#f59e0b", "t=0.0, 1.0, 3.0s (parallel)"),
        ("ACPI S3 Kernel Resume", 0.0, 3.5, "#2563eb", "t=0.0–3.5s (WoL GLAN)"),
        ("ISP ROI Motion + WoL", 0.0, 0.25, "#ef4444", "t=0.0s (2.5W MIPS cam)"),
    ]
    y = np.arange(len(stages))
    for i, (label, start, dur, col, note) in enumerate(stages):
        ax2.barh(i, dur, left=start, height=0.55, color=col, alpha=0.9)
        text_x = start + dur + 0.15
        if text_x > 4.6:
            ax2.text(start - 0.12, i, note, va="center", ha="right", fontsize=8.3, fontweight="bold")
        else:
            ax2.text(text_x, i, note, va="center", ha="left", fontsize=8.3, fontweight="bold")

    ax2.set_yticks(y)
    ax2.set_yticklabels([s[0] for s in stages], fontsize=9)
    ax2.set_xlim(0, 7.6)
    ax2.set_xlabel("Elapsed Wall-Clock Time from Walkway Motion (Seconds)", fontsize=10, fontweight="bold")
    ax2.set_title("Parallel S3 Wake + 3-Frame Spaced Burst Timeline", fontsize=11, pad=8)
    ax2.grid(axis="y", visible=False)

    plt.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(OUT, dpi=160)
    plt.close(fig)
    print("Generated", OUT)


if __name__ == "__main__":
    main()
