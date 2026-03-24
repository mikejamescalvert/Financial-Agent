"""Tests for enhanced strategy engine features (drawdown, earnings, trailing stops, etc.)."""

from __future__ import annotations

from datetime import date

from financial_agent.config import DataConfig, TradingConfig
from financial_agent.data.models import EarningsEvent, MarketEnrichment
from financial_agent.portfolio.models import (
    OrderType,
    PortfolioSnapshot,
    Position,
    SignalType,
    TradeSignal,
)
from financial_agent.risk.drawdown import DrawdownCircuitBreaker
from financial_agent.risk.volatility import VolatilitySizer
from financial_agent.strategy.engine import StrategyEngine


def _make_config(**overrides) -> TradingConfig:
    defaults = {
        "max_position_pct": 0.10,
        "max_daily_trades": 10,
        "stop_loss_pct": 0.05,
        "take_profit_pct": 0.15,
        "min_cash_reserve_pct": 0.10,
        "watchlist": "AAPL,MSFT",
        "strategy": "balanced",
        "dry_run": True,
    }
    defaults.update(overrides)
    return TradingConfig(**defaults)


def _make_data_config(**overrides) -> DataConfig:
    defaults = {
        "data_dir": ".data",
        "earnings_buffer_days": 3,
        "max_sector_pct": 0.30,
        "trailing_stop_atr_multiplier": 2.0,
        "slippage_tolerance_pct": 0.002,
        "use_limit_orders": False,
        "enable_position_scaling": False,
        "risk_budget_pct": 0.02,
    }
    defaults.update(overrides)
    return DataConfig(**defaults)


def _make_portfolio(
    positions: list[Position] | None = None,
    equity: float = 100_000.0,
    cash: float = 20_000.0,
) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        equity=equity,
        cash=cash,
        buying_power=cash * 2,
        positions=positions or [],
    )


def _make_signal(
    symbol: str = "AAPL",
    signal: SignalType = SignalType.BUY,
    confidence: float = 0.7,
    reason: str = "Test signal",
    scale_action: str = "",
) -> TradeSignal:
    return TradeSignal(
        symbol=symbol,
        signal=signal,
        confidence=confidence,
        reason=reason,
        scale_action=scale_action,
    )


def _make_position(
    symbol: str = "AAPL",
    qty: float = 10.0,
    current_price: float = 160.0,
    highest_price: float = 170.0,
    **overrides,
) -> Position:
    defaults = {
        "symbol": symbol,
        "qty": qty,
        "avg_entry_price": 150.0,
        "current_price": current_price,
        "market_value": qty * current_price,
        "unrealized_pl": (current_price - 150.0) * qty,
        "unrealized_pl_pct": (current_price - 150.0) / 150.0,
        "highest_price": highest_price,
    }
    defaults.update(overrides)
    return Position(**defaults)


class TestDrawdownCircuitBreakerIntegration:
    def test_buys_blocked_when_drawdown_high(self):
        """When drawdown >= 25%, buys should be blocked (size_multiplier=0)."""
        breaker = DrawdownCircuitBreaker(peak_equity=100_000.0)
        engine = StrategyEngine(
            config=_make_config(),
            drawdown_breaker=breaker,
        )
        # 25% drawdown: equity=75k, peak=100k
        portfolio = _make_portfolio(equity=75_000.0, cash=15_000.0)
        technicals = {"AAPL": {"current_price": 160.0}}
        signals = [_make_signal(signal=SignalType.BUY)]

        orders = engine.generate_orders(signals, portfolio, technicals)
        assert len(orders) == 0

    def test_sells_still_allowed_during_drawdown(self):
        """Sell orders should work even when drawdown blocks buys."""
        breaker = DrawdownCircuitBreaker(peak_equity=100_000.0)
        engine = StrategyEngine(
            config=_make_config(),
            drawdown_breaker=breaker,
        )
        portfolio = _make_portfolio(
            equity=75_000.0,
            cash=15_000.0,
            positions=[_make_position(symbol="AAPL", qty=10.0, current_price=160.0)],
        )
        signals = [_make_signal(signal=SignalType.SELL, confidence=0.5)]
        orders = engine.generate_orders(signals, portfolio)
        assert len(orders) == 1
        assert orders[0].side == "sell"

    def test_halt_blocks_all_trading(self):
        """When drawdown >= 50%, all trading should halt."""
        breaker = DrawdownCircuitBreaker(peak_equity=100_000.0)
        engine = StrategyEngine(
            config=_make_config(),
            drawdown_breaker=breaker,
        )
        # 50% drawdown
        portfolio = _make_portfolio(
            equity=50_000.0,
            cash=10_000.0,
            positions=[_make_position(symbol="AAPL", qty=10.0, current_price=160.0)],
        )
        signals = [
            _make_signal(signal=SignalType.BUY),
            _make_signal(symbol="AAPL", signal=SignalType.SELL),
        ]
        orders = engine.generate_orders(signals, portfolio)
        assert len(orders) == 0

    def test_reduced_sizing_during_moderate_drawdown(self):
        """15% drawdown should reduce buy sizes to 75%."""
        breaker = DrawdownCircuitBreaker(peak_equity=100_000.0)
        engine = StrategyEngine(
            config=_make_config(),
            drawdown_breaker=breaker,
        )
        portfolio = _make_portfolio(equity=85_000.0, cash=17_000.0)
        technicals = {"AAPL": {"current_price": 100.0}}
        signals = [_make_signal(signal=SignalType.BUY, confidence=0.8)]

        orders = engine.generate_orders(signals, portfolio, technicals)
        assert len(orders) == 1
        # Max position = 85000 * 0.10 = 8500
        # Target = 8500 * 0.8 * 0.75 (size_multiplier) = 5100
        # qty = 5100 / 100 = 51
        assert orders[0].qty == 51.0


