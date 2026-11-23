"""SQLite WAL database management and query helpers for the Real-Time Sales Tracker."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from src.config import DB_PATH, SQL_VIEWS_PATH


def get_connection(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    """Open a SQLite connection configured in WAL mode for safe concurrent reads/writes."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=15.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    return conn


def init_schema(db_path: Path | str = DB_PATH) -> None:
    """Create raw_orders table, indexes, and 4-gate SQL classification views."""
    ddl = SQL_VIEWS_PATH.read_text(encoding="utf-8")
    with get_connection(db_path) as conn:
        conn.executescript(ddl)
        conn.commit()


def reset_raw_orders(db_path: Path | str = DB_PATH) -> None:
    """Drop all rows in raw_orders and ensure schema/views exist."""
    init_schema(db_path)
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM raw_orders;")
        conn.execute("DELETE FROM sqlite_sequence WHERE name='raw_orders';")
        conn.commit()


def insert_raw_orders(
    rows: Iterable[tuple[Any, ...]],
    db_path: Path | str = DB_PATH,
) -> int:
    """Batch-insert raw order tuples into raw_orders and return inserted row count."""
    batch = list(rows)
    if not batch:
        return 0
    sql = """
        INSERT INTO raw_orders (
            event_timestamp_utc,
            order_id,
            agent_name,
            discount_code,
            market,
            language,
            customer_email,
            amount_usd,
            ingested_at_utc,
            bucket_id,
            scenario_tag
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    with get_connection(db_path) as conn:
        conn.executemany(sql, batch)
        conn.commit()
    return len(batch)


def get_max_bucket_id(db_path: Path | str = DB_PATH) -> int | None:
    """Return MAX(bucket_id) from raw_orders, or None if table is empty."""
    init_schema(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT MAX(bucket_id) AS max_b FROM raw_orders;").fetchone()
        return int(row["max_b"]) if row and row["max_b"] is not None else None


def get_latest_scenario_tag(db_path: Path | str = DB_PATH) -> str | None:
    """Return the scenario_tag of the most recent ingested raw order."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT scenario_tag FROM raw_orders ORDER BY raw_event_id DESC LIMIT 1;"
        ).fetchone()
        return str(row["scenario_tag"]) if row else None


def query_dataframe(
    sql: str,
    params: tuple[Any, ...] = (),
    db_path: Path | str = DB_PATH,
) -> pd.DataFrame:
    """Execute a SQL query and return a Pandas DataFrame."""
    with get_connection(db_path) as conn:
        return pd.read_sql_query(sql, conn, params=params)


def load_classified_orders(
    db_path: Path | str = DB_PATH,
    since_utc: str | None = None,
) -> pd.DataFrame:
    """Load rows from v_classified_orders, optionally filtered from since_utc onward."""
    if since_utc:
        return query_dataframe(
            "SELECT * FROM v_classified_orders WHERE event_timestamp_utc >= ? ORDER BY event_timestamp_utc ASC;",
            (since_utc,),
            db_path=db_path,
        )
    return query_dataframe(
        "SELECT * FROM v_classified_orders ORDER BY event_timestamp_utc ASC;",
        db_path=db_path,
    )


def load_valid_sales(
    db_path: Path | str = DB_PATH,
    since_utc: str | None = None,
) -> pd.DataFrame:
    """Load validated, deduplicated sales from v_valid_sales."""
    if since_utc:
        return query_dataframe(
            "SELECT * FROM v_valid_sales WHERE event_timestamp_utc >= ? ORDER BY event_timestamp_utc ASC;",
            (since_utc,),
            db_path=db_path,
        )
    return query_dataframe(
        "SELECT * FROM v_valid_sales ORDER BY event_timestamp_utc ASC;",
        db_path=db_path,
    )


def load_quarantined_orders(
    db_path: Path | str = DB_PATH,
    since_utc: str | None = None,
) -> pd.DataFrame:
    """Load rejected / quarantined records from v_quarantined_orders."""
    if since_utc:
        return query_dataframe(
            "SELECT * FROM v_quarantined_orders WHERE event_timestamp_utc >= ? ORDER BY raw_event_id DESC;",
            (since_utc,),
            db_path=db_path,
        )
    return query_dataframe(
        "SELECT * FROM v_quarantined_orders ORDER BY raw_event_id DESC;",
        db_path=db_path,
    )
