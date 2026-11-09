"""Step 4 — detection.

Read a loaded capture back from the database, run the detection rules, write the
anomalies to the `anomaly` table, and show that the dropout fix works: the naive
rule floods on bursty ID 3D2, the fixed rule does not.

Run:
    python run_step4.py            # detect on log_id = 1
    python run_step4.py 2          # detect on another log_id
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
    detect_missing_ids,
    detect_timing_drift,
    detect_unknown_ids,
    write_anomalies,
)
from src.load import read_frames  # noqa: E402

K_MED = 3.0
K_P99 = 1.5


def main(log_id: int = 1):
    engine = get_engine()
    df = read_frames(engine, log_id)
    print(f"Loaded {len(df):,} frames for log_id={log_id} "
          f"({df['can_id'].nunique()} IDs)")

    # --- demonstrate the dropout fix: naive vs fixed ---
    naive = detect_dropouts(df, k_med=K_MED, use_p99=False)
    fixed = detect_dropouts(df, k_med=K_MED, k_p99=K_P99, use_p99=True)
    print("\nDropout rule comparison (k_med=3):")
    print(f"  naive  (gap > 3x median)          : {len(naive):>4} flags, "
          f"IDs {sorted(naive['can_id'].unique())}")
    print(f"  fixed  (also > 1.5x p99 per ID)   : {len(fixed):>4} flags, "
          f"IDs {sorted(fixed['can_id'].unique())}")
    if not naive.empty:
        top = naive["can_id"].value_counts()
        print(f"  -> naive's false positives are dominated by: "
              f"{top.index[0]} ({top.iloc[0]} of {len(naive)})")

    # --- run the full rule set and store it ---
    baseline_ids = df["can_id"].unique()  # single log: baseline = its own IDs
    drift = detect_timing_drift(df)
    unknown = detect_unknown_ids(df, known_ids=baseline_ids)
    missing = detect_missing_ids(df, expected_ids=baseline_ids)

    import pandas as pd
    anomalies = pd.concat([fixed, drift, unknown, missing], ignore_index=True)

    clear_anomalies(engine, log_id)
    n = write_anomalies(engine, log_id, anomalies)
    print(f"\nWrote {n} anomalies to the database.")

    # --- summarise from the database ---
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT anomaly_type, count(*) AS n FROM anomaly "
            "WHERE log_id = :log_id GROUP BY anomaly_type ORDER BY n DESC"
        ), {"log_id": log_id}).all()
    print("\nAnomalies by type (from DB):")
    if rows:
        for r in rows:
            print(f"  {r.anomaly_type:<13} {r.n}")
    else:
        print("  (none — this capture is clean; Step 5 injects faults to test)")

    print("\nNote: baseline = this log's own IDs, so unknown/missing are 0 here; "
          "they matter when comparing captures. The clean result is expected — "
          "Step 5 injects known dropouts to measure precision/recall.")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
