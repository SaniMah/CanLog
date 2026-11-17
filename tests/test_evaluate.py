"""Tests for the precision/recall scorer (src/evaluate.score)."""
import pandas as pd

from src.evaluate import score


def test_perfect_match():
    events = [{"can_id": "100", "start": 1.0, "end": 1.5}]
    detected = pd.DataFrame(
        {"can_id": ["100"], "start_ts": [0.95], "end_ts": [1.6]}
    )
    r = score(detected, events)
    assert r["tp"] == 1 and r["fp"] == 0 and r["fn"] == 0
    assert r["precision"] == 1.0 and r["recall"] == 1.0


def test_false_positive_and_false_negative():
    events = [
        {"can_id": "100", "start": 1.0, "end": 1.5},   # will be found
        {"can_id": "200", "start": 3.0, "end": 3.2},   # will be missed
    ]
    detected = pd.DataFrame(
        {"can_id": ["100", "999"],       # 999 matches no event -> false positive
         "start_ts": [0.95, 8.0],
         "end_ts": [1.6, 8.1]}
    )
    r = score(detected, events)
    assert r["tp"] == 1 and r["fn"] == 1 and r["fp"] == 1
    assert r["precision"] == 0.5
    assert r["recall"] == 0.5


def test_same_id_wrong_time_is_not_a_match():
    events = [{"can_id": "100", "start": 1.0, "end": 1.5}]
    detected = pd.DataFrame(
        {"can_id": ["100"], "start_ts": [5.0], "end_ts": [5.2]}  # no overlap
    )
    r = score(detected, events)
    assert r["tp"] == 0 and r["fn"] == 1 and r["fp"] == 1
    assert r["recall"] == 0.0
