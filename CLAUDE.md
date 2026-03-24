# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Development Commands

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest -v

# Run tests with coverage
pytest --cov=financial_agent --cov-report=term-missing -v

# Run a single test file
pytest tests/unit/test_models.py -v

# Run a single test class or method
pytest tests/unit/test_strategy_engine.py::TestStrategyEngine::test_buy_signal_produces_order -v

# Lint
ruff check src/ tests/

# Format check
ruff format --check src/ tests/

# Auto-fix lint issues
ruff check --fix src/ tests/

# Auto-format
ruff format src/ tests/

# Type check
mypy src/

# Run the trading agent locally (requires env vars set)
python -m financial_agent.main

# Run the daily screener
python -m financial_agent.screener_main

# Run the performance report
python -m financial_agent.performance_main

# Run the portfolio review
python -m financial_agent.review_main

# Run the watchlist review
python -m financial_agent.watchlist_main
```

## Architecture

This is an AI-powered stock & crypto trading agent that runs as a scheduled GitHub Action (every 30 minutes 24/7). It uses Alpaca for brokerage and Claude for analysis. The system includes 5 autonomous agents with rich market intelligence.

### Agents & Schedules

| Agent | Schedule | Entry Point | Purpose |
|-------|----------|-------------|---------|
| Trading Agent | Every 30 min (weekday), 2h (weekend) | `main.py` | Core trading cycle |
| Portfolio Review | Daily 9 PM UTC | `review_main.py` | Performance review → GitHub issues |
| Watchlist Review | Daily 1 AM UTC | `watchlist_main.py` | Universe screening → watchlist updates |
| Daily Screener | Weekdays 1 PM UTC | `screener_main.py` | Pre-market unusual activity scan |
| Performance Report | Weekly Saturday | `performance_main.py` | Risk-adjusted metrics report |

### Execution Flow (main.py)

`main()` runs one trading cycle:
1. `AlpacaBroker.is_market_open()` — determines if stocks are included
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

### Package Structure

```
src/financial_agent/
├── main.py                    # Trading agent entry point
├── review_main.py             # Portfolio review agent
├── watchlist_main.py          # Watchlist review agent
├── screener_main.py           # Daily pre-market screener
├── performance_main.py        # Weekly performance report
├── config.py                  # BrokerConfig, AIConfig, DataConfig, TradingConfig, AppConfig
│
├── broker/alpaca_client.py    # Alpaca SDK wrapper (market + limit orders)
├── analysis/ai_analyzer.py    # Claude AI integration (enhanced multi-factor prompt)
│
├── strategy/
│   ├── engine.py              # Risk management: volatility sizing, sector limits, drawdown,
│   │                          #   trailing stops, earnings buffer, limit orders, position scaling
│   └── technical.py           # Indicators: SMA/EMA/MACD/RSI/BB/ATR + 200-day SMA,
│                              #   support/resistance, relative strength, multi-timeframe
│
├── portfolio/models.py        # Position, PortfolioSnapshot, TradeSignal, TradeOrder,
│                              #   OrderType, PositionStage, AssetClass, SignalType
│
├── data/                      # Market data enrichment (all optional, graceful degradation)
│   ├── models.py              # FundamentalData, EarningsEvent, NewsSentiment, MacroContext,
│   │                          #   CryptoMarketContext, MarketEnrichment
│   ├── fundamentals.py        # Financial Modeling Prep API (requires DATA_FMP_API_KEY)
│   ├── earnings.py            # Earnings calendar (requires DATA_FMP_API_KEY)
│   ├── news.py                # Finnhub news/sentiment (requires DATA_FINNHUB_API_KEY)
│   ├── macro.py               # VIX, SPY trend, economic calendar (free, no key needed)
│   ├── crypto_market.py       # BTC dominance, Fear & Greed (CoinGecko, free)
│   └── sector_map.py          # Static GICS sector mapping for 100+ symbols
│
├── risk/                      # Risk management modules
│   ├── drawdown.py            # Tiered drawdown circuit breaker (5/10/15/20%)
│   ├── correlation.py         # Sector exposure tracking and limits
│   └── volatility.py          # ATR-based volatility-adjusted position sizing
│
├── persistence/               # Cross-session state (JSON files, GitHub Actions cache)
│   ├── thesis_store.py        # Trade thesis logging and lifecycle management
│   └── equity_tracker.py      # Peak equity, drawdown history, daily returns
│
├── performance/               # Performance analytics
│   └── benchmarking.py        # Sharpe/Sortino ratio, win rate, profit factor, trade journal
│
├── review/
│   ├── reviewer.py            # Portfolio review AI agent
│   └── watchlist_reviewer.py  # Watchlist screening AI agent
│
└── utils/logging.py           # structlog JSON setup
```

### Data Flow

```
Portfolio Snapshot
    ├── Sector enrichment (sector_map)
    ├── Equity tracking (persistence)
    │
    ├── Market Enrichment (data/)
    │   ├── Fundamentals (FMP API)
    │   ├── Earnings calendar (FMP API)
    │   ├── News sentiment (Finnhub API)
    │   ├── Macro context (VIX, SPY — free)
    │   └── Crypto market (CoinGecko — free)
    │
    ├── Technical Analysis (strategy/technical.py)
    │   ├── Standard indicators (SMA, EMA, MACD, RSI, BB, ATR, OBV)
    │   ├── Extended (SMA-200, weekly trend, support/resistance, 52w high/low)
    │   └── Relative strength vs SPY
    │
    ├── Risk Checks (risk/)
    │   ├── Drawdown circuit breaker → size multiplier or halt
    │   ├── Trailing stops → sell signals
    │   └── Sector exposure → block concentrated buys
    │
    └── AI Analysis (Claude)
        ├── Receives ALL above data in structured prompt
        ├── Evaluates macro → sector → multi-timeframe → fundamentals → news
        ├── Reviews active trade theses (persistence)
        └── Outputs TradeSignal[] with scale_action support
            │
            └── Strategy Engine
                ├── Volatility-adjusted sizing (ATR-based)
                ├── Position scaling (1/2 add-on increments, full initial entry)
                ├── Limit order generation
                └── TradeOrder[] → Broker execution
