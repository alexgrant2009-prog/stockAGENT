"""marketscout CLI: scan, recommend, scorecard, paper, watchlist.

Analysis tool only — never connects to a brokerage or places orders.
"""

import datetime

import click

from . import config, data, db

DISCLAIMER = "Analysis, not financial advice. Verify before acting."
UNAVAILABLE = "data unavailable"


def _pct(value: float | None, signed: bool = True) -> str:
    if value is None:
        return UNAVAILABLE
    return f"{value:+.2f}%" if signed else f"{value:.2f}%"


def _money(value: float | None) -> str:
    return UNAVAILABLE if value is None else f"${value:,.2f}"


@click.group()
def main():
    """Market analysis and tracked recommendations. No real trading."""


# ---------------------------------------------------------------- scan

@main.command()
def scan():
    """Market briefing: direction, sector rotation, momentum, headlines."""
    today = datetime.date.today().isoformat()
    click.echo(f"MARKETSCOUT BRIEFING — {today}\n")

    click.echo("MARKET DIRECTION")
    spy_returns = None
    for ticker, name in data.INDEXES.items():
        hist = data.fetch_history(ticker, period="6mo")
        rets = data.window_returns(hist["Close"]) if hist is not None else \
            {"1d": None, "1mo": None, "3mo": None}
        if ticker == "SPY":
            spy_returns = rets
        click.echo(f"  {ticker:<5} {name:<12} 1d {_pct(rets['1d']):>10}"
                   f"   1mo {_pct(rets['1mo']):>10}"
                   f"   3mo {_pct(rets['3mo']):>10}")
    if spy_returns and all(v is not None for v in spy_returns.values()):
        positive = sum(1 for v in spy_returns.values() if v > 0)
        direction = ("uptrend" if positive == 3
                     else "downtrend" if positive == 0 else "mixed")
    else:
        direction = UNAVAILABLE
    click.echo(f"  Direction (SPY across 1d/1mo/3mo): {direction}\n")

    click.echo("SECTOR ROTATION")
    sector_rets = {}
    for ticker, name in data.SECTORS.items():
        hist = data.fetch_history(ticker, period="6mo")
        rets = data.window_returns(hist["Close"]) if hist is not None else \
            {"1d": None, "1mo": None, "3mo": None}
        sector_rets[ticker] = rets
        click.echo(f"  {ticker:<5} {name:<20} 1d {_pct(rets['1d']):>10}"
                   f"   1mo {_pct(rets['1mo']):>10}"
                   f"   3mo {_pct(rets['3mo']):>10}")
    for window in ("1mo", "3mo"):
        ranked = sorted(((t, r[window]) for t, r in sector_rets.items()
                         if r[window] is not None),
                        key=lambda x: x[1], reverse=True)
        if ranked:
            lead = ", ".join(f"{t} {_pct(r)}" for t, r in ranked[:3])
            lag = ", ".join(f"{t} {_pct(r)}" for t, r in ranked[-3:])
            click.echo(f"  Leading {window}: {lead}")
            click.echo(f"  Lagging {window}: {lag}")
        else:
            click.echo(f"  Sector ranking {window}: {UNAVAILABLE}")

    watchlist = config.load_watchlist()
    click.echo("\nMOMENTUM SIGNALS (watchlist)")
    any_signal = False
    for ticker in watchlist:
        hist = data.fetch_history(ticker, period="2y")
        if hist is None:
            click.echo(f"  {ticker:<6} {UNAVAILABLE}")
            continue
        sig = data.momentum_signals(hist)
        notes = []
        if sig["above_50"] and sig["above_200"]:
            notes.append("above 50d & 200d MA")
        elif sig["above_50"]:
            notes.append("above 50d MA")
        elif sig["above_200"]:
            notes.append("above 200d MA")
        if sig["golden_cross"]:
            notes.append("golden cross (50d crossed above 200d)")
        if sig["volume_ratio"] is not None and sig["volume_ratio"] >= 2:
            notes.append(f"volume {sig['volume_ratio']:.1f}x 30-day avg")
        if notes:
            any_signal = True
            click.echo(f"  {ticker:<6} {'; '.join(notes)}")
    if not any_signal:
        click.echo("  No momentum signals flagged.")

    click.echo("\nHEADLINES (watchlist)")
    any_news = False
    for ticker in watchlist:
        for item in data.fetch_news(ticker, limit=2):
            any_news = True
            click.echo(f"  {ticker}: {item['title']} ({item['publisher']})")
    if not any_news:
        click.echo(f"  {UNAVAILABLE}")