class TestEarningsBufferIntegration:
    def test_blocks_buys_near_earnings(self):
        """Buys should be blocked when earnings are within buffer days."""
        data_config = _make_data_config(earnings_buffer_days=3)
        engine = StrategyEngine(
            config=_make_config(),
            data_config=data_config,
        )
        enrichment = MarketEnrichment(
            earnings=[
                EarningsEvent(
                    symbol="AAPL",
                    earnings_date=date(2026, 2, 23),
                    days_until_earnings=2,
                )
            ]
        )
        portfolio = _make_portfolio(equity=100_000.0, cash=20_000.0)
        technicals = {"AAPL": {"current_price": 160.0}}
        signals = [_make_signal(signal=SignalType.BUY)]

        orders = engine.generate_orders(signals, portfolio, technicals, enrichment)
        assert len(orders) == 0

    def test_allows_buys_far_from_earnings(self):
        """Buys should be allowed when earnings are far enough away."""
        data_config = _make_data_config(earnings_buffer_days=3)
        engine = StrategyEngine(
            config=_make_config(),
            data_config=data_config,
        )
        enrichment = MarketEnrichment(
            earnings=[
                EarningsEvent(
                    symbol="AAPL",
                    earnings_date=date(2026, 4, 25),
                    days_until_earnings=30,
                )
            ]
        )
        portfolio = _make_portfolio(equity=100_000.0, cash=20_000.0)
        technicals = {"AAPL": {"current_price": 160.0}}
        signals = [_make_signal(signal=SignalType.BUY)]

        orders = engine.generate_orders(signals, portfolio, technicals, enrichment)
        assert len(orders) == 1

    def test_sells_not_blocked_near_earnings(self):
        """Sell orders should not be blocked by earnings proximity."""
        data_config = _make_data_config(earnings_buffer_days=3)
        engine = StrategyEngine(
            config=_make_config(),
            data_config=data_config,
        )
        enrichment = MarketEnrichment(
            earnings=[
                EarningsEvent(
                    symbol="AAPL",
                    earnings_date=date(2026, 2, 23),
                    days_until_earnings=1,
                )
            ]
        )
        portfolio = _make_portfolio(
            positions=[_make_position(symbol="AAPL")],
        )
        signals = [_make_signal(signal=SignalType.SELL, confidence=0.5)]

        orders = engine.generate_orders(signals, portfolio, enrichment=enrichment)
        assert len(orders) == 1
        assert orders[0].side == "sell"


