# Financial Agent

AI-powered stock and cryptocurrency trading system that runs autonomously as GitHub Actions. Uses Alpaca for brokerage, Claude for analysis, and a multi-layered risk management framework to make informed trading decisions 24/7.

## System Overview

The system consists of **5 autonomous agents**, each running on its own schedule:

| Agent | Schedule | Purpose |
|-------|----------|---------|
| **Trading Agent** | Every 30 min, 24/7 | Core trading cycle — analyze markets, generate signals, execute trades |
| **Portfolio Review** | Daily 9 PM UTC | Grade portfolio health (A-F), create improvement suggestions as GitHub issues |
| **Watchlist Review** | Daily 1 AM UTC | Screen a 110-stock + 12-crypto universe, dynamically update watchlists |
| **Daily Screener** | Weekdays 1 PM UTC | Pre-market scan for breakouts, unusual volume, and sector momentum |
| **Performance Report** | Weekly (Saturday) | Risk-adjusted metrics: Sharpe, Sortino, win rate, profit factor |

### How the Trading Agent Works

Each 30-minute cycle:

1. **Portfolio snapshot** — Fetch account + positions from Alpaca, enrich with sector data
2. **Market enrichment** — Gather fundamentals, earnings, news sentiment, macro indicators, crypto context
3. **Technical analysis** — Compute 20+ indicators per symbol across multiple timeframes
4. **Risk assessment** — Check drawdown circuit breaker, trailing stops, sector exposure
5. **AI analysis** — Claude evaluates all data using a macro → sector → technical → fundamental framework
6. **Order generation** — Strategy engine applies volatility-adjusted sizing, position scaling, limit orders
7. **Execution** — Submit orders to Alpaca (or log in dry-run mode)
8. **Logging** — Record trade theses, journal entries, equity history

Crypto is analyzed on every run; stocks only when the US market is open.

## Key Features

- **Multi-asset trading** — Stocks and crypto with asset-appropriate risk rules
- **5 autonomous agents** — Trading, portfolio review, watchlist screening, pre-market scanning, performance reporting
- **20+ technical indicators** — SMA/EMA/MACD/RSI/Bollinger/ATR/OBV, 200-day SMA, relative strength vs SPY, multi-timeframe analysis
- **AI-powered decisions** — Claude analyzes technicals + fundamentals + news + macro context as a unified framework
- **Tiered drawdown protection** — Circuit breaker with 5 severity levels (5%/10%/15%/20% thresholds)
- **Volatility-adjusted sizing** — ATR-based position sizing with configurable risk budget
- **Position scaling** — Gradual entries and exits in 1/3 increments
- **Sector concentration limits** — Max 30% portfolio per GICS sector (configurable)
- **Earnings awareness** — Blocks buys within a configurable buffer window before earnings
- **ATR-based trailing stops** — Dynamic stops that adapt to each symbol's volatility
- **Limit orders with slippage control** — Configurable slippage tolerance for order placement
- **Market data enrichment** — Fundamentals (FMP), news/sentiment (Finnhub), macro (VIX/SPY), crypto (CoinGecko)
- **Graceful degradation** — All data providers are optional; no API key = feature disabled, not an error
- **Trade thesis persistence** — Every trade logged with reasoning, confidence, and invalidation criteria
- **Performance analytics** — Sharpe ratio, Sortino ratio, win rate, profit factor, max drawdown tracking
- **GitHub-native automation** — Review results and alerts posted as GitHub issues

For detailed architecture and data flow, see [docs/architecture.md](docs/architecture.md).

## Quick Start

### 1. Create Accounts

