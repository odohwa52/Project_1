"""
Financial OS — Database Schema & Initialization
SQLite local file. Single source of truth for all five layers.
"""

import sqlite3
import os
from pathlib import Path

DB_PATH = Path(os.getenv("FINANCIAL_OS_DB", "./financial_os.db"))


SCHEMA = """
-- ─── CARDS ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cards (
    id           TEXT PRIMARY KEY,        -- 'A' | 'B' | 'C'
    label        TEXT NOT NULL,
    budget_min   INTEGER,                 -- nullable, for Card C floor
    budget_max   INTEGER,                 -- nullable, for Card B cap
    color        TEXT NOT NULL,
    description  TEXT
);

-- ─── EXPENSES ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS expenses (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    amount            INTEGER NOT NULL,    -- KRW, no decimals
    merchant          TEXT NOT NULL,
    card_id           TEXT NOT NULL REFERENCES cards(id),
    category          TEXT NOT NULL,
    note              TEXT,
    reimbursable      INTEGER DEFAULT 0,   -- bool
    reimbursed_by     TEXT,                -- comma-separated names
    reimbursed_amount INTEGER,
    reimbursed_date   TEXT,
    is_recurring      INTEGER DEFAULT 0,
    raw_input         TEXT,                -- original NL string for audit
    created_at        TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_expenses_card ON expenses(card_id);
CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(created_at);

-- ─── MERCHANT → CATEGORY MEMORY ────────────────────────────────────
CREATE TABLE IF NOT EXISTS merchant_categories (
    merchant_normalized TEXT PRIMARY KEY,
    category            TEXT NOT NULL,
    confidence          REAL DEFAULT 1.0,
    seen_count          INTEGER DEFAULT 1,
    last_seen           TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ─── REIMBURSEMENTS ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS reimbursements (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    person_name        TEXT NOT NULL,
    amount_owed        INTEGER NOT NULL,
    amount_paid        INTEGER DEFAULT 0,
    related_expense_id INTEGER REFERENCES expenses(id),
    status             TEXT DEFAULT 'pending',  -- pending | settled | partial
    note               TEXT,
    created_at         TEXT DEFAULT CURRENT_TIMESTAMP,
    settled_at         TEXT
);
CREATE INDEX IF NOT EXISTS idx_reimb_person ON reimbursements(person_name);
CREATE INDEX IF NOT EXISTS idx_reimb_status ON reimbursements(status);

-- ─── CLASSES (academic) ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS classes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    code       TEXT,
    semester   TEXT NOT NULL,            -- '2026-1' | '2026-2'
    color      TEXT DEFAULT '#E8450A',
    archived   INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ─── TODOS ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS todos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    content        TEXT NOT NULL,
    type           TEXT NOT NULL,        -- academic | social | personal
    class_id       INTEGER REFERENCES classes(id),
    due_date       TEXT,                 -- ISO date
    due_time       TEXT,                 -- HH:MM
    priority       TEXT DEFAULT 'normal',-- low | normal | high
    repeat_pattern TEXT,                 -- daily | weekly:mon,wed | monthly:15
    completed      INTEGER DEFAULT 0,
    completed_at   TEXT,
    archived       INTEGER DEFAULT 0,
    created_at     TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_todos_type ON todos(type);
CREATE INDEX IF NOT EXISTS idx_todos_due  ON todos(due_date);
CREATE INDEX IF NOT EXISTS idx_todos_done ON todos(completed);

-- ─── FRIENDS ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS friends (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    notes      TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ─── SOCIAL PLANS ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS social_plans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    friend_ids  TEXT NOT NULL,           -- JSON array of friend ids
    location    TEXT,
    plan_date   TEXT NOT NULL,
    plan_time   TEXT,
    notes       TEXT,
    completed   INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ─── PORTFOLIO ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS portfolio_holdings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    quantity        REAL NOT NULL,
    cost_basis      REAL NOT NULL,        -- per share
    current_price   REAL,
    last_updated    TEXT,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS price_history (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker    TEXT NOT NULL,
    price     REAL NOT NULL,
    captured  TEXT NOT NULL,
    UNIQUE(ticker, captured)
);
CREATE INDEX IF NOT EXISTS idx_price_ticker_time ON price_history(ticker, captured);

-- ─── AGENT MEMOS & DECISIONS ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS research_memos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    query           TEXT NOT NULL,
    content         TEXT NOT NULL,
    related_ticker  TEXT,
    obsidian_path   TEXT,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS committee_decisions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    query            TEXT NOT NULL,
    bull_argument    TEXT,
    bear_argument    TEXT,
    risk_assessment  TEXT,
    pm_verdict       TEXT,
    obsidian_path    TEXT,
    created_at       TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ─── BRIEFINGS ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS briefings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    briefing_date TEXT UNIQUE NOT NULL,
    content_json TEXT NOT NULL,
    created_at   TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ─── SETTINGS (key/value) ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


SEED_DATA = [
    # Cards
    ("INSERT OR IGNORE INTO cards VALUES (?, ?, ?, ?, ?, ?)",
     ("A", "Group / Reimbursable", None, None, "#1E3A5F",
      "Pays for the group, gets reimbursed back")),
    ("INSERT OR IGNORE INTO cards VALUES (?, ?, ?, ?, ?, ?)",
     ("B", "Daily Use", None, 300_000, "#E8450A",
      "₩300,000 monthly cap")),
    ("INSERT OR IGNORE INTO cards VALUES (?, ?, ?, ?, ?, ?)",
     ("C", "Larger Purchases", 500_000, None, "#F59E0B",
      "₩500,000 minimum spend per transaction")),
    # Default holdings — TIGER S&P 500 (KR ETF)
    ("""INSERT OR IGNORE INTO portfolio_holdings 
        (ticker, name, quantity, cost_basis, current_price, last_updated) 
        VALUES (?, ?, ?, ?, ?, datetime('now'))""",
     ("360750.KS", "TIGER S&P 500", 42, 17_400, 19_280)),
    # Default settings
    ("INSERT OR IGNORE INTO settings VALUES (?, ?)",
     ("obsidian_vault_path", "")),
    ("INSERT OR IGNORE INTO settings VALUES (?, ?)",
     ("briefing_time", "07:00")),
    ("INSERT OR IGNORE INTO settings VALUES (?, ?)",
     ("current_semester", "2026-1")),
]


def get_connection() -> sqlite3.Connection:
    """Returns a connection with row factory set to dict-like rows."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create all tables and seed initial data."""
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        for stmt, params in SEED_DATA:
            conn.execute(stmt, params)
        conn.commit()
        print(f"✓ Database initialized at {DB_PATH.resolve()}")
    finally:
        conn.close()


def reset_db() -> None:
    """Wipe DB. Useful for demo prep."""
    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"✓ Removed {DB_PATH}")
    init_db()


if __name__ == "__main__":
    import sys
    if "--reset" in sys.argv:
        reset_db()
    else:
        init_db()
