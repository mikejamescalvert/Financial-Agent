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
        default="claude-sonnet-4-6-20250620",
        description="Claude model to use (GitHub Variable: ANTHROPIC_MODEL)",
    )
    max_tokens: int = Field(
        default=4096,
        description="Max tokens for AI responses (GitHub Variable: ANTHROPIC_MAX_TOKENS)",
    )


class DataConfig(BaseSettings):
    """External data provider configuration. API keys are optional."""

    model_config = {"env_prefix": "DATA_"}

    fmp_api_key: str = Field(
        default="",
        description="Financial Modeling Prep API key for fundamentals/earnings.",
    )
    finnhub_api_key: str = Field(
        default="",
        description="Finnhub API key for news/sentiment.",
    )
    data_dir: str = Field(
        default=".data",
        description="Directory for persistent data (theses, equity history, trade journal).",
    )
    earnings_buffer_days: int = Field(
        default=3,
        description="Avoid opening positions within N days of earnings.",
    )
    max_sector_pct: float = Field(
        default=0.30,
        description="Max portfolio allocation to any single sector.",
    )
    trailing_stop_atr_multiplier: float = Field(
        default=2.0,
        description="Trailing stop distance as multiple of ATR.",
    )
    slippage_tolerance_pct: float = Field(
        default=0.002,
        description="Max slippage for limit orders (0.2%).",
    )
    use_limit_orders: bool = Field(
        default=True,
        description="Use limit orders instead of market orders.",
    )
    enable_position_scaling: bool = Field(
        default=True,
        description="Enable partial entry/exit scaling.",
    )
    risk_budget_pct: float = Field(
        default=0.02,
        description="Target risk per position as fraction of equity.",
    )
    min_order_value: float = Field(
        default=25.0,
        description="Minimum order value in dollars. Orders below this are skipped.",
    )
    sell_cooldown_hours: int = Field(
        default=48,
        description="Hours after selling a symbol before it can be re-bought.",
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
            # Technology (15)
            "AAPL,MSFT,GOOGL,NVDA,META,AVGO,ADBE,CRM,ORCL,CSCO,"
            "INTC,AMD,QCOM,NOW,IBM,"
            # Consumer Discretionary (10)
            "AMZN,TSLA,HD,NFLX,COST,NKE,MCD,SBUX,TJX,BKNG,"
            # Financials (10)
            "JPM,V,MA,GS,MS,BRK.B,BAC,WFC,BLK,SCHW,"
            # Healthcare (10)
            "UNH,JNJ,LLY,PFE,ABT,TMO,ABBV,MRK,AMGN,ISRG,"
            # Industrials (10)
            "BA,CAT,GE,MMM,LMT,RTX,UPS,HON,DE,UNP,"
            # Communication Services (5)
            "GOOG,DIS,CMCSA,T,VZ,"
            # Energy (8)
            "XOM,CVX,COP,SLB,EOG,MPC,PSX,OXY,"
            # Utilities (5)
            "NEE,SO,DUK,D,AEP,"
            # Real Estate (5)
            "AMT,PLD,CCI,EQIX,SPG,"
            # Materials (5)
            "LIN,APD,SHW,ECL,FCX,"
            # Consumer Staples (7)
            "PG,PEP,KO,WMT,PM,MO,CL,"
            # Sector ETFs & Benchmarks (8)
            "SPY,QQQ,XLK,XLF,XLE,XLV,XLI,IWM,"
            # International ADRs (5)
            "TSM,ASML,NVO,BABA,SAP"
        ),
        description="Broad screening universe covering all 11 GICS sectors + ETFs + ADRs.",
    )
    crypto_universe: str = Field(
        default=(
            "BTC/USD,ETH/USD,SOL/USD,DOGE/USD,AVAX/USD,"
            "LINK/USD,DOT/USD,MATIC/USD,ADA/USD,XRP/USD,ATOM/USD,UNI/USD"
        ),
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
    historical_days: int = Field(
        default=270,
        description="Days of historical data to fetch (270 > 252 trading days = 1 year).",
    )


class AppConfig(BaseSettings):
    """Top-level application configuration."""

    broker: BrokerConfig = Field(default_factory=BrokerConfig)  # type: ignore[arg-type]
    ai: AIConfig = Field(default_factory=AIConfig)  # type: ignore[arg-type]
    trading: TradingConfig = Field(default_factory=TradingConfig)
    data: DataConfig = Field(default_factory=DataConfig)

    log_level: str = Field(
        default="INFO",
        description="Logging level (GitHub Variable: LOG_LEVEL)",
    )
