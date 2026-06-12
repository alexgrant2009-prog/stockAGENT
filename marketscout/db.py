"""SQLite storage for recommendations and the paper portfolio.

Recommendations are append-only: SQLite triggers abort any UPDATE or
DELETE so past calls can never be edited or erased.
"""

import sqlite3
from datetime import datetime, timezone

from . import config

PAPER_STARTING_CASH = 10_000.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,
    horizon TEXT NOT NULL,
    thesis TEXT NOT NULL,
    risk TEXT NOT NULL,
    confidence TEXT NOT NULL,
    price REAL,
    spy_price REAL
);
CREATE TRIGGER IF NOT EXISTS recommendations_no_update
BEFORE UPDATE ON recommendations
BEGIN SELECT RAISE(ABORT, 'recommendations are immutable'); END;
CREATE TRIGGER IF NOT EXISTS recommendations_no_delete
BEFORE DELETE ON recommendations
BEGIN SELECT RAISE(ABORT, 'recommendations are immutable'); END;

CREATE TABLE IF NOT EXISTS paper_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    qty INTEGER NOT NULL CHECK (qty > 0),
    price REAL NOT NULL,
    spy_price REAL
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.home_dir() / "marketscout.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def save_recommendation(conn, ticker, action, horizon, thesis, risk,
                        confidence, price, spy_price) -> None:
    conn.execute(
        "INSERT INTO recommendations (created_at, ticker, action, horizon,"
        " thesis, risk, confidence, price, spy_price)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (_now(), ticker, action, horizon, thesis, risk, confidence,
         price, spy_price),
    )
    conn.commit()


def list_recommendations(conn) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM recommendations ORDER BY id").fetchall()


def record_trade(conn, ticker, side, qty, price, spy_price) -> None:
    conn.execute(
        "INSERT INTO paper_trades (created_at, ticker, side, qty, price,"
        " spy_price) VALUES (?, ?, ?, ?, ?, ?)",
        (_now(), ticker, side, qty, price, spy_price),
    )
    conn.commit()


def list_trades(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM paper_trades ORDER BY id").fetchall()


def paper_state(conn) -> tuple[float, dict[str, int], dict[str, float]]:
    """Return (cash, {ticker: shares held}, {ticker: total cost of open lots}).

    Cost basis uses average cost: sells reduce cost proportionally.
    """
    cash = PAPER_STARTING_CASH
    shares: dict[str, int] = {}
    cost: dict[str, float] = {}
    for t in list_trades(conn):
        ticker, qty, price = t["ticker"], t["qty"], t["price"]
        if t["side"] == "buy":
            cash -= qty * price
            shares[ticker] = shares.get(ticker, 0) + qty
            cost[ticker] = cost.get(ticker, 0.0) + qty * price
        else:
            cash += qty * price
            held = shares.get(ticker, 0)
            if held:
                cost[ticker] = cost.get(ticker, 0.0) * (1 - qty / held)
            shares[ticker] = held - qty
        if shares.get(ticker) == 0:
            shares.pop(ticker, None)
            cost.pop(ticker, None)
    return cash, shares, cost
