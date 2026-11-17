"""Step 2 - database.

Create the schema in PostgreSQL (Neon) and bulk-load one CANdid capture:
its log_file row, all CAN frames (via COPY), and the per-ID timing profiles.
Then print row counts straight from the database to prove it loaded.

Run:
    python run_step2.py                 # reset schema + load the brakes capture
    python run_step2.py --no-reset      # load without dropping existing tables
    python run_step2.py path\\to\\x.log  # load a different capture
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parent))
from src.db import get_engine, init_schema  # noqa: E402
from src.load import (  # noqa: E402
    copy_frames,
    insert_log_file,
    load_candump,
    read_candid_meta,
    store_profiles,
)
from src.profile import profile_ids  # noqa: E402

DEFAULT_LOG = Path("data/candid/2_brakes_CAN.log")


def main(log_path=None, reset=True):
    log_path = Path(log_path) if log_path else DEFAULT_LOG
    engine = get_engine()

    if reset:
        print("Creating schema (sql/schema.sql) ...")
        init_schema(engine)

    print(f"Parsing {log_path.name} ...")
    df = load_candump(log_path)
    print(f"  {len(df):,} frames, {df['can_id'].nunique()} IDs")

    # metadata file sits next to the CAN log: 2_brakes_CAN.log -> 2_brakes_meta.json
    meta_path = log_path.with_name(log_path.name.replace("_CAN.log", "_meta.json"))
    meta = read_candid_meta(meta_path)

    log_id = insert_log_file(engine, log_path.name, meta, frame_count=len(df))
    print(f"  log_file row inserted: log_id = {log_id} "
          f"({meta['vehicle_make']} {meta['vehicle_model']}, {meta['capture_type']})")

    n_frames = copy_frames(engine, log_id, df)
    print(f"  COPYed {n_frames:,} frames into can_frame")

    n_prof = store_profiles(engine, log_id, profile_ids(df))
    print(f"  stored {n_prof} id_profile rows")

    # --- verify straight from the database ---
    print("\nRow counts in the database:")
    with engine.connect() as conn:
        for table in ("log_file", "can_frame", "id_profile", "anomaly"):
            n = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            print(f"  {table:<11} {n:>8,}")

        print("\nBusiest IDs (from id_profile, via SQL):")
        rows = conn.execute(text(
            """
            SELECT can_id, frame_count, round(freq_hz::numeric, 1) AS freq_hz,
                   round((median_period * 1000)::numeric, 2) AS median_ms
            FROM id_profile
            WHERE log_id = :log_id
            ORDER BY frame_count DESC
            LIMIT 5
            """
        ), {"log_id": log_id}).all()
        for r in rows:
            print(f"  {r.can_id:<5} {r.frame_count:>6} frames  "
                  f"{r.freq_hz:>6} Hz  median {r.median_ms} ms")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    reset = "--no-reset" not in sys.argv
    main(args[0] if args else None, reset=reset)
