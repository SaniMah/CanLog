"""Load CAN bus logs into pandas DataFrames.

Supports the CANdid / candump ("SocketCAN") log format, one frame per line:

    (1731916598.782538) can0 420#3F0000334200F257
     |__ epoch secs __|  |__| |_| |____ hex data ____|
                         iface  CAN ID (hex)

So each line is:  (timestamp) interface  CANID#HEXDATA
"""
from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

# (timestamp) interface CANID#DATA   — DATA may be empty (e.g. remote frames).
_CANDUMP_RE = re.compile(
    r"^\((?P<ts>\d+\.\d+)\)\s+(?P<iface>\S+)\s+"
    r"(?P<can_id>[0-9A-Fa-f]+)#(?P<data>[0-9A-Fa-f]*)"
)


def load_candump(path, interface: str | None = None) -> pd.DataFrame:
    """Read a candump ``.log`` file into a DataFrame.

    Parameters
    ----------
    path : str | Path
        Path to the ``.log`` file.
    interface : str, optional
        If given, keep only frames on this bus (e.g. ``"can0"``).

    Returns
    -------
    DataFrame with columns:
        timestamp : float  Unix epoch seconds (microsecond precision)
        can_id    : str    CAN identifier, upper-case hex (e.g. "4D1")
        data      : str    data field as hex string (may be "")
        dlc       : int    number of data bytes (data length code)
        iface     : str    bus interface (e.g. "can0")

    Lines that do not match the format are skipped; the count is stored in
    ``df.attrs["skipped_lines"]``.
    """
    path = Path(path)
    rows: list[tuple] = []
    skipped = 0

    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = _CANDUMP_RE.match(line)
            if not m:
                if line.strip():  # don't count blank lines as errors
                    skipped += 1
                continue
            if interface and m["iface"] != interface:
                continue
            data = m["data"].upper()
            rows.append(
                (
                    float(m["ts"]),
                    m["can_id"].upper(),
                    data,
                    len(data) // 2,  # 2 hex chars = 1 byte
                    m["iface"],
                )
            )

    df = pd.DataFrame(rows, columns=["timestamp", "can_id", "data", "dlc", "iface"])
    df.attrs["source_file"] = str(path)
    df.attrs["skipped_lines"] = skipped
    return df


# ---------------------------------------------------------------------------
# Loading a capture into the database (Step 2)
# ---------------------------------------------------------------------------

def read_candid_meta(meta_path) -> dict:
    """Read a CANdid ``*_meta.json`` into the fields log_file wants.

    Returns a dict with keys: source_dataset, vehicle_make, vehicle_model,
    capture_type, description, duration_s. Missing files/keys give None.
    """
    info = {
        "source_dataset": "CANdid",
        "vehicle_make": None,
        "vehicle_model": None,
        "capture_type": None,
        "description": None,
        "duration_s": None,
    }
    meta_path = Path(meta_path)
    if not meta_path.exists():
        return info
    raw = json.loads(meta_path.read_text(encoding="utf-8"))
    car = raw.get("Car Info", {})
    info.update(
        vehicle_make=car.get("Make"),
        vehicle_model=car.get("Model"),
        capture_type=raw.get("Capture Type"),
        description=raw.get("Capture Description"),
        duration_s=raw.get("Capture Duration (seconds)"),
    )
    return info


def insert_log_file(engine: Engine, filename: str, meta: dict, frame_count: int) -> int:
    """Insert one log_file row and return its new ``log_id``."""
    sql = text(
        """
        INSERT INTO log_file
            (filename, source_dataset, vehicle_make, vehicle_model,
             capture_type, description, duration_s, frame_count)
        VALUES
            (:filename, :source_dataset, :vehicle_make, :vehicle_model,
             :capture_type, :description, :duration_s, :frame_count)
        RETURNING log_id
        """
    )
    params = {"filename": filename, "frame_count": frame_count, **meta}
    with engine.begin() as conn:  # begin() = commit on success, rollback on error
        return conn.execute(sql, params).scalar_one()


def copy_frames(engine: Engine, log_id: int, df: pd.DataFrame) -> int:
    """Bulk-load frames into can_frame using PostgreSQL COPY.

    COPY streams all rows in one pass — far faster than thousands of INSERTs
    over the network. We build a tab-separated buffer in memory and hand it to
    psycopg2's ``copy_expert``. Returns the number of rows loaded.
    """
    buf = io.StringIO()
    for ts, can_id, data, dlc in zip(
        df["timestamp"], df["can_id"], df["data"], df["dlc"]
    ):
        # columns: log_id, ts, can_id, data, dlc  (tab-separated, text format)
        buf.write(f"{log_id}\t{ts}\t{can_id}\t{data}\t{dlc}\n")
    buf.seek(0)

    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.copy_expert(
            "COPY can_frame (log_id, ts, can_id, data, dlc) FROM STDIN WITH (FORMAT text)",
            buf,
        )
        raw.commit()
    finally:
        raw.close()
    return len(df)


def store_profiles(engine: Engine, log_id: int, profile_df: pd.DataFrame) -> int:
    """Write per-ID timing profiles (from profile_ids) into id_profile."""
    cols = [
        "can_id", "frame_count", "freq_hz", "median_period", "period_iqr",
        "min_period", "max_period", "first_ts", "last_ts",
    ]
    out = profile_df.rename(columns={"count": "frame_count"}).copy()
    out = out[cols]
    out.insert(0, "log_id", log_id)
    out.to_sql("id_profile", engine, if_exists="append", index=False)
    return len(out)
