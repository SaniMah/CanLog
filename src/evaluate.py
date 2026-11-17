"""Evaluation: inject known dropouts into a clean capture, then measure how well
the detector finds them (precision / recall).

Why inject? The brakes capture is clean - it has no real dropouts to score
against. Known windows of frames are removed to create dropouts whose exact
location is known (ground truth), then the detector runs and the results
are compared.

Matching is by interval overlap: a detected gap counts as a true positive if it
overlaps an injected window for the same CAN ID.
    precision = detections that hit a real injected dropout / all detections
    recall    = injected dropouts that were detected / all injected dropouts
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .profile import profile_ids


def eligible_ids(df, min_freq=20.0, min_count=200, max_iqr_ratio=0.5):
    """Pick steady, periodic IDs that make clean injection targets.

    High rate (so a short removed window is clearly a gap), enough frames, and
    low timing jitter (IQR small vs median) so they aren't bursty.
    """
    prof = profile_ids(df)
    ok = (
        (prof["freq_hz"] >= min_freq)
        & (prof["count"] >= min_count)  # profile_ids names the frame count "count"
        & (prof["period_iqr"] <= max_iqr_ratio * prof["median_period"])
    )
    return prof.loc[ok, "can_id"].tolist()


def make_dropout_events(df, n=24, durations=(0.2, 0.3, 0.5, 0.8, 1.2), seed=42, guard=3.0):
    """Create ``n`` random dropout events on eligible IDs.

    Each event = {can_id, start, end, duration}. Guard keeps events away from
    the very start/end of the capture.
    """
    rng = np.random.default_rng(seed)
    ids = eligible_ids(df)
    if not ids:
        raise RuntimeError("no eligible IDs to inject into")
    t0, t1 = float(df["timestamp"].min()), float(df["timestamp"].max())

    events = []
    for _ in range(n):
        cid = ids[int(rng.integers(len(ids)))]
        dur = float(durations[int(rng.integers(len(durations)))])
        start = float(rng.uniform(t0 + guard, t1 - guard - dur))
        events.append({"can_id": cid, "start": start, "end": start + dur, "duration": dur})
    return events


def inject_dropouts(df, events) -> pd.DataFrame:
    """Return a copy of df with each event's frames removed (the dropout)."""
    ts = df["timestamp"].to_numpy()
    cid = df["can_id"].to_numpy()
    remove = np.zeros(len(df), dtype=bool)
    for e in events:
        remove |= (cid == e["can_id"]) & (ts >= e["start"]) & (ts < e["end"])
    return df.loc[~remove].reset_index(drop=True)


def _overlap(a0, a1, b0, b1) -> bool:
    return a0 <= b1 and b0 <= a1


def score(detected: pd.DataFrame, events) -> dict:
    """Compare detected dropout gaps against injected events (by overlap)."""
    dets = list(detected[["can_id", "start_ts", "end_ts"]].itertuples(index=False))
    truth_hit = [False] * len(events)
    det_hit = [False] * len(dets)

    for di, d in enumerate(dets):
        for ti, e in enumerate(events):
            if d.can_id == e["can_id"] and _overlap(d.start_ts, d.end_ts, e["start"], e["end"]):
                truth_hit[ti] = True
                det_hit[di] = True

    tp = sum(truth_hit)                         # injected dropouts found
    fn = len(events) - tp                       # injected dropouts missed
    fp = sum(1 for h in det_hit if not h)       # detections that hit nothing real
    n_det = len(dets)
    precision = (sum(det_hit) / n_det) if n_det else float("nan")
    recall = (tp / len(events)) if events else float("nan")
    f1 = (2 * precision * recall / (precision + recall)
          if precision and recall and not np.isnan(precision) else 0.0)
    return {
        "n_det": n_det, "tp": tp, "fp": fp, "fn": fn,
        "precision": precision, "recall": recall, "f1": f1,
    }
