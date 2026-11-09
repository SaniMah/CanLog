# CAN Log Analyser

Automated fault analysis for automotive **CAN bus** logs: load raw frames into a
database, learn what "normal" traffic looks like for each CAN ID, flag faults
(dropouts, timing drift, unknown/missing IDs), show the results on a dashboard,
and generate a structured test report.

> ⚠️ **Status: in development.** This README describes the target; see
> [NOTES.md](NOTES.md) for what is actually built so far. Only tested features
> will be claimed here on completion.

---

## Problem

In automotive test and validation, a CAN bus carries hundreds of messages per
second. When a control unit drops out or a message's timing drifts, it hides in
tens of thousands of log lines. Finding it by hand (scrolling logs, eyeballing
oscilloscope traces) is slow and easy to get wrong. This tool automates that
first-pass triage.

## What it does (target)

1. **Load** a CAN log (timestamp, CAN ID, data bytes) into a database.
2. **Profile** each CAN ID: message count, median period, period spread.
3. **Detect** faults: dropouts, timing drift, unknown IDs, missing IDs.
4. **Dashboard** (Streamlit): overview, anomaly timeline, ID drill-down, export.
5. **AI report**: an LLM writes a structured report from the computed numbers only.
6. **Evaluate**: precision / recall against labelled and injected faults.

## Tech stack

Python · pandas · NumPy · PostgreSQL (SQLAlchemy) · Streamlit · pytest · LLM API

## Project layout

```
data/        CAN logs (git-ignored — not committed)
src/         load, profile, detect, evaluate, report, db
sql/         schema + saved analysis queries
app/         Streamlit dashboard
tests/       pytest
notebooks/   exploratory analysis
NOTES.md     plain-English notes (how each part works)
```

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env     # then edit .env with your PostgreSQL URL + API key
```

A hosted PostgreSQL database (e.g. **Supabase** or **Neon**, both free tier) is
used; put its connection string in `.env` as `DATABASE_URL`.

## Datasets (public, credited)

- **CANdid** — Australian, CC BY 4.0, multiple vehicles, labelled actions
  (main dataset).
- **ROAD** — real vehicle, labelled attacks incl. suspension (frames removed =
  real dropouts) (evaluation).
- Fallback: comma2k19. Optional decoding: cantools + opendbc DBC files.

Each dataset's licence is credited here on completion.

## Note on AI assistance

This project was built with AI assistance (Claude). Design decisions, code and
documentation were reviewed before use.