# ----------------------------------------------------------- recommend

def _analyze_ticker(ticker: str) -> dict:
    """Score one watchlist ticker from momentum + fundamentals."""
    hist = data.fetch_history(ticker, period="5y")
    fund = data.fetch_fundamentals(ticker)
    avg_pe, pe_years = data.avg_historical_pe(ticker, hist)
    sig = data.momentum_signals(hist) if hist is not None else None
    rets = data.window_returns(hist["Close"]) if hist is not None else {"3mo": None}

    score, momentum_pts, fundamental_pts, missing = 0, 0, 0, 0
    facts, risks = [], []

    if sig is None:
        missing += 1
        facts.append("price history is unavailable")
    else:
        for key, label in (("above_50", "50-day"), ("above_200", "200-day")):
            if sig[key] is None:
                missing += 1
            elif sig[key]:
                momentum_pts += 1
            else:
                momentum_pts -= 1
        if sig["golden_cross"]:
            momentum_pts += 1
        if sig["volume_ratio"] is not None and sig["volume_ratio"] >= 2:
            momentum_pts += 1
        if sig["above_50"] and sig["above_200"]:
            facts.append("trades above its 50- and 200-day moving averages")
        elif sig["above_50"] is False and sig["above_200"] is False:
            facts.append("trades below both its 50- and 200-day moving averages")
        if sig["golden_cross"]:
            facts.append("printed a golden cross in the last 10 sessions")
        if sig["volume_ratio"] is not None and sig["volume_ratio"] >= 2:
            facts.append(f"volume is {sig['volume_ratio']:.1f}x its 30-day average")

    if rets.get("3mo") is not None:
        momentum_pts += 1 if rets["3mo"] > 0 else -1
        facts.append(f"3-month return is {_pct(rets['3mo'])}")
    else:
        missing += 1

    if fund["revenue_growth"] is None:
        missing += 1
        facts.append(f"revenue growth: {UNAVAILABLE}")
    else:
        fundamental_pts += 1 if fund["revenue_growth"] > 0.05 else \
            (-1 if fund["revenue_growth"] < 0 else 0)
        facts.append(f"revenue growth is {fund['revenue_growth'] * 100:.1f}% y/y")

    if fund["profit_margins"] is None:
        missing += 1
    else:
        fundamental_pts += 1 if fund["profit_margins"] > 0.15 else 0
        facts.append(f"profit margin is {fund['profit_margins'] * 100:.1f}%")

    if fund["free_cash_flow"] is None:
        missing += 1
        facts.append(f"free cash flow: {UNAVAILABLE}")
    else:
        fundamental_pts += 1 if fund["free_cash_flow"] > 0 else -1
        facts.append(f"free cash flow is {_money(fund['free_cash_flow'])}")

    if fund["trailing_pe"] is None or avg_pe is None:
        missing += 1
        facts.append(f"valuation vs multi-year average: {UNAVAILABLE}")
    else:
        ratio = fund["trailing_pe"] / avg_pe
        if ratio < 0.95:
            fundamental_pts += 1
            facts.append(f"trailing P/E of {fund['trailing_pe']:.1f} is below "
                         f"its {pe_years}-year average of {avg_pe:.1f}")
        elif ratio > 1.25:
            fundamental_pts -= 1
            facts.append(f"trailing P/E of {fund['trailing_pe']:.1f} is well above "
                         f"its {pe_years}-year average of {avg_pe:.1f}")
            risks.append(f"the stock trades at {ratio:.2f}x its {pe_years}-year "
                         "average multiple; multiple compression would sink the thesis")
        else:
            facts.append(f"trailing P/E of {fund['trailing_pe']:.1f} is near "
                         f"its {pe_years}-year average of {avg_pe:.1f}")

    score = momentum_pts + fundamental_pts

    if score >= 3 and missing <= 2:
        action = "buy"
    elif score <= -2:
        action = "avoid"
    else:
        action = "watch"
    horizon = ("long-term hold" if fundamental_pts >= 2
               else "short-term trade")

    if action == "avoid":
        risks.append("a recovery above the 50- and 200-day moving averages "
                     "would invalidate the bearish setup")
    elif sig is not None and sig["ma50"] is not None:
        risks.append(f"a close below the 50-day moving average "
                     f"(${sig['ma50']:,.2f}) would break the setup")
    if missing:
        risks.append(f"{missing} data field(s) were unavailable, so the "
                     "analysis is incomplete")
    risk = risks[0] if risks else ("weak signals on both momentum and "
                                   "fundamentals leave no clear edge")

    confidence = ("high" if abs(score) >= 5 else
                  "medium" if abs(score) >= 3 else "low")
    # Missing data always lowers confidence.
    if missing >= 3:
        confidence = "low"
    elif missing >= 1 and confidence == "high":
        confidence = "medium"

    thesis = (f"{ticker} {'; '.join(facts[:3])}. "
              f"{' '.join(f[0].upper() + f[1:] + '.' for f in facts[3:6])}").strip()

    return {"ticker": ticker, "action": action, "horizon": horizon,
            "thesis": thesis, "risk": risk, "confidence": confidence,
            "score": score, "missing": missing,
            "price": sig["price"] if sig else None}


