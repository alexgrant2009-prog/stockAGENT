"""Market data via yfinance, plus signal computation.

Every fetch returns None (or an empty container) on failure so callers
can render "data unavailable" instead of fabricating values.
"""

import pandas as pd
import yfinance as yf

INDEXES = {"SPY": "S&P 500", "QQQ": "Nasdaq 100", "DIA": "Dow Jones"}

SECTORS = {
    "XLK": "Technology", "XLF": "Financials", "XLE": "Energy",
    "XLV": "Health Care", "XLI": "Industrials", "XLP": "Cons. Staples",
    "XLY": "Cons. Discretionary", "XLU": "Utilities", "XLB": "Materials",
    "XLRE": "Real Estate", "XLC": "Communications",
}

# Trading-day window lengths
DAYS_1MO = 21
DAYS_3MO = 63


def fetch_history(ticker: str, period: str = "1y") -> pd.DataFrame | None:
    """Daily OHLCV history, or None on failure."""
    try:
        hist = yf.Ticker(ticker).history(period=period, auto_adjust=True)
    except Exception:
        return None
    if hist is None or hist.empty:
        return None
    return hist


def last_price(ticker: str) -> float | None:
    hist = fetch_history(ticker, period="5d")
    if hist is None:
        return None
    return float(hist["Close"].iloc[-1])


def price_on_or_after(ticker: str, date: str) -> float | None:
    """First close on or after `date` (YYYY-MM-DD...)."""
    try:
        hist = yf.Ticker(ticker).history(start=date[:10], auto_adjust=True)
    except Exception:
        return None
    if hist is None or hist.empty:
        return None
    return float(hist["Close"].iloc[0])


def window_returns(close: pd.Series) -> dict[str, float | None]:
    """Percent returns over 1 day, 1 month, 3 months of trading days."""
    out: dict[str, float | None] = {}
    for label, days in (("1d", 1), ("1mo", DAYS_1MO), ("3mo", DAYS_3MO)):
        if len(close) > days:
            out[label] = float(close.iloc[-1] / close.iloc[-1 - days] - 1) * 100
        else:
            out[label] = None
    return out


def momentum_signals(hist: pd.DataFrame) -> dict:
    """Moving-average, golden-cross, and volume signals from daily history."""
    close, volume = hist["Close"], hist["Volume"]
    sig: dict = {"price": float(close.iloc[-1]),
                 "above_50": None, "above_200": None,
                 "golden_cross": False, "volume_ratio": None,
                 "ma50": None, "ma200": None}
    if len(close) >= 50:
        ma50 = close.rolling(50).mean()
        sig["ma50"] = float(ma50.iloc[-1])
        sig["above_50"] = sig["price"] > sig["ma50"]
    if len(close) >= 200:
        ma200 = close.rolling(200).mean()
        sig["ma200"] = float(ma200.iloc[-1])
        sig["above_200"] = sig["price"] > sig["ma200"]
        # Golden cross: 50-day MA crossed above the 200-day MA within
        # the last 10 sessions.
        spread = (close.rolling(50).mean() - ma200).dropna()
        if len(spread) > 10:
            recent = spread.iloc[-10:]
            sig["golden_cross"] = bool(
                spread.iloc[-1] > 0 and (recent <= 0).any())
    if len(volume) > 30:
        avg30 = float(volume.iloc[-31:-1].mean())
        if avg30 > 0:
            sig["volume_ratio"] = float(volume.iloc[-1]) / avg30
    return sig


def fetch_news(ticker: str, limit: int = 3) -> list[dict]:
    """Recent headlines: [{title, publisher}]. Empty list on failure."""
    try:
        items = yf.Ticker(ticker).news or []
    except Exception:
        return []
    headlines = []
    for item in items[:limit]:
        content = item.get("content", item)
        title = content.get("title")
        if not title:
            continue
        provider = content.get("provider") or {}
        publisher = (provider.get("displayName")
                     or item.get("publisher") or "unknown source")
        headlines.append({"title": title, "publisher": publisher})
    return headlines


def fetch_fundamentals(ticker: str) -> dict:
    """Revenue growth, margins, FCF, trailing P/E. Missing fields are None."""
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        info = {}
    out = {}
    for key, field in (("revenue_growth", "revenueGrowth"),
                       ("profit_margins", "profitMargins"),
                       ("free_cash_flow", "freeCashflow"),
                       ("trailing_pe", "trailingPE")):
        val = info.get(field)
        out[key] = float(val) if isinstance(val, (int, float)) else None
    return out


def avg_historical_pe(ticker: str, hist: pd.DataFrame | None) -> tuple[float | None, int]:
    """Average P/E over past fiscal years (up to ~5y of yfinance annual data).

    Computed as fiscal-year-end price / diluted EPS for each reported year.
    Returns (average, years used); (None, 0) when fewer than 2 years of
    data are available.
    """
    if hist is None or len(hist) < 2:
        return None, 0
    try:
        inc = yf.Ticker(ticker).income_stmt
        net_income = inc.loc["Net Income"]
        shares = inc.loc["Diluted Average Shares"]
    except Exception:
        return None, 0
    close = hist["Close"].copy()
    close.index = close.index.tz_localize(None)
    pes = []
    for year_end in net_income.index:
        ni, sh = net_income[year_end], shares[year_end]
        if pd.isna(ni) or pd.isna(sh) or not sh or ni <= 0:
            continue
        ts = pd.Timestamp(year_end)
        if ts < close.index[0]:
            continue
        price = close.asof(ts)
        if pd.isna(price):
            continue
        pes.append(float(price) / (float(ni) / float(sh)))
    if len(pes) < 2:
        return None, 0
    return sum(pes) / len(pes), len(pes)
