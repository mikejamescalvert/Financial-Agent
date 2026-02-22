"""Configuration management using environment variables and GitHub Variables.

All sensitive values (API keys, secrets) are stored in GitHub Secrets.
All tunable parameters (thresholds, limits) are stored in GitHub Variables.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class BrokerConfig(BaseSettings):
    """Alpaca broker configuration. Keys come from GitHub Secrets."""

    model_config = {"env_prefix": "ALPACA_"}

    api_key: str = Field(description="Alpaca API key (GitHub Secret: ALPACA_API_KEY)")
    secret_key: str = Field(description="Alpaca secret key (GitHub Secret: ALPACA_SECRET_KEY)")
    base_url: str = Field(
        default="https://paper-api.alpaca.markets",
        description="Alpaca base URL. Use paper URL for testing.",
    )
    data_url: str = Field(
        default="https://data.alpaca.markets",
        description="Alpaca data URL (GitHub Variable: ALPACA_DATA_URL)",
    )


class AIConfig(BaseSettings):
    """Claude AI configuration."""

    model_config = {"env_prefix": "ANTHROPIC_"}

    api_key: str = Field(description="Anthropic API key (GitHub Secret: ANTHROPIC_API_KEY)")
    model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Claude model to use (GitHub Variable: ANTHROPIC_MODEL)",
    )
    max_tokens: int = Field(
        default=4096,
        description="Max tokens for AI responses (GitHub Variable: ANTHROPIC_MAX_TOKENS)",
    )


class TradingConfig(BaseSettings):
    """Trading strategy parameters. All from GitHub Variables."""

    model_config = {"env_prefix": "TRADING_"}

    max_position_pct: float = Field(
        default=0.10,
        description="Max portfolio % for a single position.",
    )
    max_daily_trades: int = Field(
        default=10,
        description="Max trades per day (GitHub Variable: TRADING_MAX_DAILY_TRADES)",
    )
    stop_loss_pct: float = Field(
        default=0.05,
        description="Default stop loss percentage (GitHub Variable: TRADING_STOP_LOSS_PCT)",
    )
    take_profit_pct: float = Field(
        default=0.15,
        description="Default take profit percentage (GitHub Variable: TRADING_TAKE_PROFIT_PCT)",
    )
    min_cash_reserve_pct: float = Field(
        default=0.10,
        description="Minimum cash reserve as % of portfolio.",
    )
    watchlist: str = Field(
        default="AAPL,MSFT,GOOGL,AMZN,NVDA,META,TSLA,JPM,V,JNJ",
        description="Comma-separated watchlist (GitHub Variable: TRADING_WATCHLIST)",
    )
    crypto_watchlist: str = Field(
        default="BTC/USD,ETH/USD,SOL/USD",
        description="Comma-separated crypto watchlist (GitHub Variable: TRADING_CRYPTO_WATCHLIST)",
    )
    stock_universe: str = Field(
        default=(
            "AAPL,MSFT,GOOGL,AMZN,NVDA,META,TSLA,JPM,V,JNJ,"
            "UNH,HD,PG,MA,DIS,NFLX,ADBE,CRM,COST,PEP,"
            "AMD,INTC,QCOM,AVGO,ORCL,CSCO,IBM,NOW,UBER,SQ,"
            "BA,CAT,GE,MMM,LMT,RTX,GS,MS,BRK.B,WMT"
        ),
        description="Broad screening universe for watchlist review.",
    )
    crypto_universe: str = Field(
        default="BTC/USD,ETH/USD,SOL/USD,DOGE/USD,AVAX/USD,LINK/USD,DOT/USD,MATIC/USD,ADA/USD",
        description="Broad crypto screening universe (GitHub Variable: TRADING_CRYPTO_UNIVERSE)",
    )
    strategy: str = Field(
        default="balanced",
        description="Active strategy: balanced, conservative, momentum.",
    )
    dry_run: bool = Field(
        default=False,
        description="If true, log trades but don't execute (GitHub Variable: TRADING_DRY_RUN)",
    )


class AppConfig(BaseSettings):
    """Top-level application configuration."""

    broker: BrokerConfig = Field(default_factory=BrokerConfig)  # type: ignore[arg-type]
    ai: AIConfig = Field(default_factory=AIConfig)  # type: ignore[arg-type]
    trading: TradingConfig = Field(default_factory=TradingConfig)

    log_level: str = Field(
        default="INFO",
        description="Logging level (GitHub Variable: LOG_LEVEL)",
    )