class TestTrailingStops:
    def test_generates_sell_when_stop_hit(self):
        data_config = _make_data_config(trailing_stop_atr_multiplier=2.0)
        engine = StrategyEngine(
            config=_make_config(),
            data_config=data_config,
        )
        # Position with high=170, current=160, ATR=3
        # Trailing stop = 170 - (3 * 2.0) = 164
        # Current 160 < 164, stop triggered
        portfolio = _make_portfolio(
            positions=[
                _make_position(
                    symbol="AAPL",
                    qty=10.0,
                    current_price=160.0,
                    highest_price=170.0,
                )
            ],
        )
        technicals = {"AAPL": {"atr_14": 3.0}}

        signals = engine.check_trailing_stops(portfolio, technicals)
        assert len(signals) == 1
        assert signals[0].symbol == "AAPL"
        assert signals[0].signal == SignalType.SELL
        assert signals[0].confidence == 0.9
        assert "Trailing stop hit" in signals[0].reason

    def test_no_signal_when_above_stop(self):
        data_config = _make_data_config(trailing_stop_atr_multiplier=2.0)
        engine = StrategyEngine(
            config=_make_config(),
            data_config=data_config,
        )
        # Position with high=170, current=168, ATR=3
        # Trailing stop = 170 - (3 * 2.0) = 164
        # Current 168 > 164, no trigger
        portfolio = _make_portfolio(
            positions=[
                _make_position(
                    symbol="AAPL",
                    qty=10.0,
                    current_price=168.0,
                    highest_price=170.0,
                )
            ],
        )
        technicals = {"AAPL": {"atr_14": 3.0}}

        signals = engine.check_trailing_stops(portfolio, technicals)
        assert len(signals) == 0

    def test_no_signal_without_data_config(self):
        engine = StrategyEngine(config=_make_config())
        portfolio = _make_portfolio(
            positions=[_make_position(symbol="AAPL")],
        )
        technicals = {"AAPL": {"atr_14": 3.0}}
        signals = engine.check_trailing_stops(portfolio, technicals)
        assert len(signals) == 0

    def test_skips_symbol_without_technicals(self):
        data_config = _make_data_config(trailing_stop_atr_multiplier=2.0)
        engine = StrategyEngine(
            config=_make_config(),
            data_config=data_config,
        )
        portfolio = _make_portfolio(
            positions=[_make_position(symbol="AAPL")],
        )
        technicals = {"MSFT": {"atr_14": 3.0}}  # No AAPL technicals
        signals = engine.check_trailing_stops(portfolio, technicals)
        assert len(signals) == 0

    def test_skips_zero_atr(self):
        data_config = _make_data_config(trailing_stop_atr_multiplier=2.0)
        engine = StrategyEngine(
            config=_make_config(),
            data_config=data_config,
        )
        portfolio = _make_portfolio(
            positions=[_make_position(symbol="AAPL")],
        )
        technicals = {"AAPL": {"atr_14": 0.0}}
        signals = engine.check_trailing_stops(portfolio, technicals)
        assert len(signals) == 0


class TestVolatilityAdjustedSizing:
    def test_reduces_position_for_high_vol_stock(self):
        """High-volatility stocks should get smaller positions."""
        vol_sizer = VolatilitySizer()
        engine = StrategyEngine(
            config=_make_config(),
            volatility_sizer=vol_sizer,
        )
        portfolio = _make_portfolio(equity=100_000.0, cash=20_000.0)
        # atr_pct = (8/100)*100 = 8.0 -> very_high -> cap = 0.07
        technicals = {"AAPL": {"current_price": 100.0, "atr_pct": 8.0}}
        signals = [_make_signal(signal=SignalType.BUY, confidence=0.8)]

        orders = engine.generate_orders(signals, portfolio, technicals)
        assert len(orders) == 1
        # vol cap = 0.07 * 100000 = 7000
        # max_position = min(10000, 7000) = 7000
        # target = min(7000 * 0.8, 10000, 7000) = 5600
        # qty = 5600 / 100 = 56
        assert orders[0].qty == 56.0

    def test_normal_position_for_low_vol_stock(self):
        """Low-volatility stocks should get normal-sized positions."""
        vol_sizer = VolatilitySizer()
        engine = StrategyEngine(
            config=_make_config(),
            volatility_sizer=vol_sizer,
        )
        portfolio = _make_portfolio(equity=100_000.0, cash=20_000.0)
        # atr_pct = (0.3/100)*100 = 0.3 -> low -> cap = 0.20
        technicals = {"AAPL": {"current_price": 100.0, "atr_pct": 0.3}}
        signals = [_make_signal(signal=SignalType.BUY, confidence=0.8)]

        orders = engine.generate_orders(signals, portfolio, technicals)
        assert len(orders) == 1
        # vol cap = 0.20 * 100000 = 20000
        # max_position = min(10000, 20000) = 10000 (config cap is tighter)
        # target = min(10000 * 0.8, 10000, 10000) = 8000
        # qty = 8000 / 100 = 80
        assert orders[0].qty == 80.0


