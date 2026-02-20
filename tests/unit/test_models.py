"""Tests for portfolio data models."""

from financial_agent.portfolio.models import (
    PortfolioSnapshot,
    Position,
    SignalType,
    TradeOrder,
    TradeSignal,
)


def _make_position(**overrides):
    defaults = {
        "symbol": "AAPL",
        "qty": 10.0,
        "avg_entry_price": 150.0,
        "current_price": 160.0,
        "market_value": 1600.0,
        "unrealized_pl": 100.0,
        "unrealized_pl_pct": 0.0667,
    }
    defaults.update(overrides)
    return Position(**defaults)


def _make_portfolio(positions=None, equity=10000.0, cash=2000.0):
    return PortfolioSnapshot(
        equity=equity,
        cash=cash,
        buying_power=cash * 2,
        positions=positions or [],
    )


class TestPosition:
    def test_create_position(self):
        pos = _make_position()
        assert pos.symbol == "AAPL"
        assert pos.qty == 10.0
        assert pos.side == "long"

    def test_position_with_loss(self):
        pos = _make_position(unrealized_pl=-50.0, unrealized_pl_pct=-0.033)
        assert pos.unrealized_pl < 0


class TestPortfolioSnapshot:
    def test_empty_portfolio(self):
        port = _make_portfolio()
        assert port.position_count == 0
        assert port.total_unrealized_pl == 0.0

    def test_portfolio_with_positions(self):
        positions = [
            _make_position(symbol="AAPL", market_value=1600.0, unrealized_pl=100.0),
            _make_position(symbol="MSFT", market_value=2400.0, unrealized_pl=-50.0),
        ]
        port = _make_portfolio(positions=positions)
        assert port.position_count == 2
        assert port.total_unrealized_pl == 50.0

    def test_get_position(self):
        port = _make_portfolio(positions=[_make_position(symbol="AAPL")])
        assert port.get_position("AAPL") is not None
        assert port.get_position("MSFT") is None

    def test_position_weight(self):
        port = _make_portfolio(
            positions=[_make_position(symbol="AAPL", market_value=1000.0)],
            equity=10000.0,
        )
        assert port.position_weight("AAPL") == 0.1
        assert port.position_weight("MSFT") == 0.0


class TestTradeSignal:
    def test_buy_signal(self):
        signal = TradeSignal(
            symbol="AAPL",
            signal=SignalType.BUY,
            confidence=0.75,
            reason="Strong momentum",
        )
        assert signal.signal == SignalType.BUY
        assert signal.confidence == 0.75

    def test_confidence_bounds(self):
        import pytest

        with pytest.raises(Exception):
            TradeSignal(
                symbol="AAPL",
                signal=SignalType.BUY,
                confidence=1.5,
                reason="Invalid",
            )


class TestTradeOrder:
    def test_create_order(self):
        order = TradeOrder(
            symbol="AAPL",
            side="buy",
            qty=5.0,
            reason="AI recommendation",
            signal_confidence=0.8,
        )
        assert order.symbol == "AAPL"
        assert order.qty == 5.0