@main.command()
def recommend():
    """Generate up to 5 ranked ideas and save them to the database."""
    watchlist = config.load_watchlist()
    click.echo(f"Analyzing {len(watchlist)} watchlist tickers...\n")
    ideas = [_analyze_ticker(t) for t in watchlist]
    # Strongest convictions first, bullish or bearish.
    ideas.sort(key=lambda i: abs(i["score"]), reverse=True)
    ideas = ideas[:5]

    spy_price = data.last_price("SPY")
    conn = db.connect()
    for n, idea in enumerate(ideas, 1):
        click.echo(f"{n}. {idea['ticker']} — {idea['action'].upper()} "
                   f"({idea['horizon']}, confidence: {idea['confidence']})")
        click.echo(f"   Price: {_money(idea['price'])}")
        click.echo(f"   Thesis: {idea['thesis']}")
        click.echo(f"   Risk: {idea['risk']}")
        db.save_recommendation(
            conn, idea["ticker"], idea["action"], idea["horizon"],
            idea["thesis"], idea["risk"], idea["confidence"],
            idea["price"], spy_price)
        click.echo()
    conn.close()
    click.echo(f"Saved {len(ideas)} recommendation(s) to the scorecard "
               "database (append-only).\n")
    click.echo(DISCLAIMER)


# ----------------------------------------------------------- scorecard

@main.command()
def scorecard():
    """Accountability report: every past call vs SPY over the same window."""
    conn = db.connect()
    recs = db.list_recommendations(conn)
    conn.close()
    if not recs:
        click.echo("No recommendations recorded yet. Run "
                   "`marketscout recommend` first.")
        return

    spy_now = data.last_price("SPY")
    rows, wins, scored = [], 0, 0
    for rec in recs:
        price_now = data.last_price(rec["ticker"])
        ret = (None if rec["price"] is None or price_now is None
               else (price_now / rec["price"] - 1) * 100)
        spy_then = rec["spy_price"] or data.price_on_or_after(
            "SPY", rec["created_at"])
        spy_ret = (None if spy_then is None or spy_now is None
                   else (spy_now / spy_then - 1) * 100)
        win = None
        if ret is not None and spy_ret is not None:
            scored += 1
            # buy/watch win by beating SPY; avoid wins by lagging it.
            win = (ret < spy_ret) if rec["action"] == "avoid" else (ret > spy_ret)
            wins += win
        rows.append((rec, price_now, ret, spy_ret, win))

    if scored:
        click.echo(f"WIN RATE vs SPY: {wins}/{scored} "
                   f"({wins / scored * 100:.0f}%)\n")
    else:
        click.echo(f"WIN RATE vs SPY: {UNAVAILABLE}\n")
    header = (f"{'date':<12} {'ticker':<7} {'action':<6} {'then':>10} "
              f"{'now':>10} {'return':>9} {'SPY':>9} {'beat?':>6}")
    click.echo(header)
    click.echo("-" * len(header))
    for rec, price_now, ret, spy_ret, win in rows:
        click.echo(
            f"{rec['created_at'][:10]:<12} {rec['ticker']:<7} "
            f"{rec['action']:<6} "
            f"{_money(rec['price']):>10} {_money(price_now):>10} "
            f"{_pct(ret):>9} {_pct(spy_ret):>9} "
            f"{'—' if win is None else 'yes' if win else 'no':>6}")


# --------------------------------------------------------------- paper

@main.group()
def paper():
    """Paper portfolio: virtual $10,000, real prices, no real orders."""


