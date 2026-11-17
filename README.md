# CAN Log Analyser

**Automated fault triage for automotive CAN bus logs** - load raw frames into a
database, learn what "normal" looks like for every CAN ID, flag timing faults
(dropouts, drift, unknown/missing IDs), show them on a dashboard, and generate a
structured test report. Validated with precision/recall against injected faults.

> Built as a portfolio project by **Sanithma** (Mechatronics Engineering &
> Computer Science, Monash University), drawing on hands-on CAN fault
> investigation during an engineering internship. AI tools were used to help
> revise the code and documentation; all logic and results were reviewed and
> tested.

---

## The problem

A vehicle's CAN bus carries **hundreds of messages per second** from dozens of
electronic control units (ECUs). When a unit drops out, resets, or its message
timing drifts, the symptom hides inside tens of thousands of near-identical log
lines. Finding it by hand - scrolling logs, eyeballing oscilloscope traces - is
slow, tedious, and easy to get wrong.

**This tool automates that first-pass triage:** point it at a capture and it
tells you which IDs misbehaved, when, and how badly - with the evidence to back
each call.

## Who it's for

Test and validation engineers (and students) who need to screen CAN captures
quickly and produce a defensible report, without hand-analysing every frame.

## What it does

```
.log capture -> load (parse) -> PostgreSQL (store) -> profile (learn normal)
             -> detect (flag faults) -> dashboard + AI report
```

1. **Load** a candump/SocketCAN `.log` into PostgreSQL (bulk `COPY`).
2. **Profile** every CAN ID: message count, rate, median period, timing spread.
3. **Detect** faults -> an `anomaly` table: dropouts, timing drift, unknown IDs,
   missing IDs.
4. **Dashboard** (Streamlit): overview, anomaly timeline, per-ID drill-down, and
   a downloadable anomaly table (CSV/Excel).
5. **AI report**: a local LLM writes a structured report from the computed
   numbers only (no cloud, no API key), labelled a draft for review.
6. **Evaluate**: precision/recall against injected faults, with a tuned threshold.

## Results & proof

**The detector works, and it's measured - not asserted.** The headline finding
is a real engineering story:

- A naive "flag any gap > 3x the median period" rule produced **202 false
  positives**, all on one ID (`3D2`) - which turned out to be *bursty*
  (alternating fast and slow traffic), not faulty.

  ![ID 3D2 timing](reports/figures/step1_3D2_gaps.png)

- The fix: require a gap to exceed **both** `3x median` **and** `1.5x the ID's
  own 99th-percentile gap`, so routine big gaps on bursty IDs are treated as
  normal. Validated by injecting 24 known dropouts into a clean capture:

  | threshold k | precision | recall | notes |
  |---|---|---|---|
  | **3 (chosen)** | **1.00** | **1.00** | naive rule scores just **0.11** precision here |
  | 8 | 1.00 | 0.96 | |
  | 32 | 1.00 | 0.38 | misses the shortest dropouts |

  ![Precision/recall vs k](reports/figures/step5_pr_vs_k.png)

At the chosen threshold the detector finds **every** injected dropout with **no
false positives**, where the naive rule's precision collapses to 0.11.

## How it works (tech)

**Python** (pandas, NumPy) / **PostgreSQL** on Neon via **SQLAlchemy** /
**Streamlit** / **pytest** / a **local LLM** (Ollama).

**Database schema** (`sql/schema.sql`) - one parent table and three children, in
3rd normal form:

- `log_file` - one row per capture (vehicle, type, duration).
- `can_frame` - one row per frame, `FK -> log_file (ON DELETE CASCADE)`, a
  `CHECK` on `dlc`, and a composite index on `(log_id, can_id, ts)` for the
  common "this ID, in time order" query.
- `id_profile` - learned normal per ID, `UNIQUE(log_id, can_id)`.
- `anomaly` - detected faults, `CHECK` on the allowed types.

## How to run

```powershell
# 1. Environment
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Database - create a free PostgreSQL on Neon or Supabase, then:
copy .env.example .env
#    edit .env: DATABASE_URL=postgresql://USER:PASS@HOST/DB?sslmode=require

# 3. Pipeline (each step is a script)
python run_step2.py          # create schema + bulk-load a capture
python run_step3.py          # SQL analysis + charts
python run_step4.py          # detection -> anomaly table
python run_step5.py          # evaluation: precision/recall vs k
python run_inject_demo.py    # add a labelled faulty capture for the demo
python run_step7.py          # generate the AI report

# 4. Dashboard
streamlit run app/dashboard.py
```

The AI report runs on a **local** model: install [Ollama](https://ollama.com),
`ollama pull llama3.2`, and the report tab upgrades from template to LLM prose
automatically. Without it, a template-filled draft is still produced.

## Project structure

```
src/        load, profile, detect, evaluate, report, db
sql/        schema.sql + analysis.sql (saved queries)
app/        dashboard.py (Streamlit)
tests/      pytest (detection + parsing + scoring)
reports/    figures + generated reports
run_step*.py   one runnable script per build step
```

## Testing

```powershell
pytest -q        # 13 tests, no database needed (pure functions on synthetic data)
```

Covers log parsing, the brief's three gap cases (no gaps / one known gap / empty
log), the bursty-ID fix, timing drift, and the precision/recall scorer.

## Limitations (honest notes)

- Evaluation uses **injected** faults on a clean capture: exact ground truth,
  but synthetic. A stronger test is the **ROAD** dataset's real "suspension"
  attacks; the detector and scorer are ready to run on it once loaded.
- Works on **raw frame timing** - it does not decode signal values (DBC decoding
  is an optional extension via `cantools`).
- Thresholds are tuned on one vehicle/scenario; a production tool would
  re-profile per vehicle.

## Datasets & licences

- **CANdid** - CAN bus captures from multiple vehicles, University of Adelaide.
  Licence **CC BY 4.0**. DOI [10.25909/29068553](https://doi.org/10.25909/29068553).
- Data files live in `data/` and are **not** committed (git-ignored).

## AI assistance

AI tools were used to help revise the code and documentation; all logic and
results were reviewed and tested. The anomaly detector and evaluation are the
author's own method.
