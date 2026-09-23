-- SQLite Audit Database Schema for Indian Stock Multi-Agent Dashboard
-- Created automatically on first run as audit.db

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    mode TEXT NOT NULL,                  -- 'live' or 'demo'
    engine TEXT NOT NULL,                -- 'claude_code', 'anthropic', 'openai', 'deterministic'
    scanned_count INTEGER NOT NULL,      -- total stocks scanned in the universe
    shortlisted_count INTEGER NOT NULL,  -- total stocks analyzed
    buys_count INTEGER NOT NULL          -- total BUY signals triggered
);

CREATE TABLE IF NOT EXISTS verdicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT,
    cap_segment TEXT,                    -- 'Large Cap', 'Mid Cap', 'Small Cap'
    verdict TEXT NOT NULL,               -- 'BUY', 'WATCH', 'AVOID'
    confidence INTEGER NOT NULL,         -- 1 to 10
    winner TEXT NOT NULL,                -- 'Bull' or 'Bear'
    live_price REAL,
    day_change_pct REAL,
    rationale TEXT,
    key_catalyst TEXT,
    telegram_sent INTEGER NOT NULL,      -- 1 if dispatched to Telegram, 0 otherwise
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);
