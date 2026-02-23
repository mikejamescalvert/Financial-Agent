# Architecture

## System Overview

Financial Agent is an AI-powered multi-asset trading system built as a set of GitHub Actions workflows. It uses Alpaca for brokerage, Claude for AI analysis, and a multi-layered risk management framework.

### Agents & Schedules

| Agent | Schedule | Entry Point | Trigger |
|-------|----------|-------------|---------|
| Trading Agent | Every 30 min 24/7 | `main.py` | Cron + manual |
| Portfolio Review | Daily 9 PM UTC | `review_main.py` | Cron + manual |
| Watchlist Review | Daily 1 AM UTC | `watchlist_main.py` | Cron + manual |
| Daily Screener | Weekdays 1 PM UTC | `screener_main.py` | Cron + manual |
| Performance Report | Weekly Saturday 12 PM UTC | `performance_main.py` | Cron + manual |

All agents:
- Run only on the `main` branch
- Cache persistent state (`.data/` directory) between runs via GitHub Actions cache
- Use the `trading` environment with deployment protection
- Load configuration from GitHub Secrets and Variables

## Trading Agent Execution Flow

`main()` runs one complete trading cycle:

1. `AlpacaBroker.is_market_open()` — determines if stocks are included (crypto always trades)
2. `AlpacaBroker.get_portfolio_snapshot()` — fetch account + positions, enrich with sector data
3. `EquityTracker.record()` — track equity for drawdown detection
4. `_fetch_enrichment()` — fetch fundamentals, earnings, news, macro, crypto market data
5. **Crypto pipeline** (always): historical bars → `TechnicalAnalyzer.compute_indicators()`
6. **Stock pipeline** (market open): historical bars → indicators → `compute_relative_strength()`
7. `StrategyEngine.check_trailing_stops()` — generate sell signals for positions hitting ATR-based stops
8. `AIAnalyzer.analyze()` — sends portfolio + technicals + enrichment + theses + equity history to Claude
9. `StrategyEngine.generate_orders()` — converts signals to sized orders with risk management
10. `AlpacaBroker.submit_order()` — executes market or limit orders (or dry-run logs)
11. `_record_trade()` — persist trade thesis and journal entry
12. `_write_step_summary()` — rich markdown to `GITHUB_STEP_SUMMARY`

## Other Agents

### Portfolio Review (`review_main.py`)

Sends the current portfolio state + technicals to Claude, which returns:
- **Portfolio grade** (A-F) based on diversification, risk, and performance
- **3-5 actionable suggestions** with priority, category (risk/performance/strategy/config/watchlist), and detailed reasoning

Results are posted as GitHub issues for tracking.

### Watchlist Review (`watchlist_main.py`)

Screens the full 110-stock + 12-crypto universe:
1. Fetches historical bars and computes technical indicators for all universe symbols
2. Claude ranks candidates as buy/hold/sell with reasoning
3. Updates `TRADING_WATCHLIST` and `TRADING_CRYPTO_WATCHLIST` GitHub Variables programmatically
4. Creates an audit issue documenting the changes

### Daily Screener (`screener_main.py`)

Pre-market scan across the full universe looking for:
- Breakout candidates (price near resistance, increasing volume)
- Unusual volume spikes
- Big movers (significant gap up/down)
- Sector momentum shifts

Results posted as GitHub issues for review before market open.

### Performance Report (`performance_main.py`)

Weekly analysis computing:
- Sharpe ratio (30-day rolling)
- Sortino ratio (downside-only volatility)
- Win rate and profit factor
- Max drawdown (90-day lookback)
- Trade journal summary

Posted as a GitHub issue with risk-adjusted metrics.

## Data Flow

```
Portfolio Snapshot
    ├── Sector enrichment (sector_map)
    ├── Equity tracking (persistence)
    │
    ├── Market Enrichment (data/)
    │   ├── Fundamentals (FMP API)        — EPS, P/E, revenue growth, margins, FCF
    │   ├── Earnings calendar (FMP API)   — upcoming dates for buffer logic
    │   ├── News sentiment (Finnhub API)  — per-symbol sentiment scores
    │   ├── Macro context (free)          — VIX, SPY trend, 10Y yield, market regime
    │   └── Crypto context (CoinGecko)    — BTC dominance, Fear & Greed index
    │
    ├── Technical Analysis (strategy/technical.py)
    │   ├── Trend: SMA (20/50/100/200), EMA, MACD
    │   ├── Momentum: RSI, Stochastic K/D
    │   ├── Volatility: Bollinger Bands, ATR (raw + % of price)
    │   ├── Volume: OBV
    │   ├── Multi-timeframe: 200-day SMA, weekly trend proxy, weekly SMA-10
    │   ├── Relative strength vs SPY (absolute + percentile rank)
    │   └── Support/resistance levels, 52-week high/low
    │
    ├── Risk Checks (risk/)
    │   ├── Drawdown circuit breaker → size multiplier or halt
    │   ├── Trailing stops → sell signals for positions hitting ATR stops
    │   └── Sector exposure → block concentrated buys
    │
    └── AI Analysis (Claude)
        ├── Receives ALL above data in structured prompt
        ├── Multi-factor framework: macro → sector → multi-timeframe → fundamentals → news
        ├── Reviews active trade theses (persistence)
        └── Outputs TradeSignal[] with confidence scores + scale_action
            │
            └── Strategy Engine
                ├── Volatility-adjusted sizing (ATR-based, risk budget %)
                ├── Position scaling (1/3 increments)
                ├── Earnings buffer check
                ├── Sector concentration check
                ├── Limit order generation with slippage tolerance
                └── TradeOrder[] → Broker execution → Trade journal
```

