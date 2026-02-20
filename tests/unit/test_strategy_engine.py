"""Tests for the strategy engine order generation."""

from financial_agent.config import TradingConfig
from financial_agent.portfolio.models import (
    PortfolioSnapshot,
    Position,
    SignalType,
    TradeSignal,
)
from financial_agent.strategy.engine import StrategyEngine


def _make_config(**overrides):
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


def _make_portfolio(positions=None, equity=100000.0, cash=20000.0):
    return PortfolioSnapshot(
        equity=equity,
        cash=cash,
        buying_power=cash * 2,
        positions=positions or [],
    )


def _make_signal(symbol="AAPL", signal=SignalType.BUY, confidence=0.7, reason="Test"):
    return TradeSignal(symbol=symbol, signal=signal, confidence=confidence, reason=reason)


class TestStrategyEngine:
    def test_hold_signals_produce_no_orders(self):
        engine = StrategyEngine(_make_config())
        signals = [_make_signal(signal=SignalType.HOLD)]
        orders = engine.generate_orders(signals, _make_portfolio())
        assert len(orders) == 0

    def test_buy_signal_produces_order(self):
        engine = StrategyEngine(_make_config())
        portfolio = _make_portfolio(
            positions=[
                Position(
                    symbol="AAPL",
                    qty=10,
                    avg_entry_price=150.0,
                    current_price=160.0,
                    market_value=1600.0,
                    unrealized_pl=100.0,
                    unrealized_pl_pct=0.0667,
                )
            ]
        )
        signals = [_make_signal(signal=SignalType.BUY, confidence=0.8)]
        orders = engine.generate_orders(signals, portfolio)
        assert len(orders) == 1
        assert orders[0].side == "buy"
        assert orders[0].symbol == "AAPL"

    def test_sell_signal_without_position(self):
        engine = StrategyEngine(_make_config())
        signals = [_make_signal(signal=SignalType.SELL)]
        orders = engine.generate_orders(signals, _make_portfolio())
        assert len(orders) == 0

    def test_sell_signal_with_position(self):
        engine = StrategyEngine(_make_config())
        portfolio = _make_portfolio(
            positions=[
                Position(
                    symbol="AAPL",
                    qty=10,
                    avg_entry_price=150.0,
                    current_price=160.0,
                    market_value=1600.0,
                    unrealized_pl=100.0,
                    unrealized_pl_pct=0.0667,
                )
            ]
        )
        signals = [_make_signal(signal=SignalType.SELL, confidence=0.5)]
        orders = engine.generate_orders(signals, portfolio)
        assert len(orders) == 1
        assert orders[0].side == "sell"
        assert orders[0].qty == 5.0  # 10 * 0.5 confidence

    def test_daily_trade_limit(self):
        engine = StrategyEngine(_make_config(max_daily_trades=2))
        portfolio = _make_portfolio(
            positions=[
                Position(
                    symbol=sym,
                    qty=10,
                    avg_entry_price=100.0,
                    current_price=110.0,
                    market_value=1100.0,
                    unrealized_pl=100.0,
                    unrealized_pl_pct=0.10,
                )
                for sym in ["AAPL", "MSFT", "GOOGL"]
            ]
        )
        signals = [
            _make_signal(symbol="AAPL", signal=SignalType.SELL, confidence=0.9),
            _make_signal(symbol="MSFT", signal=SignalType.SELL, confidence=0.5),
            _make_signal(symbol="GOOGL", signal=SignalType.SELL, confidence=0.7),
        ]
        orders = engine.generate_orders(signals, portfolio)
        assert len(orders) == 2
        # Should keep highest confidence orders
        assert orders[0].signal_confidence == 0.9

    def test_buy_respects_cash_reserve(self):
        engine = StrategyEngine(_make_config(min_cash_reserve_pct=0.50))
        # Cash is 20% of equity but reserve is 50%, so no buys allowed
        portfolio = _make_portfolio(equity=100000.0, cash=20000.0)
        signals = [_make_signal(signal=SignalType.BUY)]
        orders = engine.generate_orders(signals, portfolio)
        assert len(orders) == 0
