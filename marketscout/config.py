"""Watchlist config file management."""

import json
import os
from pathlib import Path

SEED_WATCHLIST = [
    "MSFT", "AAPL", "GOOGL", "NVDA", "COST",
    "V", "MA", "BRK-B", "SPGI", "WM",
]


def home_dir() -> Path:
    d = Path(os.environ.get("MARKETSCOUT_HOME", "~/.marketscout")).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _watchlist_path() -> Path:
    return home_dir() / "watchlist.json"


def load_watchlist() -> list[str]:
    path = _watchlist_path()
    if not path.exists():
        save_watchlist(SEED_WATCHLIST)
        return list(SEED_WATCHLIST)
    with open(path) as f:
        return json.load(f)


def save_watchlist(tickers: list[str]) -> None:
    with open(_watchlist_path(), "w") as f:
        json.dump(tickers, f, indent=2)


def add_ticker(ticker: str) -> bool:
    """Add a ticker. Returns False if already present."""
    ticker = ticker.upper()
    tickers = load_watchlist()
    if ticker in tickers:
        return False
    tickers.append(ticker)
    save_watchlist(tickers)
    return True


def remove_ticker(ticker: str) -> bool:
    """Remove a ticker. Returns False if not present."""
    ticker = ticker.upper()
    tickers = load_watchlist()
    if ticker not in tickers:
        return False
    tickers.remove(ticker)
    save_watchlist(tickers)
    return True