class TestLimitOrders:
    def test_generates_limit_order_for_buy(self):
        data_config = _make_data_config(use_limit_orders=True, slippage_tolerance_pct=0.002)
        engine = StrategyEngine(
            config=_make_config(),
            data_config=data_config,
        )
        portfolio = _make_portfolio(
            positions=[_make_position(symbol="AAPL", current_price=160.0)],
        )
        signals = [_make_signal(signal=SignalType.BUY, confidence=0.8)]

        orders = engine.generate_orders(signals, portfolio)
        assert len(orders) == 1
        assert orders[0].order_type == OrderType.LIMIT
        assert orders[0].limit_price is not None
        # limit_price = 160 * (1 + 0.002) = 160.32
        assert orders[0].limit_price == 160.32

    def test_generates_limit_order_for_sell(self):
        data_config = _make_data_config(use_limit_orders=True, slippage_tolerance_pct=0.002)
        engine = StrategyEngine(
            config=_make_config(),
            data_config=data_config,
        )
        portfolio = _make_portfolio(
            positions=[_make_position(symbol="AAPL", current_price=160.0)],
        )
        signals = [_make_signal(signal=SignalType.SELL, confidence=0.5)]

        orders = engine.generate_orders(signals, portfolio)
        assert len(orders) == 1
        assert orders[0].order_type == OrderType.LIMIT
        assert orders[0].limit_price is not None
        # limit_price = 160 * (1 - 0.002) = 159.68
        assert orders[0].limit_price == 159.68

    def test_market_order_when_limit_disabled(self):
        data_config = _make_data_config(use_limit_orders=False)
        engine = StrategyEngine(
            config=_make_config(),
            data_config=data_config,
        )
        portfolio = _make_portfolio(
            positions=[_make_position(symbol="AAPL", current_price=160.0)],
        )
        signals = [_make_signal(signal=SignalType.BUY, confidence=0.8)]

        orders = engine.generate_orders(signals, portfolio)
        assert len(orders) == 1
        assert orders[0].order_type == OrderType.MARKET
        assert orders[0].limit_price is None


class TestPositionScaling:
    def test_scale_add_uses_half_position(self):
        """scale_action='add' should use 1/2 of max position size."""
        data_config = _make_data_config(enable_position_scaling=True)
        engine = StrategyEngine(
            config=_make_config(),
            data_config=data_config,
        )
        portfolio = _make_portfolio(
            equity=100_000.0,
            cash=20_000.0,
            positions=[_make_position(symbol="AAPL", qty=5.0, current_price=160.0)],
        )
        signals = [
            _make_signal(signal=SignalType.BUY, confidence=0.8, scale_action="add"),
        ]

        orders = engine.generate_orders(signals, portfolio)
        assert len(orders) == 1
        # With scaling: scale_factor = 0.50
        # max_position = 10000
        # current_weight = 800/100000 = 0.008
        # remaining = 0.10 - 0.008 = 0.092
        # target = min(10000 * 0.8 * 1.0 * 0.50, 10000, 9200) = 4000
        # qty = 4000 / 160 = 25.0
        assert orders[0].qty == 25.0

    def test_initial_entry_uses_full_position(self):
        """New position with scaling enabled should use full position size."""
        data_config = _make_data_config(enable_position_scaling=True)
        engine = StrategyEngine(
            config=_make_config(),
            data_config=data_config,
        )
        portfolio = _make_portfolio(equity=100_000.0, cash=20_000.0)
        technicals = {"AAPL": {"current_price": 100.0}}
        signals = [_make_signal(signal=SignalType.BUY, confidence=0.8)]

        orders = engine.generate_orders(signals, portfolio, technicals)
        assert len(orders) == 1
        # With scaling, initial entry: scale_factor = 1.0 (full position)
        # target = min(10000 * 0.8 * 1.0 * 1.0, 10000, 10000) = 8000
        # qty = 8000 / 100 = 80.0
        assert orders[0].qty == 80.0

    def test_partial_exit_sells_third(self):
        """scale_action='partial_exit' should sell 1/3 of position."""
        data_config = _make_data_config(enable_position_scaling=True)
        engine = StrategyEngine(
            config=_make_config(),
            data_config=data_config,
        )
        portfolio = _make_portfolio(
            positions=[_make_position(symbol="AAPL", qty=30.0, current_price=160.0)],
        )
        signals = [
            _make_signal(
                signal=SignalType.SELL,
                confidence=0.8,
                scale_action="partial_exit",
            ),
        ]

        orders = engine.generate_orders(signals, portfolio)
        assert len(orders) == 1
        assert orders[0].side == "sell"
        # partial_exit -> sell 1/3 = 30 * 0.33 = 9.9
        assert orders[0].qty == 9.9

    def test_full_sell_without_scaling(self):
        """Without scaling, sell qty should be proportional to confidence."""
        data_config = _make_data_config(enable_position_scaling=False)
        engine = StrategyEngine(
            config=_make_config(),
            data_config=data_config,
        )
        portfolio = _make_portfolio(
            positions=[_make_position(symbol="AAPL", qty=30.0, current_price=160.0)],
        )
        signals = [_make_signal(signal=SignalType.SELL, confidence=0.5)]

        orders = engine.generate_orders(signals, portfolio)
        assert len(orders) == 1
        assert orders[0].qty == 15.0  # 30 * 0.5