def _paper_trade(side: str, ticker: str, qty: int):
    ticker = ticker.upper()
    price = data.last_price(ticker)
    if price is None:
        raise click.ClickException(
            f"{ticker}: price {UNAVAILABLE}; trade not recorded.")
    conn = db.connect()
    cash, shares, _ = db.paper_state(conn)
    if side == "buy" and qty * price > cash:
        conn.close()
        raise click.ClickException(
            f"Insufficient paper cash: need {_money(qty * price)}, "
            f"have {_money(cash)}.")
    if side == "sell" and qty > shares.get(ticker, 0):
        conn.close()
        raise click.ClickException(
            f"Cannot sell {qty} {ticker}: holding {shares.get(ticker, 0)}.")
    db.record_trade(conn, ticker, side, qty, price, data.last_price("SPY"))
    cash, _, _ = db.paper_state(conn)
    conn.close()
    verb = "Bought" if side == "buy" else "Sold"
    click.echo(f"{verb} {qty} {ticker} @ {_money(price)} (paper). "
               f"Cash: {_money(cash)}")


@paper.command()
@click.argument("ticker")
@click.argument("qty", type=click.IntRange(min=1))
def buy(ticker, qty):
    """Paper-buy QTY shares of TICKER at the current price."""
    _paper_trade("buy", ticker, qty)


@paper.command()
@click.argument("ticker")
@click.argument("qty", type=click.IntRange(min=1))
def sell(ticker, qty):
    """Paper-sell QTY shares of TICKER at the current price."""
    _paper_trade("sell", ticker, qty)


@paper.command()
def status():
    """Portfolio value and total return vs SPY."""
    conn = db.connect()
    cash, shares, cost = db.paper_state(conn)
    trades = db.list_trades(conn)
    conn.close()

    prices = {t: data.last_price(t) for t in shares}
    if any(p is None for p in prices.values()):
        total_ret = None
        missing = [t for t, p in prices.items() if p is None]
    else:
        value = cash + sum(shares[t] * prices[t] for t in shares)
        total_ret = (value / db.PAPER_STARTING_CASH - 1) * 100
        missing = []

    spy_ret = None
    if trades:
        spy_then, spy_now = trades[0]["spy_price"], data.last_price("SPY")
        if spy_then and spy_now:
            spy_ret = (spy_now / spy_then - 1) * 100

    if trades:
        since = trades[0]["created_at"][:10]
        click.echo(f"PAPER PORTFOLIO — total return {_pct(total_ret)} "
                   f"vs SPY {_pct(spy_ret)} (since {since})\n")
    else:
        click.echo("PAPER PORTFOLIO — no trades yet\n")
    click.echo(f"Cash: {_money(cash)}")
    for t in sorted(shares):
        p = prices[t]
        avg = cost[t] / shares[t] if shares[t] else None
        pos_val = _money(shares[t] * p) if p is not None else UNAVAILABLE
        pnl = _pct((p / avg - 1) * 100) if p is not None and avg else UNAVAILABLE
        click.echo(f"  {t:<6} {shares[t]:>6} sh  avg {_money(avg)}  "
                   f"now {_money(p)}  value {pos_val}  p/l {pnl}")
    if total_ret is not None:
        value = cash + sum(shares[t] * prices[t] for t in shares)
        click.echo(f"Total value: {_money(value)}")
    elif missing:
        click.echo(f"Total value: {UNAVAILABLE} (no price for "
                   f"{', '.join(missing)})")


# ----------------------------------------------------------- watchlist

@main.group()
def watchlist():
    """Manage the watchlist config file."""


@watchlist.command("add")
@click.argument("ticker")
def watchlist_add(ticker):
    """Add TICKER to the watchlist."""
    if config.add_ticker(ticker):
        click.echo(f"Added {ticker.upper()}.")
    else:
        click.echo(f"{ticker.upper()} is already on the watchlist.")


@watchlist.command("remove")
@click.argument("ticker")
def watchlist_remove(ticker):
    """Remove TICKER from the watchlist."""
    if config.remove_ticker(ticker):
        click.echo(f"Removed {ticker.upper()}.")
    else:
        click.echo(f"{ticker.upper()} is not on the watchlist.")


@watchlist.command("list")
def watchlist_list():
    """Show the watchlist."""
    for ticker in config.load_watchlist():
        click.echo(ticker)


if __name__ == "__main__":
    main()