- **[Alpaca](https://alpaca.markets/)** — Sign up and get API keys (start with paper trading)
- **[Anthropic](https://console.anthropic.com/)** — Get an API key for Claude

### 2. Configure GitHub Secrets

Go to **Settings > Secrets and variables > Actions > Secrets**:

| Secret | Required | Description |
|--------|----------|-------------|
| `ALPACA_API_KEY` | Yes | Alpaca API key |
| `ALPACA_SECRET_KEY` | Yes | Alpaca secret key |
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key |
| `DATA_FMP_API_KEY` | No | [Financial Modeling Prep](https://financialmodelingprep.com/) — enables fundamentals + earnings data |
| `DATA_FINNHUB_API_KEY` | No | [Finnhub](https://finnhub.io/) — enables news sentiment analysis |

### 3. Configure GitHub Variables

Go to **Settings > Secrets and variables > Actions > Variables**:

| Variable | Default | Description |
|----------|---------|-------------|
| `TRADING_WATCHLIST` | `AAPL,MSFT,GOOGL,...` | Active stock watchlist |
| `TRADING_CRYPTO_WATCHLIST` | `BTC/USD,ETH/USD,SOL/USD` | Active crypto watchlist |
| `TRADING_STRATEGY` | `balanced` | Strategy: `balanced`, `conservative`, `momentum` |
| `TRADING_DRY_RUN` | `false` | `true` to log orders without executing |

For the full list of 40+ configuration variables, see [docs/configuration.md](docs/configuration.md).

### 4. Create GitHub Environment

Go to **Settings > Environments** and create an environment called `trading`:

- Add **required reviewers** (yourself) for deployment protection
- This prevents accidental execution of trading workflows

### 5. Set Up Branch Protection

See [`.github/branch-protection.md`](.github/branch-protection.md) for detailed instructions.

### 6. Enable Workflows

The agents run automatically on schedule after merging to `main`. You can also trigger any workflow manually from the **Actions** tab.

## Safety Features

- **Paper trading by default** — `ALPACA_BASE_URL` defaults to Alpaca's paper trading endpoint
- **Dry-run mode** — `TRADING_DRY_RUN=true` logs orders without submitting them
- **Drawdown circuit breaker** — 5-tier protection that progressively reduces position sizes, blocks buys, and can halt trading entirely at severe drawdown levels
- **Position limits** — Max 10% of portfolio in any single position (configurable)
- **Sector concentration limits** — Max 30% per GICS sector prevents over-exposure
- **Cash reserves** — Always maintains a minimum cash buffer (default 10%)
- **Earnings buffer** — Blocks buy signals near earnings dates to avoid volatility
- **Daily trade limits** — Prevents runaway execution
- **ATR-based trailing stops** — Automatically generates sell signals when stops are hit
- **Environment protection** — GitHub environment requires manual approval
- **CI pipeline** — Lint, type checks, tests, and security scans on every PR

For details on the risk management system, see [docs/risk-management.md](docs/risk-management.md).

## Trading Strategies

| Strategy | Description |
|----------|-------------|
| `balanced` | Mix of momentum, mean-reversion, and fundamentals |
| `conservative` | Dividend stocks, covered calls, capital preservation |
| `momentum` | Momentum indicators, breakouts, growth stocks |

## Local Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest -v

# Lint & format
ruff check src/ tests/
ruff format --check src/ tests/

# Type check
mypy src/

# Run agents locally (requires env vars)
python -m financial_agent.main
python -m financial_agent.review_main
python -m financial_agent.watchlist_main
python -m financial_agent.screener_main
python -m financial_agent.performance_main
```

## CI Pipeline

PR/push to `main` triggers three jobs in `.github/workflows/ci.yml`:

1. **Lint & Type Check** — ruff check, ruff format --check, mypy
2. **Tests** — pytest with coverage (259 tests)
3. **Security Scan** — pip-audit + TruffleHog secrets scan

All three must pass before merging.

## Going Live

1. Change `ALPACA_BASE_URL` to `https://api.alpaca.markets`
2. Start with a small watchlist and `conservative` strategy
3. Monitor the Actions tab for execution summaries
4. Set `TRADING_DRY_RUN=true` if you need to pause trading without disabling workflows

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/architecture.md) | System design, data flow, package structure |
| [Configuration](docs/configuration.md) | All 40+ environment variables with defaults |
| [Risk Management](docs/risk-management.md) | Drawdown protection, position sizing, sector limits, trailing stops |

## Branch Strategy

- `main` is protected — PRs only, squash merge preferred
- Branch naming: `feature/*`, `fix/*`, `refactor/*`, `release/v*`
- CODEOWNERS requires @mikejamescalvert review on all changes
