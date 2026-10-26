"""SQLite database: connection and tables.

SQLite needs no server and keeps everything in one file (data/varavu.db by default),
which suits a local MCP server. The SQL is plain enough to move to Postgres later.
"""
import os
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS uploads (
    id          INTEGER PRIMARY KEY,
    file_path   TEXT NOT NULL,
    file_hash   TEXT NOT NULL UNIQUE,            -- the same photo is never registered twice
    status      TEXT NOT NULL DEFAULT 'pending', -- pending | processed | failed
    error       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS drafts (
    id            INTEGER PRIMARY KEY,
    upload_id     INTEGER NOT NULL REFERENCES uploads(id),
    entry_index   INTEGER NOT NULL,              -- a notebook page can give several drafts
    document_type TEXT NOT NULL,
    data          TEXT NOT NULL,                 -- BillEntry JSON after the agent
    issues        TEXT NOT NULL DEFAULT '[]',
    needs_review  TEXT NOT NULL DEFAULT '[]',
    suggestions   TEXT NOT NULL DEFAULT '[]',
    corrections   TEXT NOT NULL DEFAULT '[]',
    steps         TEXT NOT NULL DEFAULT '[]',
    status        TEXT NOT NULL DEFAULT 'pending', -- pending | confirmed | rejected
    reject_reason TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS vendors (
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL UNIQUE,
    gstin            TEXT,
    phone            TEXT,
    default_category TEXT
);

CREATE TABLE IF NOT EXISTS transactions (
    id               INTEGER PRIMARY KEY,
    draft_id         INTEGER NOT NULL UNIQUE REFERENCES drafts(id),
    upload_id        INTEGER NOT NULL REFERENCES uploads(id),
    vendor_id        INTEGER REFERENCES vendors(id),
    bill_date        TEXT NOT NULL,              -- ISO date, e.g. 2024-03-01
    transaction_type TEXT NOT NULL,              -- purchase | sale | expense
    category         TEXT NOT NULL,
    document_type    TEXT NOT NULL,
    vendor_name      TEXT,
    bill_number      TEXT,
    total            REAL NOT NULL,
    tax_total        REAL,
    amount_paid      REAL,
    balance_due      REAL,
    payment_mode     TEXT,
    data             TEXT NOT NULL,              -- confirmed BillEntry JSON
    model_data       TEXT NOT NULL,              -- the agent's version, to measure corrections later
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS line_items (
    id             INTEGER PRIMARY KEY,
    transaction_id INTEGER NOT NULL REFERENCES transactions(id),
    description    TEXT NOT NULL,
    quantity       REAL,
    unit           TEXT,
    rate           REAL,
    amount         REAL,
    tax_rate       REAL
);

CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(bill_date);

-- Full-text search over confirmed bills (SQLite FTS5, ranked with BM25).
CREATE VIRTUAL TABLE IF NOT EXISTS bill_search USING fts5(
    transaction_id UNINDEXED, vendor_name, bill_number, category, items
);
"""


def data_dir() -> Path:
    return Path(os.getenv("VARAVU_DATA_DIR", "data"))


def db_path_for(shop: str | None = None) -> str:
    """Each shop gets its own database file, so one shop's queries can never reach another's data,
    not even through the read-only SQL tool. The local (stdio) setup uses VARAVU_DB or data/varavu.db."""
    if not shop or shop == "local":
        return os.getenv("VARAVU_DB", str(data_dir() / "varavu.db"))
    return str(data_dir() / "shops" / f"{shop}.db")


def db_path() -> str:
    return db_path_for(None)


def connect(path: str | Path | None = None, shop: str | None = None) -> sqlite3.Connection:
    """Open the database, creating the file and tables if needed.

    timeout: wait up to 30 s if another connection (e.g. the background scanner) is writing.
    WAL mode lets readers and one writer work at the same time.
    """
    path = str(path) if path else db_path_for(shop)
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row  # rows behave like dicts: row["total"]
    conn.execute("PRAGMA foreign_keys = ON")
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    return conn
