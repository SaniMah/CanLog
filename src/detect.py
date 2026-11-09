"""Detection rules: find anomalies in CAN traffic and write them to `anomaly`.

Anomaly types (matching the `anomaly.anomaly_type` CHECK constraint):
    dropout       an ID went silent far longer than it ever normally does
    timing_drift  an ID's period changed a lot over the capture
    unknown_id    an ID appeared that isn't in the known/baseline set
    missing_id    a known/baseline ID never appeared

The dropout rule is the important one. A naive "gap > k * median" rule wrongly
flags *bursty* IDs — e.g. CANdid ID 3D2, which normally alternates ~33 ms and
~210 ms gaps, so 8% of its gaps are 6x the median yet perfectly normal. The fix:
also require the gap to beat the ID's own normal worst-case wait (99th-percentile
gap). We threshold on the MAX of the two terms, so:
    * steady IDs  -> the median term dominates (same as the simple rule);
    * bursty IDs  -> the p99 term lifts the bar above their routine big gaps.

All detect_* functions take a frames DataFrame with columns `timestamp` and
`can_id` and return a DataFrame with the ANOMALY_COLS below (no log_id — that is
added by write_anomalies).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

ANOMALY_COLS = ["can_id", "anomaly_type", "start_ts", "end_ts", "value", "detail"]


def detect_dropouts(
    df: pd.DataFrame,
    k_med: float = 3.0,
    k_p99: float = 1.5,
    min_count: int = 10,
    use_p99: bool = True,
) -> pd.DataFrame:
    """Flag inter-frame gaps that are abnormally long for their ID.

    threshold = k_med * median_period          (if use_p99 is False — naive rule)
    threshold = max(k_med * median, k_p99 * p99_period)   (if use_p99 is True)

    ``use_p99=False`` reproduces the original naive rule, used in Step 5 to show
    what the fix is worth.
    """
    rows: list[dict] = []
    for can_id, g in df.sort_values("timestamp").groupby("can_id"):
        ts = g["timestamp"].to_numpy()
        if len(ts) < min_count:
            continue
        gaps = np.diff(ts)
        med = float(np.median(gaps))
        if med <= 0:
            continue
        threshold = k_med * med
        p99 = float(np.percentile(gaps, 99))
        if use_p99:
            threshold = max(threshold, k_p99 * p99)

        for i, gap in enumerate(gaps):
            if gap > threshold:
                rows.append(
                    {
                        "can_id": can_id,
                        "anomaly_type": "dropout",
                        "start_ts": float(ts[i]),
                        "end_ts": float(ts[i + 1]),
                        "value": float(gap),
                        "detail": (
                            f"gap {gap * 1000:.0f} ms; median {med * 1000:.1f} ms, "
                            f"p99 {p99 * 1000:.0f} ms, threshold {threshold * 1000:.0f} ms"
                        ),
                    }
                )
    return pd.DataFrame(rows, columns=ANOMALY_COLS)


def detect_timing_drift(
    df: pd.DataFrame, min_count: int = 200, drift_frac: float = 0.25
) -> pd.DataFrame:
    """Flag IDs whose period drifts between the start and end of the capture.

    Compares the median gap over the first third vs the last third of an ID's
    frames; a change bigger than ``drift_frac`` (e.g. 25%) is flagged.
    """
    rows: list[dict] = []
    for can_id, g in df.sort_values("timestamp").groupby("can_id"):
        ts = g["timestamp"].to_numpy()
        if len(ts) < min_count:
            continue
        gaps = np.diff(ts)
        third = len(gaps) // 3
        early = float(np.median(gaps[:third]))
        late = float(np.median(gaps[-third:]))
        if early <= 0:
            continue
        change = (late - early) / early
        if abs(change) > drift_frac:
            rows.append(
                {
                    "can_id": can_id,
                    "anomaly_type": "timing_drift",
                    "start_ts": float(ts[0]),
                    "end_ts": float(ts[-1]),
                    "value": float(change),
                    "detail": (
                        f"median period {early * 1000:.1f} ms -> {late * 1000:.1f} ms "
                        f"({change * 100:+.0f}%)"
                    ),
                }
            )
    return pd.DataFrame(rows, columns=ANOMALY_COLS)


def detect_unknown_ids(df: pd.DataFrame, known_ids) -> pd.DataFrame:
    """Flag IDs present in the capture but not in the known/baseline set."""
    known = set(known_ids)
    rows: list[dict] = []
    for can_id, g in df.groupby("can_id"):
        if can_id in known:
            continue
        ts = g["timestamp"].to_numpy()
        rows.append(
            {
                "can_id": can_id,
                "anomaly_type": "unknown_id",
                "start_ts": float(ts.min()),
                "end_ts": float(ts.max()),
                "value": float(len(ts)),
                "detail": f"{len(ts)} frames from an ID not in the baseline",
            }
        )
    return pd.DataFrame(rows, columns=ANOMALY_COLS)


def detect_missing_ids(df: pd.DataFrame, expected_ids) -> pd.DataFrame:
    """Flag baseline IDs that never appear in the capture."""
    present = set(df["can_id"].unique())
    rows: list[dict] = []
    for can_id in expected_ids:
        if can_id not in present:
            rows.append(
                {
                    "can_id": can_id,
                    "anomaly_type": "missing_id",
                    "start_ts": None,
                    "end_ts": None,
                    "value": None,
                    "detail": "expected (baseline) ID never seen in this capture",
                }
            )
    return pd.DataFrame(rows, columns=ANOMALY_COLS)


# ---------------------------------------------------------------------------
# Writing results to the database
# ---------------------------------------------------------------------------

def clear_anomalies(engine: Engine, log_id: int) -> None:
    """Remove any existing anomalies for a log, so detection can be re-run."""
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM anomaly WHERE log_id = :log_id"),
                     {"log_id": log_id})


def write_anomalies(engine: Engine, log_id: int, anomalies: pd.DataFrame) -> int:
    """Insert detected anomalies into the `anomaly` table."""
    if anomalies.empty:
        return 0
    out = anomalies.copy()
    out.insert(0, "log_id", log_id)
    out.to_sql("anomaly", engine, if_exists="append", index=False)
    return len(out)
