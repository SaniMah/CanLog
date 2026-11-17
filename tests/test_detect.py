"""Tests for timing profiling and anomaly detection.

Covers the three cases from the brief (no gaps / one known gap / empty log)
plus the bursty-ID dropout fix and timing drift. All on synthetic data - no
database needed.
"""
import numpy as np
import pandas as pd

from src.detect import detect_dropouts, detect_timing_drift
from src.profile import find_large_gaps, profile_ids


def steady(can_id, period, n, start=0.0):
    """Frames for one ID at a fixed period."""
    ts = start + np.arange(n) * period
    return pd.DataFrame({"timestamp": ts, "can_id": can_id})


# --- the three brief cases ------------------------------------------------- #

def test_no_gaps():
    df = steady("100", 0.01, 100)          # steady 100 Hz
    assert find_large_gaps(df, k=3).empty


def test_one_known_gap():
    before = steady("100", 0.01, 50)
    after = steady("100", 0.01, 50, start=0.01 * 50 + 0.2)  # a 200 ms gap
    df = pd.concat([before, after], ignore_index=True)

    res = find_large_gaps(df, k=3)
    assert len(res) == 1
    assert res.iloc[0]["can_id"] == "100"
    assert res.iloc[0]["gap_s"] > 0.1
    assert res.iloc[0]["ratio"] > 3


def test_empty_log():
    df = pd.DataFrame({"timestamp": [], "can_id": []})
    assert profile_ids(df).empty
    assert find_large_gaps(df).empty
    assert detect_dropouts(df).empty


# --- the dropout fix ------------------------------------------------------- #

def test_bursty_id_not_false_flagged():
    """A bursty ID (9 fast gaps then 1 big gap, repeating) floods the naive
    rule but is NOT flagged by the fixed (p99) rule."""
    cycle = [0.01] * 9 + [0.2]
    gaps = np.tile(cycle, 30)
    ts = np.concatenate([[0.0], np.cumsum(gaps)])
    df = pd.DataFrame({"timestamp": ts, "can_id": "3D2"})

    naive = detect_dropouts(df, k_med=3, use_p99=False)
    fixed = detect_dropouts(df, k_med=3, k_p99=1.5, use_p99=True)

    assert len(naive) > 0     # naive drowns in false positives
    assert len(fixed) == 0    # fix removes them


def test_real_stall_is_detected():
    before = steady("100", 0.01, 100)
    after = steady("100", 0.01, 100, start=0.01 * 100 + 1.0)  # 1 s stall
    df = pd.concat([before, after], ignore_index=True)

    fixed = detect_dropouts(df, k_med=3, k_p99=1.5, use_p99=True)
    assert len(fixed) == 1
    assert fixed.iloc[0]["anomaly_type"] == "dropout"
    assert fixed.iloc[0]["value"] > 0.9


def test_rare_id_ignored():
    df = steady("100", 0.01, 5)   # fewer than min_count frames
    assert find_large_gaps(df).empty
    assert detect_dropouts(df).empty


# --- timing drift ---------------------------------------------------------- #

def test_timing_drift_detected():
    first = np.arange(300) * 0.01                 # 10 ms period
    second = first[-1] + 0.025 * np.arange(1, 301)  # 25 ms period
    ts = np.concatenate([first, second])
    df = pd.DataFrame({"timestamp": ts, "can_id": "200"})

    res = detect_timing_drift(df, min_count=200, drift_frac=0.25)
    assert len(res) == 1
    assert res.iloc[0]["anomaly_type"] == "timing_drift"
