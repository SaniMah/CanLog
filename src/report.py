"""Step 7 - AI test report.

Collect a capture's anomaly + validation numbers into a `facts` dict, then have
a LOCAL LLM (Ollama) write a structured report that uses ONLY those numbers. If
Ollama isn't running, fall back to a deterministic template filled from the same
facts, so a draft is always produced.

The report is always labelled a DRAFT to review before use, and the model is
told to use only the supplied numbers (no invented values).

Install the local model (one-off, done by the user):
    https://ollama.com  ->  ollama pull llama3.2
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")
DRAFT_BANNER = "DRAFT - review before use"


# --------------------------------------------------------------------------- #
# 1. Gather the facts (numbers only) from the database + evaluation study
# --------------------------------------------------------------------------- #
def gather_facts(engine: Engine, log_id: int, k: int = 3,
                 eval_csv: str | Path = "reports/eval_sweep.csv") -> dict:
    """Pull everything the report may state into one plain dict of numbers."""
    with engine.connect() as conn:
        lf = conn.execute(
            text("SELECT filename, vehicle_make, vehicle_model, capture_type, "
                 "description FROM log_file WHERE log_id = :l"),
            {"l": log_id},
        ).mappings().first()
        if lf is None:
            raise ValueError(f"no log_file with log_id={log_id}")

        n_frames = conn.execute(
            text("SELECT count(*) FROM can_frame WHERE log_id = :l"), {"l": log_id}
        ).scalar_one()
        n_ids = conn.execute(
            text("SELECT count(DISTINCT can_id) FROM can_frame WHERE log_id = :l"),
            {"l": log_id},
        ).scalar_one()
        span = conn.execute(
            text("SELECT max(ts) - min(ts) FROM can_frame WHERE log_id = :l"),
            {"l": log_id},
        ).scalar_one() or 0.0

        by_type = dict(conn.execute(
            text("SELECT anomaly_type, count(*) FROM anomaly WHERE log_id = :l "
                 "GROUP BY anomaly_type"), {"l": log_id}
        ).all())

        top = conn.execute(
            text("SELECT can_id, round((value * 1000)::numeric, 0) AS gap_ms, "
                 "round((start_ts - (SELECT min(ts) FROM can_frame WHERE log_id = :l))"
                 "::numeric, 2) AS at_s "
                 "FROM anomaly WHERE log_id = :l AND anomaly_type = 'dropout' "
                 "ORDER BY value DESC LIMIT 5"), {"l": log_id}
        ).all()

    facts = {
        "capture": {
            "filename": lf["filename"],
            "vehicle": f"{lf['vehicle_make']} {lf['vehicle_model']}".strip(),
            "type": lf["capture_type"],
            "description": lf["description"],
        },
        "traffic": {
            "frames": int(n_frames),
            "unique_ids": int(n_ids),
            "duration_s": round(float(span), 1),
            "frames_per_s": round(n_frames / span) if span else None,
        },
        "anomalies": {
            "total": int(sum(by_type.values())),
            "by_type": {k2: int(v) for k2, v in by_type.items()},
            "top_dropouts": [
                {"can_id": r.can_id, "gap_ms": float(r.gap_ms), "at_s": float(r.at_s)}
                for r in top
            ],
        },
        "detection": {
            "rule": "gap > max(k_med * median_period, k_p99 * p99_period)",
            "k_med": 3.0, "k_p99": 1.5,
        },
        "validation": _read_validation(eval_csv, k=k),
    }
    return facts


def _read_validation(eval_csv, k=3) -> dict:
    """Read precision/recall for the chosen k from the Step 5 sweep CSV."""
    path = Path(eval_csv)
    if not path.exists():
        return {}
    import csv
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            if abs(float(row["k"]) - k) < 1e-9:
                return {
                    "method": "24 known dropouts injected into a clean capture",
                    "k": k,
                    "precision": round(float(row["fixed_precision"]), 2),
                    "recall": round(float(row["fixed_recall"]), 2),
                    "naive_precision": round(float(row["naive_precision"]), 2),
                }
    return {}


# --------------------------------------------------------------------------- #
# 2. Prompt + local LLM call
# --------------------------------------------------------------------------- #
def build_prompt(facts: dict) -> str:
    return (
        "You are a test engineer writing a CAN bus fault-analysis report.\n"
        "Use ONLY the numbers in the JSON below. Do NOT invent any values, IDs, "
        "or measurements that are not present. If something is not in the data, "
        "say it is not available.\n\n"
        f"Begin the report with the line: {DRAFT_BANNER}\n"
        "Then write these sections as headings, in this order:\n"
        "  Method, Results, Analysis, Conclusion, Next checks.\n"
        "Keep it concise, factual and professional. Explain what the anomalies "
        "mean for a vehicle test engineer.\n\n"
        "DATA (JSON):\n"
        f"{json.dumps(facts, indent=2)}\n"
    )


def ollama_available(timeout: float = 2.0) -> bool:
    """Fast check that a local Ollama server is reachable (avoids long hangs)."""
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=timeout):
            return True
    except Exception:
        return False


def generate_with_ollama(prompt: str, model: str = DEFAULT_MODEL, timeout: int = 120) -> str:
    """Call a local Ollama server. Raises on any connection/HTTP error."""
    body = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
    req = urllib.request.Request(
        OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode())
    return payload.get("response", "").strip()


# --------------------------------------------------------------------------- #
# 3. Deterministic fallback (works with no LLM)
# --------------------------------------------------------------------------- #
def render_fallback(facts: dict) -> str:
    cap, tr, an = facts["capture"], facts["traffic"], facts["anomalies"]
    det, val = facts["detection"], facts.get("validation", {})

    lines = [
        f"# CAN Bus Test Report - {DRAFT_BANNER}",
        "",
        f"**Capture:** {cap['filename']} - {cap['vehicle']} ({cap['type']})  ",
        f"*{cap['description']}*",
        "",
        "## Method",
        f"Loaded {tr['frames']:,} CAN frames ({tr['unique_ids']} unique IDs, "
        f"{tr['duration_s']} s, ~{tr['frames_per_s']} frames/s) into PostgreSQL. "
        "Each ID's normal timing was profiled (median period and 99th-percentile "
        "gap). Dropouts were flagged where an inter-frame gap exceeded "
        f"`{det['rule']}` (k_med={det['k_med']:g}, k_p99={det['k_p99']:g}).",
        "",
        "## Results",
        f"- Total anomalies: **{an['total']}**"
        + (f" ({', '.join(f'{k}: {v}' for k, v in an['by_type'].items())})"
           if an["by_type"] else " - none; this capture looks clean."),
    ]
    if an["top_dropouts"]:
        lines.append("- Largest dropouts:")
        for d in an["top_dropouts"]:
            lines.append(f"    - ID `{d['can_id']}`: {d['gap_ms']:.0f} ms gap "
                         f"at {d['at_s']:.2f} s")
    if val:
        lines += [
            "",
            "## Validation",
            f"Detector validated by {val['method']}: at k={val['k']}, "
            f"**precision {val['precision']:.2f}, recall {val['recall']:.2f}** "
            f"(a naive median-only rule scored precision "
            f"{val['naive_precision']:.2f} on the same test).",
        ]
    lines += [
        "",
        "## Analysis",
        (f"{an['total']} timing anomalies were detected. The flagged IDs stopped "
         "transmitting for far longer than their own normal worst-case gap, which "
         "is consistent with a dropout (ECU reset, loose connector, or bus error) "
         "rather than normal bursty traffic."
         if an["total"] else
         "No anomalies were detected: every ID stayed within its normal timing "
         "envelope for the whole capture."),
        "",
        "## Conclusion",
        (f"The capture shows **{an['total']} dropout-type anomalies** that warrant "
         "investigation." if an["total"] else
         "The capture is **clean** by these rules - no dropouts, drift, or "
         "unexpected IDs."),
        "",
        "## Next checks",
        "- Inspect wiring and the transmitting ECU for any flagged IDs.",
        "- Compare against a known-good capture of the same vehicle/scenario.",
        "- Re-run against labelled real-fault data (e.g. the ROAD dataset) for "
        "independent confirmation.",
        "",
        f"_Generated from computed values only. {DRAFT_BANNER}._",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 4. Public entry point
# --------------------------------------------------------------------------- #
def generate_report(engine: Engine, log_id: int, model: str = DEFAULT_MODEL,
                    use_llm: bool = True) -> tuple[str, str]:
    """Return (report_markdown, source).

    source is "ollama:<model>" when the local LLM wrote it, else
    "template-fallback". The fallback always works, with or without Ollama.
    """
    facts = gather_facts(engine, log_id)
    if use_llm and ollama_available():
        try:
            text_out = generate_with_ollama(build_prompt(facts), model=model)
            if text_out:
                return text_out, f"ollama:{model}"
        except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
            pass  # Ollama not running / unreachable -> fall back
    return render_fallback(facts), "template-fallback"
