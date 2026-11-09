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
