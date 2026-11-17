"""Database engine + connection helpers.

Reads ``DATABASE_URL`` from ``.env`` (never hard-coded, never committed) and
builds a SQLAlchemy engine. For this project the database is PostgreSQL hosted
on Neon, but nothing here is Neon-specific.

Quick connection test:
    python -m src.db
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

load_dotenv()  # load variables from .env in the project root

# Placeholder value shipped in .env.example - treat as "not configured".
_PLACEHOLDER_PREFIX = "postgresql+psycopg2://user:password@host"


def _normalise_url(url: str) -> str:
    """Make a provider's URL usable by SQLAlchemy + psycopg2.

    Neon and Supabase hand out URLs starting ``postgresql://`` (or the older
    ``postgres://``). SQLAlchemy needs the driver named, so ``+psycopg2`` is
    inserted. Any query string (e.g. ``?sslmode=require``) is kept.
    """
    for prefix in ("postgresql+psycopg2://", "postgresql+"):
        if url.startswith(prefix):
            return url  # driver already specified
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    return url


def get_database_url() -> str:
    """Return the configured database URL, or raise a helpful error."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url or url.startswith(_PLACEHOLDER_PREFIX):
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and paste your "
            "Neon/Supabase connection string into DATABASE_URL."
        )
    return _normalise_url(url)


def get_engine(echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine.

    ``pool_pre_ping`` quietly checks a connection is alive before use, which
    matters for serverless Postgres (Neon) that may close idle connections.
    """
    return create_engine(get_database_url(), echo=echo, pool_pre_ping=True)


def init_schema(engine: Engine, schema_path: str | Path = "sql/schema.sql") -> None:
    """Create all tables by running ``sql/schema.sql``.

    The script drops and recreates the tables, so this resets the database.
    A raw psycopg2 connection is used because the script contains several
    statements separated by ``;`` (SQLAlchemy's ``text()`` expects one).
    """
    script = Path(schema_path).read_text(encoding="utf-8")
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute(script)
        raw.commit()
    finally:
        raw.close()


if __name__ == "__main__":
    engine = get_engine()
    with engine.connect() as conn:
        database = conn.execute(text("select current_database()")).scalar_one()
        version = conn.execute(text("select version()")).scalar_one()
    print("Connected OK")
    print("  database:", database)
    print("  server  :", version.split(" on ")[0])
