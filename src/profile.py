"""Learn what 'normal' looks like for each CAN ID, and flag timing gaps.

A healthy CAN ID is usually sent at a steady rate (e.g. every 10 ms). We learn
that rate per ID, then flag any gap between consecutive frames that is much
bigger than usual — a candidate *dropout*.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def profile_ids(df: pd.DataFrame) -> pd.DataFrame:
    """Summarise the timing of each CAN ID.

    Returns one row per CAN ID with:
        can_id, count, first_ts, last_ts, duration_s, freq_hz,
        mean_period, median_period, period_iqr, min_period, max_period

    ``median_period`` is the typical seconds between frames (robust to the
    occasional big gap). ``period_iqr`` is how spread-out the timing is.
    """
    out: list[dict] = []
    for can_id, g in df.sort_values("timestamp").groupby("can_id"):
        ts = g["timestamp"].to_numpy()
        gaps = np.diff(ts)  # seconds between consecutive frames of this ID
        duration = float(ts[-1] - ts[0]) if len(ts) > 1 else 0.0

        row = {
            "can_id": can_id,
            "count": int(len(ts)),
            "first_ts": float(ts[0]),
            "last_ts": float(ts[-1]),
            "duration_s": duration,
            "freq_hz": (len(ts) / duration) if duration > 0 else np.nan,
        }
        if len(gaps):
            row.update(
                mean_period=float(gaps.mean()),
                median_period=float(np.median(gaps)),
                period_iqr=float(np.subtract(*np.percentile(gaps, [75, 25]))),
                min_period=float(gaps.min()),
                max_period=float(gaps.max()),
            )
        else:
            row.update(
                mean_period=np.nan, median_period=np.nan, period_iqr=np.nan,
                min_period=np.nan, max_period=np.nan,
            )
        out.append(row)

    return (
        pd.DataFrame(out)
        .sort_values("count", ascending=False)
        .reset_index(drop=True)
    )


def find_large_gaps(df: pd.DataFrame, k: float = 3.0, min_count: int = 10) -> pd.DataFrame:
    """Flag inter-frame gaps larger than ``k * median_period`` for that ID.

    Parameters
    ----------
    k : float
        Threshold multiplier. A gap counts as a dropout if it is more than
        ``k`` times that ID's median period. Start at 3; tuned in Step 5.
    min_count : int
        Ignore IDs seen fewer than this many times — too few frames to have a
        meaningful 'normal' rate.

    Returns one row per flagged gap:
        can_id, gap_start_ts, gap_end_ts, gap_s, median_period, ratio
    where ``ratio = gap_s / median_period`` (how many times normal).
    """
    hits: list[dict] = []
    for can_id, g in df.sort_values("timestamp").groupby("can_id"):
        ts = g["timestamp"].to_numpy()
        if len(ts) < min_count:
            continue
        gaps = np.diff(ts)
        med = float(np.median(gaps))
        if med <= 0:
            continue
        threshold = k * med
        for i, gap in enumerate(gaps):
            if gap > threshold:
                hits.append(
                    {
                        "can_id": can_id,
                        "gap_start_ts": float(ts[i]),
                        "gap_end_ts": float(ts[i + 1]),
                        "gap_s": float(gap),
                        "median_period": med,
                        "ratio": float(gap / med),
                    }
                )

    cols = ["can_id", "gap_start_ts", "gap_end_ts", "gap_s", "median_period", "ratio"]
    return (
        pd.DataFrame(hits, columns=cols)
        .sort_values("gap_s", ascending=False)
        .reset_index(drop=True)
    )
