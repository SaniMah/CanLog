"""Step 1 — evening test.

Load one CANdid capture, learn the normal rate of each CAN ID, flag timing
gaps bigger than 3x the median, and plot one ID's timeline with the gaps
marked.

Run:
    python run_step1.py                     # uses the bundled brakes capture
    python run_step1.py path\\to\\other.log  # any candump .log
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # save figures to file, no interactive window needed
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from src.load import load_candump  # noqa: E402
from src.profile import find_large_gaps, profile_ids  # noqa: E402

DEFAULT_LOG = Path("data/candid/2_brakes_CAN.log")
FIG_DIR = Path("reports/figures")
K = 3.0  # a gap > K * median_period is flagged as a candidate dropout


def plot_id_timeline(df, can_id, k=K, out_path=None):
    """Plot the inter-frame gaps for one CAN ID over the capture.

    Each point is the gap *before* a frame. The dashed red line is the dropout
    threshold (k x median); points above it (red) are the flagged gaps.
    """
    g = df[df["can_id"] == can_id].sort_values("timestamp")
    ts = g["timestamp"].to_numpy()
    rel = ts[1:] - ts[0]                 # frame time, seconds from capture start
    gaps_ms = (ts[1:] - ts[:-1]) * 1000  # gap before each frame, in ms
    med_ms = float(sorted(gaps_ms)[len(gaps_ms) // 2])
    thresh = k * med_ms
    flagged = gaps_ms > thresh

    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(rel[~flagged], gaps_ms[~flagged], ".", ms=4, color="#2a6f97",
            label="normal gap")
    ax.plot(rel[flagged], gaps_ms[flagged], "o", ms=7, color="#d00000",
            label=f"flagged gap (> {k:g}x median)")
    ax.axhline(med_ms, lw=1, color="#90a4ae", label=f"median = {med_ms:.1f} ms")
    ax.axhline(thresh, ls="--", lw=1.2, color="#d00000",
               label=f"threshold = {thresh:.1f} ms")
    ax.set_xlabel("time since capture start (s)")
    ax.set_ylabel("gap before frame (ms)")
    ax.set_title(f"CAN ID {can_id} — inter-frame timing  "
                 f"({int(flagged.sum())} gaps flagged)")
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()

    if out_path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, dpi=120)
    return out_path


def main(log_path=None):
    log_path = Path(log_path) if log_path else DEFAULT_LOG
    print(f"Loading {log_path} ...")
    df = load_candump(log_path)

    span = df["timestamp"].max() - df["timestamp"].min()
    print(f"  {len(df):,} frames | {df['can_id'].nunique()} unique IDs | "
          f"{span:.1f} s capture | {df.attrs['skipped_lines']} lines skipped")

    prof = profile_ids(df)
    print("\nBusiest CAN IDs (by frame count):")
    cols = ["can_id", "count", "freq_hz", "median_period", "period_iqr"]
    print(prof[cols].head(10).to_string(index=False))

    gaps = find_large_gaps(df, k=K)
    print(f"\nFlagged {len(gaps)} gaps > {K:g}x median period "
          f"across {gaps['can_id'].nunique()} IDs.")
    if not gaps.empty:
        print("\nBiggest gaps:")
        print(gaps.head(10).to_string(index=False))

    # Plot the ID with the single biggest gap (clearest dropout); fall back to
    # the busiest ID if nothing was flagged.
    plot_id = gaps.iloc[0]["can_id"] if not gaps.empty else prof.iloc[0]["can_id"]
    out = FIG_DIR / f"step1_{plot_id}_gaps.png"
    plot_id_timeline(df, plot_id, out_path=out)
    print(f"\nSaved timeline plot for ID {plot_id} -> {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
