# Financial Agent

AI-powered stock and cryptocurrency portfolio analyzer and trading agent that runs as a GitHub Action.

## How It Works

The agent runs every 30 minutes, 24/7. Crypto is analyzed on every run; stocks are only analyzed when the US market is open.

1. **Checks** if the stock market is open (crypto always trades)
2. **Fetches** your current portfolio from Alpaca (stocks + crypto)
3. **Runs technical analysis** (RSI, MACD, Bollinger Bands, etc.) on your watchlists
4. **Sends everything to Claude** for AI-powered analysis
5. **Generates trade orders** with position sizing and risk management
6. **Executes trades** (or logs them in dry-run mode)

## Setup

### 1. Create Accounts

- **[Alpaca](https://alpaca.markets/)** — Sign up and get API keys. Start with a paper trading account.
- **[Anthropic](https://console.anthropic.com/)** — Get an API key for Claude.

### 2. Configure GitHub Secrets

Go to **Settings > Secrets and variables > Actions > Secrets** and add:

| Secret | Description |
|--------|-------------|
| `ALPACA_API_KEY` | Your Alpaca API key |
| `ALPACA_SECRET_KEY` | Your Alpaca secret key |
| `ANTHROPIC_API_KEY` | Your Anthropic API key |

### 3. Configure GitHub Variables

Go to **Settings > Secrets and variables > Actions > Variables** and add:

| Variable | Default | Description |
|----------|---------|-------------|
| `ALPACA_BASE_URL` | `https://paper-api.alpaca.markets` | Broker URL. Use `https://api.alpaca.markets` for live trading |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | Claude model for analysis |
| `TRADING_WATCHLIST` | `AAPL,MSFT,GOOGL,AMZN,NVDA,META,TSLA,JPM,V,JNJ` | Comma-separated stock symbols |
| `TRADING_CRYPTO_WATCHLIST` | `BTC/USD,ETH/USD,SOL/USD` | Comma-separated crypto pairs (Alpaca format) |
| `TRADING_STRATEGY` | `balanced` | Strategy: `balanced`, `conservative`, `momentum` |
| `TRADING_DRY_RUN` | `false` | Set to `true` to disable trading and only log orders |
| `TRADING_MAX_POSITION_PCT` | `0.10` | Max portfolio % for a single position |
| `TRADING_MAX_DAILY_TRADES` | `10` | Max trades per day |
| `TRADING_STOP_LOSS_PCT` | `0.05` | Default stop loss % |
| `TRADING_TAKE_PROFIT_PCT` | `0.15` | Default take profit % |
| `TRADING_MIN_CASH_RESERVE_PCT` | `0.10` | Minimum cash reserve as % of portfolio |
| `LOG_LEVEL` | `INFO` | Logging level |

### 4. Create GitHub Environment

Go to **Settings > Environments** and create an environment called `trading`:

- Add **required reviewers** (yourself) for deployment protection
- This prevents accidental execution of trading workflows

### 5. Set Up Branch Protection

See [`.github/branch-protection.md`](.github/branch-protection.md) for detailed instructions on configuring branch protection rules.

### 6. Enable the Workflow

The trading agent runs automatically on schedule. You can also trigger it manually:

**Actions > Trading Agent > Run workflow**

## Project Structure

```
├── .github/
│   ├── workflows/
│   │   ├── trading-agent.yml    # Scheduled trading workflow
│   │   └── ci.yml               # CI: lint, test, security
│   ├── CODEOWNERS               # Required reviewers
│   ├── SECURITY.md              # Security policy
│   ├── dependabot.yml           # Dependency updates
│   ├── pull_request_template.md # PR template
│   └── ISSUE_TEMPLATE/          # Issue templates
├── src/financial_agent/
│   ├── main.py                  # Entry point
│   ├── config.py                # Configuration (env vars)
│   ├── broker/
│   │   └── alpaca_client.py     # Alpaca API integration
│   ├── portfolio/
│   │   └── models.py            # Data models (Position, Order, Signal)
│   ├── strategy/
│   │   ├── engine.py            # Order generation with risk management
│   │   └── technical.py         # Technical indicator computation
│   ├── analysis/
│   │   └── ai_analyzer.py       # Claude-powered market analysis
│   └── utils/
│       └── logging.py           # Structured logging
└── tests/
    └── unit/                    # Unit tests
```

## Trading Strategies

| Strategy | Description |
|----------|-------------|
| `balanced` | Mix of momentum, mean-reversion, and fundamentals |
| `conservative` | Dividend stocks, covered calls, capital preservation |
| `momentum` | Momentum indicators, breakouts, growth stocks |

## Safety Features

- **Paper trading** URL is the default broker endpoint — trades go to your Alpaca paper account, not real money
- **Dry-run mode** can be enabled via `TRADING_DRY_RUN=true` to log orders without submitting them
- **Position limits** prevent over-concentration in any single asset
- **Cash reserves** ensure you always maintain a minimum cash buffer
- **Separate asset pipelines** — crypto and stocks are analyzed independently with asset-appropriate risk rules
- **Daily trade limits** prevent runaway execution
- **Environment protection** requires manual approval for the trading environment
- **CI pipeline** runs lint, type checks, tests, and security scans on every PR

## Local Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest -v

# Lint
ruff check src/ tests/

# Type check
mypy src/
```

## Going Live

1. Change `ALPACA_BASE_URL` to `https://api.alpaca.markets`
2. Start with a small watchlist and conservative strategy
3. Monitor the Actions tab for execution summaries
4. Set `TRADING_DRY_RUN=true` if you need to pause trading without disabling the workflow
