# NOTES — CAN Log Analyser

Plain-English notes on how each part works, for my own understanding and
interview prep. One short entry per build step.

---

## Step 0 — Setup (8 Nov 2026)

**Goal:** get an empty, well-organised project ready so every later step has a
home, and make sure secrets/data can never be committed by accident.

**What I created and why:**

- **Folder layout** — `data/ src/ sql/ app/ tests/ notebooks/`. Separating code
  (`src/`), queries (`sql/`), the app (`app/`) and tests (`tests/`) keeps each
  concern in one place. Empty folders carry a `.gitkeep` file so Git tracks them
  (Git doesn't track empty directories on its own).

- **`.gitignore`** — tells Git what to never commit. The two important lines:
  - `.env` → keeps API keys and the database password out of the repo.
  - `data/*` (with `!data/.gitkeep`) → keeps large/licensed CAN logs out of the
    repo while still tracking the empty `data/` folder.
  It also ignores Python caches (`__pycache__`), the virtual environment
  (`.venv/`) and editor junk.

- **`.env.example`** — a committed *template* showing which secrets are needed
  (`DATABASE_URL`, `ANTHROPIC_API_KEY`) without real values. Anyone cloning the
  repo copies it to `.env` and fills in their own. The real `.env` is ignored.

- **`requirements.txt`** — the exact Python packages the project needs, so the
  environment is reproducible with one `pip install -r requirements.txt`.
  Core now (pandas, numpy, SQLAlchemy, psycopg2, streamlit, pytest);
  optional ones (scikit-learn, cantools) are listed commented-out.

- **`src/__init__.py`** — makes `src/` an importable Python package and lists the
  modules that will be filled in later steps.

- **`README.md`** — the public face of the project, written as a consulting case
  (problem → what it does → how to run). Marked "in development"; claims will be
  trimmed to what's actually tested at the end.

**Database choice:** PostgreSQL (hosted on Supabase or Neon), accessed through
SQLAlchemy so the Python code doesn't hard-code one database. This gives a
"production-like" story for the portfolio while keeping local dev simple.

**Next (Step 1):** load one CANdid capture, compute median gap per CAN ID, flag
gaps > 3× median, and plot one ID's timeline with the gaps marked.

---

## Step 1 — Evening test (9 Nov 2026)

**Goal:** prove the core idea end-to-end on one real capture — load frames,
learn each ID's normal rate, flag timing gaps, and plot one ID.

**Dataset used:** CANdid, capture `2_brakes` (session 2, "Brakes"): a 2017 Mazda
CX-3, 81 s, driver depressing/releasing the brakes every ~11 s. Files live in
`data/candid/` (git-ignored). Source: University of Adelaide figshare,
DOI 10.25909/29068553.v2, CC BY 4.0.

**Log format (candump / SocketCAN):**
```
(1731916598.782538) can0 420#3F0000334200F257
 |__ epoch secs __|  |__| |_| |____ hex data ____|
                    iface  CAN ID
```

**What each file does:**
- **`src/load.py`** — `load_candump()` parses that format with a regex into a
  DataFrame (`timestamp, can_id, data, dlc, iface`). Bad lines are counted, not
  crashed on.
- **`src/profile.py`** — `profile_ids()` gives per-ID stats: count, frequency,
  **median period** (typical gap between frames, robust to outliers) and
  **period IQR** (how steady). `find_large_gaps(k=3)` flags any inter-frame gap
  bigger than `k ×` that ID's median period = a candidate dropout.
- **`run_step1.py`** — ties it together: prints a summary, lists the biggest
  gaps, and saves a timing plot to `reports/figures/`.

**Results on the brakes capture:**
- 184,634 frames, 93 unique IDs, 0 lines skipped.
- Busiest IDs run a steady 100 Hz (10 ms period) with tiny spread — healthy.
- The `k=3 × median` rule flagged **202 gaps, all on ID `3D2`.**

**Key finding (and a real limitation):** ID `3D2` is **not** dropping out — it's
**bursty**. It sends fast (~33 ms) then pauses (~200 ms), repeatedly, all
capture. The naive `k × median` rule can't distinguish "bursty / multi-rate" from
"dead", so it produces systematic **false positives** on `3D2`. A genuine dropout
would be a *one-off* large gap, not a regular rhythm. This motivates Step 4/5:
use a robust expected period and/or require the gap to be a one-off, then measure
precision/recall to prove the improvement.

**Why this matters:** the plot (not the numbers alone) exposed the false positive.
That "plot it, find the flaw, fix it, measure it" loop is the story this project
is meant to tell.

**Next (Step 2):** design the PostgreSQL schema (`log_file`, `can_frame`,
`id_profile`, `anomaly`) and bulk-load a capture — needs the Supabase/Neon
`DATABASE_URL` in `.env`.

---

## Step 2 — Database (10 Nov 2026)

**Goal:** design a proper relational schema and bulk-load a capture into
PostgreSQL (Neon, hosted in AWS Sydney).

**Schema (`sql/schema.sql`) — four tables, explained for FIT2094:**
- **`log_file`** (parent) — one row per capture. File-level facts (vehicle,
  capture type, duration) live here *once* instead of being repeated on every
  frame. That's **normalisation (3NF)**: no redundant, update-prone data.
- **`can_frame`** (fact table) — one row per frame, with a **foreign key**
  `log_id → log_file` and `ON DELETE CASCADE` (delete a log and its frames go
  too). A **CHECK** constraint keeps `dlc` between 0 and 8.
- **`id_profile`** — learned "normal" per ID, `UNIQUE(log_id, can_id)` so each
  ID has exactly one profile per log.
- **`anomaly`** — detected faults (Step 4); a **CHECK** limits `anomaly_type`
  to the four allowed values.
- **Keys:** surrogate `SERIAL`/`BIGSERIAL` primary keys (simple, stable joins).
- **Index:** `idx_can_frame_log_can_ts` on `(log_id, can_id, ts)` matches our
  most common query — "ID X's frames in this log, in time order" — which would
  otherwise scan all 184k rows.

**Loading (`src/load.py` + `run_step2.py`):**
- Metadata parsed from the matching `*_meta.json` into the `log_file` row.
- Frames bulk-loaded with PostgreSQL **`COPY`** (via psycopg2 `copy_expert`),
  streaming all 184k rows in one pass — far faster than many `INSERT`s over the
  network. `UNIQUE(filename)` stops the same file loading twice.
- Profiles written with pandas `to_sql`.

**Result:** `can_frame` = 184,634 rows, `id_profile` = 93 rows, verified by
querying Postgres directly.

---

## Step 3 — SQL analysis (10 Nov 2026)

**Goal:** a set of saved, reusable SQL queries (`sql/analysis.sql`) that turn
the raw frames into findings. `run_step3.py` runs them and saves charts.

**Techniques used:** aggregation + `GROUP BY/HAVING`, **window functions**
(`LAG()` to measure inter-frame gaps, bucketing for per-time-slice rates),
set operations (`EXCEPT` for "IDs in one log but not another"), and joins.

**Findings on the brakes capture:**
1. **Busy, steady bus:** ~2,274 frames/s across 93 IDs; traffic is flat over
   the whole 81 s (see `reports/figures/step3_bus_rate.png`) — healthy.
2. **Real dropout candidates:** the longest silences are on IDs **`5C7`** and
   **`4F8`** (~1.12 s gaps). These differ from `3D2`'s *regular* burst gaps
   (Step 1) — a one-off long gap is the shape a true dropout should have. Step 4
   must separate "one-off long gap" from "normally bursty".
3. **All frames are 8 bytes** (classic CAN, full payloads).
4. **10 IDs never change their payload** (e.g. `202`, `215`) — static status
   messages; a clean part of each ID's "normal" fingerprint.
5. **Most variable ID is `075`** (payload differs 83% of the time) — a live
   signal such as a counter or wheel speed.

**Note:** the cross-log query (`ids_only_in_log_a`) needs a second capture
loaded; it comes into its own in Step 5 when we add more logs.

**Next (Step 4):** detection rules writing to the `anomaly` table — dropout
(with the bursty-ID fix so `3D2` isn't flagged), timing drift, unknown ID,
missing ID.