```

### Key Design Decisions

- **Graceful degradation**: All data providers are optional. No API key = feature disabled, not an error.
- **Persistence via GitHub Actions cache**: `.data/` directory cached between workflow runs.
- **Sector mapping is static**: No API calls needed for sector classification.
- **Risk checks are pre-AI and post-AI**: Drawdown/earnings/sector checks happen in the strategy engine, but the AI also sees all risk data in its prompt.
- **Trailing stops use ATR**: Dynamic stops at 1.5x ATR that adapt to each symbol's volatility.
- **Position scaling**: Full position on initial entry, add-ons at 1/2 increments, partial exits at 1/3 via `scale_action` field.
- **Anti-churn cooldown**: After selling a symbol, re-buying is blocked for `DATA_SELL_COOLDOWN_HOURS` (default 6h).
- **Minimum order value**: Orders below `DATA_MIN_ORDER_VALUE` (default $15) are skipped to prevent micro positions.
- **Aggressive capital deployment**: AI prompt optimized for momentum trading with concentrated positions (max 20% per position, 5% min cash reserve).
- **Drawdown thresholds**: Generous tiers (15%/25%/35%/50%) to avoid premature trading freezes on small accounts.

## Coding Conventions

- **Python 3.11+** with `from __future__ import annotations` in every module
- **Pydantic v2** for all data models and config (BaseModel, BaseSettings)
- **structlog** for logging — use `structlog.get_logger()`, log with keyword args: `log.info("event_name", key=value)`
- **Ruff** for linting and formatting — line length 100, target py311
- **mypy** in strict mode
- **pytest-asyncio** with `asyncio_mode = "auto"`
- Tests use `object.__new__(ClassName)` pattern to bypass `__init__` when testing internal methods (see `test_ai_analyzer.py`)
- All HTTP calls use stdlib `urllib.request` (no additional dependencies)

## CI Pipeline

PR/push to `main` triggers three jobs in `.github/workflows/ci.yml`:
1. **Lint & Type Check** — ruff check, ruff format --check, mypy
2. **Tests** — pytest with coverage (depends on lint passing)
3. **Security Scan** — pip-audit + TruffleHog secrets scan

All three must pass before merging (branch protection).

## Configuration

All config comes from environment variables — no config files.

| Prefix | Source | Examples |
|--------|--------|----------|
| `ALPACA_` | GitHub Secrets | `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` |
| `ANTHROPIC_` | GitHub Secrets | `ANTHROPIC_API_KEY` |
| `TRADING_` | GitHub Variables | `TRADING_WATCHLIST`, `TRADING_STRATEGY`, `TRADING_DRY_RUN` |
| `DATA_` | GitHub Secrets/Variables | `DATA_FMP_API_KEY`, `DATA_FINNHUB_API_KEY`, `DATA_MAX_SECTOR_PCT` |

Optional data provider keys (`DATA_FMP_API_KEY`, `DATA_FINNHUB_API_KEY`) enable richer analysis but are not required. The system works without them.

## Branch Strategy

- `main` is protected — PRs only, squash merge preferred
- Branch naming: `feature/*`, `fix/*`, `refactor/*`, `release/v*`
- CODEOWNERS requires @mikejamescalvert review on all changes
