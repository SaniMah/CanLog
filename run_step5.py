"""Step 5 - evaluation.

Inject known dropouts into the clean capture, run the detector, and measure
precision / recall. Sweep the threshold k, compare the fixed rule against the
naive rule, pick a k, and explain the trade-off.

Run:
    python run_step5.py
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
from src.detect import detect_dropouts  # noqa: E402
from src.evaluate import inject_dropouts, make_dropout_events, score  # noqa: E402
from src.load import read_frames  # noqa: E402

FIG_DIR = Path("reports/figures")
K_VALUES = [1.5, 2, 3, 4, 6, 8, 12, 16, 24, 32]


def main(log_id: int = 1):
    engine = get_engine()
    clean = read_frames(engine, log_id)

    events = make_dropout_events(clean, n=24)
    dirty = inject_dropouts(clean, events)
    removed = len(clean) - len(dirty)
    print(f"Injected {len(events)} dropouts into log {log_id} "
          f"({removed} frames removed). Durations "
          f"{sorted({e['duration'] for e in events})} s.")

    rows = []
    for k in K_VALUES:
        fixed = score(detect_dropouts(dirty, k_med=k, use_p99=True), events)
        naive = score(detect_dropouts(dirty, k_med=k, use_p99=False), events)
        rows.append({
            "k": k,
            "fixed_precision": fixed["precision"], "fixed_recall": fixed["recall"],
            "fixed_f1": fixed["f1"], "fixed_fp": fixed["fp"],
            "naive_precision": naive["precision"], "naive_recall": naive["recall"],
            "naive_fp": naive["fp"],
        })
    table = pd.DataFrame(rows)

    pd.set_option("display.float_format", lambda v: f"{v:.3f}")
    print("\nPrecision / recall vs k:")
    print(table.to_string(index=False))

    # choose k: best F1 for the fixed rule
    best = table.loc[table["fixed_f1"].idxmax()]
    print(f"\nChosen k = {best['k']:g} (fixed rule): "
          f"precision {best['fixed_precision']:.2f}, recall {best['fixed_recall']:.2f}, "
          f"F1 {best['fixed_f1']:.2f}")
    k3 = table.loc[table["k"] == 3].iloc[0]
    print(f"At k=3, the fix matters: fixed precision {k3['fixed_precision']:.2f} "
          f"vs naive precision {k3['naive_precision']:.2f} "
          f"(naive has {int(k3['naive_fp'])} false positives from bursty IDs).")

    # --- plot ---
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(table["k"], table["fixed_precision"], "-o", color="#2a6f97", label="fixed precision")
    ax.plot(table["k"], table["fixed_recall"], "-o", color="#2a9d8f", label="fixed recall")
    ax.plot(table["k"], table["naive_precision"], "--s", color="#d00000", label="naive precision")
    ax.axvline(best["k"], color="#888", ls=":", lw=1, label=f"chosen k = {best['k']:g}")
    ax.set_xlabel("threshold k (gap > k x median)")
    ax.set_ylabel("score")
    ax.set_ylim(-0.03, 1.03)
    ax.set_title("Dropout detection: precision / recall vs k (24 injected dropouts)")
    ax.legend(loc="lower left", fontsize=8)
    fig.tight_layout()
    out = FIG_DIR / "step5_pr_vs_k.png"
    fig.savefig(out, dpi=120)

    table.to_csv("reports/eval_sweep.csv", index=False)
    print(f"\nSaved plot -> {out}  and table -> reports/eval_sweep.csv")
    print("\nTrade-off: small k catches small dropouts (high recall) but, with the "
          "naive rule, drowns in false positives (low precision). The p99 fix keeps "
          "precision high across k; raising k then only trades away recall on the "
          "shortest dropouts.")


if __name__ == "__main__":
    main()
