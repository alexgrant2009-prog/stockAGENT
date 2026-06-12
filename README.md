# marketscout

A Python CLI that analyzes the stock market with [yfinance](https://pypi.org/project/yfinance/)
and produces trade and investment ideas with full accountability: every
recommendation is stored append-only in SQLite (it can never be edited or
deleted) and graded against SPY in the scorecard. A paper portfolio lets you
act on ideas with a virtual $10,000 at real prices.

**marketscout never connects to a brokerage and never places real orders.**
It also never fabricates data — when yfinance can't supply a field, the
output says `data unavailable` and the idea's confidence rating is lowered.

## Setup

Requires Python 3.12 (3.11+ works).

```sh
pip install .
```

Data (SQLite database + watchlist config) lives in `~/.marketscout/`
(override with the `MARKETSCOUT_HOME` environment variable). The watchlist
is seeded with: MSFT, AAPL, GOOGL, NVDA, COST, V, MA, BRK-B, SPGI, WM.

## Commands

### `marketscout scan`

Market briefing: index direction (SPY/QQQ/DIA over 1d/1mo/3mo), sector
rotation across the 11 sector ETFs, momentum signals on the watchlist
(50/200-day moving averages, golden crosses, volume ≥ 2x the 30-day
average), and recent headlines.

```sh
$ marketscout scan
MARKETSCOUT BRIEFING — 2026-06-12

MARKET DIRECTION
  SPY   S&P 500      1d     +0.31%   1mo     +2.10%   3mo     +5.42%
  ...
```

### `marketscout recommend`

Combines scan signals with fundamentals (revenue growth, margins, free
cash flow, valuation vs. the stock's own multi-year average P/E) and
prints up to 5 ranked ideas — each with ticker, action (buy/watch/avoid),
time horizon, a data-grounded thesis, the main invalidating risk, and a
confidence level. Every idea is saved to the database with date and price.

```sh
$ marketscout recommend
1. MSFT — BUY (long-term hold, confidence: high)
   Price: $512.40
   Thesis: MSFT trades above its 50- and 200-day moving averages; ...
   Risk: a close below the 50-day moving average ($498.12) would break the setup
...
Analysis, not financial advice. Verify before acting.
```

### `marketscout scorecard`

The core feature: every past recommendation with price then, price now,
percent return, and SPY's return over the same window. Win rate vs SPY is
shown first. Recommendations are immutable — SQLite triggers reject any
UPDATE or DELETE.

```sh
$ marketscout scorecard
WIN RATE vs SPY: 3/5 (60%)

date         ticker  action       then        now    return       SPY  beat?
...
```

### `marketscout paper buy/sell TICKER QTY` and `marketscout paper status`

Paper portfolio starting from a virtual $10,000, filled at real current
prices. `status` leads with total return vs SPY.

```sh
$ marketscout paper buy NVDA 10
Bought 10 NVDA @ $187.32 (paper). Cash: $8,126.80

$ marketscout paper status
PAPER PORTFOLIO — total return +1.84% vs SPY +0.92% (since 2026-06-12)
...
```

### `marketscout watchlist add/remove/list TICKER`

```sh
$ marketscout watchlist add AMZN
Added AMZN.
$ marketscout watchlist list
MSFT
AAPL
...
```
