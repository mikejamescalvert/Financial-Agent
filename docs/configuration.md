# Configuration

All configuration is via environment variables — no config files. In production, these are set as GitHub Secrets (for credentials) and GitHub Variables (for tunable parameters).

## Required Secrets

| Variable | Description |
|----------|-------------|
| `ALPACA_API_KEY` | Alpaca brokerage API key |
| `ALPACA_SECRET_KEY` | Alpaca brokerage secret key |
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude |

## Optional Data Provider Keys

These enable richer market analysis but are not required. The system works without them.

| Variable | Provider | Features Enabled |
|----------|----------|-----------------|
| `DATA_FMP_API_KEY` | [Financial Modeling Prep](https://financialmodelingprep.com/) | Fundamentals (EPS, P/E, margins, FCF), earnings calendar |
| `DATA_FINNHUB_API_KEY` | [Finnhub](https://finnhub.io/) | News headlines + sentiment analysis per symbol |

Free data (no key needed): VIX, SPY trend, 10Y yield, economic calendar, BTC dominance, Fear & Greed index.

## Broker Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ALPACA_BASE_URL` | `https://paper-api.alpaca.markets` | Broker API URL. Use `https://api.alpaca.markets` for live trading |
| `ALPACA_DATA_URL` | *(Alpaca default)* | Market data API URL |

## AI Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | Claude model for analysis |
| `ANTHROPIC_MAX_TOKENS` | `4096` | Max tokens for AI response |

## Trading Parameters

| Variable | Default | Description |
|----------|---------|-------------|
| `TRADING_WATCHLIST` | `AAPL,MSFT,GOOGL,AMZN,NVDA,META,TSLA,JPM,V,JNJ` | Active stock watchlist (comma-separated) |
| `TRADING_CRYPTO_WATCHLIST` | `BTC/USD,ETH/USD,SOL/USD` | Active crypto watchlist (Alpaca format) |
| `TRADING_STOCK_UNIVERSE` | *(110 symbols)* | Full stock screening universe (11 GICS sectors) |
| `TRADING_CRYPTO_UNIVERSE` | *(12 symbols)* | Full crypto screening universe |
| `TRADING_STRATEGY` | `balanced` | Strategy: `balanced`, `conservative`, `momentum` |
| `TRADING_MAX_POSITION_PCT` | `0.10` | Max portfolio % for a single position |
| `TRADING_MAX_DAILY_TRADES` | `10` | Max trades per day |
| `TRADING_STOP_LOSS_PCT` | `0.05` | Default stop loss percentage |
| `TRADING_TAKE_PROFIT_PCT` | `0.15` | Default take profit percentage |
| `TRADING_MIN_CASH_RESERVE_PCT` | `0.10` | Minimum cash reserve as % of portfolio |
| `TRADING_HISTORICAL_DAYS` | `270` | Days of historical data to fetch for analysis |
| `TRADING_DRY_RUN` | `false` | Set to `true` to log orders without executing |

## Risk & Data Parameters

| Variable | Default | Description |
|----------|---------|-------------|
| `DATA_EARNINGS_BUFFER_DAYS` | `3` | Days before earnings to block buy signals |
| `DATA_MAX_SECTOR_PCT` | `0.30` | Max portfolio allocation per GICS sector |
| `DATA_TRAILING_STOP_ATR_MULTIPLIER` | `2.0` | ATR multiplier for trailing stop distance |
| `DATA_SLIPPAGE_TOLERANCE_PCT` | `0.002` | Slippage tolerance for limit order pricing |
| `DATA_USE_LIMIT_ORDERS` | `true` | Use limit orders instead of market orders |
| `DATA_ENABLE_POSITION_SCALING` | `true` | Enable 1/3 increment position scaling |
| `DATA_RISK_BUDGET_PCT` | `0.02` | Risk budget per trade as % of equity (for ATR-based sizing) |

## Application

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

## Configuration Classes

Configuration is managed by 5 Pydantic settings classes in `config.py`:

| Class | Prefix | Responsibility |
|-------|--------|----------------|
| `BrokerConfig` | `ALPACA_` | Brokerage connection |
| `AIConfig` | `ANTHROPIC_` | Claude AI settings |
| `DataConfig` | `DATA_` | Data providers + risk parameters |
| `TradingConfig` | `TRADING_` | Watchlists, limits, strategy |
| `AppConfig` | *(aggregates all)* | Top-level config with log level |

## Example: Minimal Setup

Set these 3 secrets and the system runs with sensible defaults:

```
ALPACA_API_KEY=your-key
ALPACA_SECRET_KEY=your-secret
ANTHROPIC_API_KEY=your-key
```

## Example: Full Setup

For maximum market intelligence:

```
# Required
ALPACA_API_KEY=your-key
ALPACA_SECRET_KEY=your-secret
ANTHROPIC_API_KEY=your-key

# Optional data providers
DATA_FMP_API_KEY=your-fmp-key
DATA_FINNHUB_API_KEY=your-finnhub-key

# Tuning
TRADING_STRATEGY=balanced
TRADING_MAX_POSITION_PCT=0.08
DATA_MAX_SECTOR_PCT=0.25
DATA_RISK_BUDGET_PCT=0.015
DATA_TRAILING_STOP_ATR_MULTIPLIER=2.5
TRADING_DRY_RUN=false
```
