"""Step 3 - SQL analysis.

Run the saved queries in sql/analysis.sql against the loaded capture, print a
few headline findings, and save two charts (bus rate over time, payload-size
mix).

Run:
    python run_step3.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from src.db import get_engine  # noqa: E402

ANALYSIS_SQL = Path("sql/analysis.sql")
FIG_DIR = Path("reports/figures")


def load_named_queries(path=ANALYSIS_SQL) -> dict[str, str]:
    """Split sql/analysis.sql into {name: sql} on the '-- name:' markers."""
    queries: dict[str, str] = {}
    name, body = None, []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("-- name:"):
            if name:
                queries[name] = "\n".join(body).strip()
            name = line.split(":", 1)[1].strip()
            body = []
        elif name:
            body.append(line)
    if name:
        queries[name] = "\n".join(body).strip()
    return queries


def main():
    engine = get_engine()
    q = load_named_queries()

    def run(name) -> pd.DataFrame:
        return pd.read_sql_query(q[name], engine)

    print("=== Overview ===")
    print(run("overview").to_string(index=False))

    print("\n=== Busiest IDs ===")
    print(run("busiest_ids").to_string(index=False))

    print("\n=== Longest gaps (dropout candidates) ===")
    print(run("longest_gaps").to_string(index=False))

    print("\n=== Payload-size (DLC) distribution ===")
    print(run("dlc_distribution").to_string(index=False))

    const = run("constant_payload_ids")
    print(f"\n=== Constant-payload IDs: {len(const)} IDs never change their data ===")
    print(const.head().to_string(index=False))

    var = run("most_variable_ids")
    print("\n=== Most variable IDs (live signals) ===")
    print(var.head().to_string(index=False))

    # --- charts ---
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    rate = run("per_5s_rate")
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar(rate["bucket_5s"] * 5, rate["frames"], width=4, color="#2a6f97")
    ax.set_xlabel("time since start (s)")
    ax.set_ylabel("frames per 5 s")
    ax.set_title("Bus traffic over time (steady = healthy)")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "step3_bus_rate.png", dpi=120)

    dlc = run("dlc_distribution")
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(dlc["dlc"].astype(str), dlc["frames"], color="#e07a5f")
    ax.set_xlabel("data bytes (DLC)")
    ax.set_ylabel("frames")
    ax.set_title("Payload-size distribution")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "step3_dlc.png", dpi=120)

    print(f"\nSaved charts -> {FIG_DIR}/step3_bus_rate.png, step3_dlc.png")


if __name__ == "__main__":
    main()