## Package Structure

```
src/financial_agent/
├── main.py                    # Trading agent entry point
├── review_main.py             # Portfolio review agent
├── watchlist_main.py          # Watchlist review agent
├── screener_main.py           # Daily pre-market screener
├── performance_main.py        # Weekly performance report
├── config.py                  # 5 config classes, 40+ env vars
│
├── broker/
│   └── alpaca_client.py       # Alpaca SDK wrapper (market + limit orders, stocks + crypto)
│
├── analysis/
│   └── ai_analyzer.py         # Claude integration with multi-factor system prompt
│
├── strategy/
│   ├── engine.py              # Order generation with risk management:
│   │                          #   volatility sizing, sector limits, drawdown,
│   │                          #   trailing stops, earnings buffer, limit orders,
│   │                          #   position scaling, daily trade limits
│   └── technical.py           # 20+ indicators: SMA/EMA/MACD/RSI/BB/ATR/OBV,
│                              #   200-day SMA, support/resistance, relative strength,
│                              #   multi-timeframe, weekly trend proxy
│
├── portfolio/
│   └── models.py              # Position, PortfolioSnapshot, TradeSignal, TradeOrder,
│                              #   OrderType, PositionStage, AssetClass, SignalType
│
├── data/                      # Market data enrichment (all optional)
│   ├── models.py              # FundamentalData, EarningsEvent, NewsSentiment,
│   │                          #   MacroContext, CryptoMarketContext, MarketEnrichment
│   ├── fundamentals.py        # Financial Modeling Prep API
│   ├── earnings.py            # Earnings calendar
│   ├── news.py                # Finnhub news/sentiment
│   ├── macro.py               # VIX, SPY trend, economic calendar (free)
│   ├── crypto_market.py       # BTC dominance, Fear & Greed (CoinGecko, free)
│   └── sector_map.py          # Static GICS sector mapping for 100+ symbols
│
├── risk/                      # Risk management modules
│   ├── drawdown.py            # Tiered circuit breaker (5 levels)
│   ├── correlation.py         # Sector exposure tracking and limits
│   └── volatility.py          # ATR-based volatility-adjusted sizing
│
├── persistence/               # Cross-session state (JSON files, GitHub Actions cache)
│   ├── thesis_store.py        # Trade thesis logging and lifecycle management
│   └── equity_tracker.py      # Peak equity, drawdown history, daily returns
│
├── performance/
│   └── benchmarking.py        # Sharpe/Sortino, win rate, profit factor, trade journal
│
├── review/
│   ├── reviewer.py            # Portfolio review AI agent
│   └── watchlist_reviewer.py  # Watchlist screening AI agent
│
└── utils/
    └── logging.py             # structlog JSON setup
```

## Persistence

State is persisted in the `.data/` directory, which is cached between GitHub Actions runs:

| File | Purpose |
|------|---------|
| `trade_theses.json` | Active trade theses with reasoning, targets, invalidation criteria |
| `equity_history.json` | Equity snapshots (capped at 365 records) |
| `peak_equity.json` | Peak equity for drawdown calculation |
| `trade_journal.json` | Trade history (last 1000 trades) for performance metrics |

## Key Design Decisions

- **Graceful degradation** — All data providers are optional. No API key = feature disabled, not an error.
- **Persistence via GitHub Actions cache** — `.data/` directory cached between workflow runs.
- **Sector mapping is static** — No API calls needed for sector classification.
- **Risk checks are pre-AI and post-AI** — Drawdown/earnings/sector checks happen in the strategy engine, but the AI also sees all risk data in its prompt.
- **Trailing stops use ATR** — Dynamic stops that adapt to each symbol's volatility.
- **Position scaling** — Entries and exits in 1/3 increments via `scale_action` field.
- **Crypto has distinct rules** — Wider stop losses (8-15% vs 3-5%), BTC dominance monitoring, Fear & Greed context.
- **All HTTP calls use stdlib** — `urllib.request` only, no additional HTTP dependencies.

## Dependencies

| Package | Purpose |
|---------|---------|
| `alpaca-py` | Brokerage API |
| `anthropic` | Claude AI |
| `pandas` | Data manipulation |
| `numpy` | Numerical computation |
| `ta` | Technical indicators |
| `pydantic` / `pydantic-settings` | Data validation and environment config |
| `structlog` | Structured logging |
| `pytz` | Timezone handling |
