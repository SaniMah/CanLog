"""Create a faulty demo capture in the database, so the dashboard has anomalies
to show.

Takes the clean capture (log 1), injects known dropouts, and stores the result
as a NEW log_file (with its frames, profiles, and detected anomalies). This is
clearly labelled as injected/demo data — it is not real fault data.

Run:
    python run_inject_demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parent))
from src.db import get_engine  # noqa: E402
from src.detect import (  # noqa: E402
    clear_anomalies,
    detect_dropouts,
    detect_timing_drift,
    write_anomalies,
)
from src.evaluate import inject_dropouts, make_dropout_events  # noqa: E402
from src.load import copy_frames, insert_log_file, read_frames, store_profiles  # noqa: E402
from src.profile import profile_ids  # noqa: E402

DEMO_FILENAME = "2_brakes_INJECTED_demo.log"
SOURCE_LOG_ID = 1


def main():
    engine = get_engine()

    # if the demo log already exists, remove it first (idempotent re-runs)
    with engine.begin() as conn:
        old = conn.execute(
            text("SELECT log_id FROM log_file WHERE filename = :f"),
            {"f": DEMO_FILENAME},
        ).scalar()
        if old is not None:
            conn.execute(text("DELETE FROM log_file WHERE log_id = :l"), {"l": old})
            print(f"Removed existing demo log_id={old} (cascade cleared its data).")

    clean = read_frames(engine, SOURCE_LOG_ID)
    events = make_dropout_events(clean, n=24)
    dirty = inject_dropouts(clean, events)
    print(f"Injected {len(events)} dropouts; {len(clean) - len(dirty)} frames removed.")

    meta = {
        "source_dataset": "CANdid (brakes) + injected dropouts",
        "vehicle_make": "Mazda",
        "vehicle_model": "CX-3 Maxx Sport",
        "capture_type": "Brakes (injected faults - demo)",
        "description": f"Clean brakes capture with {len(events)} synthetic dropouts injected",
        "duration_s": float(dirty["timestamp"].max() - dirty["timestamp"].min()),
    }
    log_id = insert_log_file(engine, DEMO_FILENAME, meta, frame_count=len(dirty))
    copy_frames(engine, log_id, dirty)
    store_profiles(engine, log_id, profile_ids(dirty))
    print(f"Stored demo capture as log_id={log_id} ({len(dirty):,} frames).")

    # detect on the dirty capture and store the anomalies
    import pandas as pd
    anomalies = pd.concat(
        [detect_dropouts(dirty, k_med=3.0, k_p99=1.5), detect_timing_drift(dirty)],
        ignore_index=True,
    )
    clear_anomalies(engine, log_id)
    n = write_anomalies(engine, log_id, anomalies)
    print(f"Detected and stored {n} anomalies for log_id={log_id}.")

    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT anomaly_type, count(*) n FROM anomaly WHERE log_id=:l "
            "GROUP BY anomaly_type"), {"l": log_id}).all()
    print("  " + ", ".join(f"{r.anomaly_type}={r.n}" for r in rows))
    print(f"\nDashboard can now show log_id={log_id}.")


if __name__ == "__main__":
    main()
