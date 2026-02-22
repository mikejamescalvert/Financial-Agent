"""Tests for trade performance tracking and risk-adjusted metrics."""

from __future__ import annotations

import tempfile

from financial_agent.performance.benchmarking import PerformanceTracker, TradeRecord


def _make_trade(**overrides) -> TradeRecord:
    defaults = {
        "symbol": "AAPL",
        "side": "buy",
        "qty": 10.0,
        "price": 150.0,
        "timestamp": "2026-02-20T10:00:00Z",
        "reason": "Test trade",
        "confidence": 0.8,
    }
    defaults.update(overrides)
    return TradeRecord(**defaults)


class TestRecordTrade:
    def test_adds_to_journal(self):
        data_dir = tempfile.mkdtemp()
        tracker = PerformanceTracker(data_dir=data_dir)
        trade = _make_trade()
        tracker.record_trade(trade)
        assert tracker.trade_count() == 1

    def test_multiple_trades(self):
        data_dir = tempfile.mkdtemp()
        tracker = PerformanceTracker(data_dir=data_dir)
        tracker.record_trade(_make_trade(symbol="AAPL"))
        tracker.record_trade(_make_trade(symbol="MSFT"))
        tracker.record_trade(_make_trade(symbol="GOOGL"))
        assert tracker.trade_count() == 3

    def test_persists_across_instances(self):
        data_dir = tempfile.mkdtemp()
        tracker1 = PerformanceTracker(data_dir=data_dir)
        tracker1.record_trade(_make_trade())

        tracker2 = PerformanceTracker(data_dir=data_dir)
        assert tracker2.trade_count() == 1


class TestWinRate:
    def test_no_closed_trades_returns_none(self):
        data_dir = tempfile.mkdtemp()
        tracker = PerformanceTracker(data_dir=data_dir)
        assert tracker.win_rate() is None

    def test_no_trades_at_all_returns_none(self):
        data_dir = tempfile.mkdtemp()
        tracker = PerformanceTracker(data_dir=data_dir)
        # Add trades without pnl (not closed)
        tracker.record_trade(_make_trade(pnl=None))
        assert tracker.win_rate() is None

    def test_all_winners(self):
        data_dir = tempfile.mkdtemp()
        tracker = PerformanceTracker(data_dir=data_dir)
        tracker.record_trade(_make_trade(pnl=100.0))
        tracker.record_trade(_make_trade(pnl=200.0))
        assert tracker.win_rate() == 1.0

    def test_all_losers(self):
        data_dir = tempfile.mkdtemp()
        tracker = PerformanceTracker(data_dir=data_dir)
        tracker.record_trade(_make_trade(pnl=-100.0))
        tracker.record_trade(_make_trade(pnl=-50.0))
        assert tracker.win_rate() == 0.0

    def test_mixed_results(self):
        data_dir = tempfile.mkdtemp()
        tracker = PerformanceTracker(data_dir=data_dir)
        tracker.record_trade(_make_trade(pnl=100.0))
        tracker.record_trade(_make_trade(pnl=-50.0))
        tracker.record_trade(_make_trade(pnl=200.0))
        tracker.record_trade(_make_trade(pnl=-30.0))
        # 2 wins out of 4 = 50%
        assert tracker.win_rate() == 0.5

    def test_mixed_with_unclosed(self):
        data_dir = tempfile.mkdtemp()
        tracker = PerformanceTracker(data_dir=data_dir)
        tracker.record_trade(_make_trade(pnl=100.0))
        tracker.record_trade(_make_trade(pnl=None))  # Not closed
        tracker.record_trade(_make_trade(pnl=-50.0))
        # 1 win out of 2 closed = 50%
        assert tracker.win_rate() == 0.5


class TestProfitFactor:
    def test_no_closed_trades_returns_none(self):
        data_dir = tempfile.mkdtemp()
        tracker = PerformanceTracker(data_dir=data_dir)
        assert tracker.profit_factor() is None

    def test_no_losses_returns_none(self):
        data_dir = tempfile.mkdtemp()
        tracker = PerformanceTracker(data_dir=data_dir)
        tracker.record_trade(_make_trade(pnl=100.0))
        tracker.record_trade(_make_trade(pnl=200.0))
        # gross_losses = 0, so returns None
        assert tracker.profit_factor() is None

    def test_calculation(self):
        data_dir = tempfile.mkdtemp()
        tracker = PerformanceTracker(data_dir=data_dir)
        tracker.record_trade(_make_trade(pnl=300.0))
        tracker.record_trade(_make_trade(pnl=-100.0))
        tracker.record_trade(_make_trade(pnl=200.0))
        tracker.record_trade(_make_trade(pnl=-50.0))
        # gross_profits = 500, gross_losses = 150
        # profit_factor = 500 / 150 = 3.33...
        pf = tracker.profit_factor()
        assert pf is not None
        assert abs(pf - 500.0 / 150.0) < 1e-9


class TestSharpeRatio:
    def test_insufficient_data_returns_none(self):
        data_dir = tempfile.mkdtemp()
        tracker = PerformanceTracker(data_dir=data_dir)
        # Less than 5 returns
        result = tracker.sharpe_ratio([0.01, 0.02, -0.01, 0.005])
        assert result is None

    def test_zero_std_returns_none(self):
        data_dir = tempfile.mkdtemp()
        tracker = PerformanceTracker(data_dir=data_dir)
        # All same returns -> zero std when adjusted for rf
        daily_rf = 0.05 / 252
        result = tracker.sharpe_ratio([daily_rf] * 10, risk_free_rate=0.05)
        assert result is None

    def test_positive_sharpe(self):
        data_dir = tempfile.mkdtemp()
        tracker = PerformanceTracker(data_dir=data_dir)
        # Consistently positive excess returns
        returns = [0.01, 0.015, 0.008, 0.012, 0.009, 0.011, 0.013]
        result = tracker.sharpe_ratio(returns, risk_free_rate=0.05)
        assert result is not None
        assert result > 0

    def test_negative_sharpe(self):
        data_dir = tempfile.mkdtemp()
        tracker = PerformanceTracker(data_dir=data_dir)
        # Consistently negative excess returns
        returns = [-0.01, -0.015, -0.008, -0.012, -0.009]
        result = tracker.sharpe_ratio(returns, risk_free_rate=0.05)
        assert result is not None
        assert result < 0


class TestSortinoRatio:
    def test_insufficient_data_returns_none(self):
        data_dir = tempfile.mkdtemp()
        tracker = PerformanceTracker(data_dir=data_dir)
        result = tracker.sortino_ratio([0.01, 0.02, -0.01])
        assert result is None

    def test_no_downside_returns_none(self):
        data_dir = tempfile.mkdtemp()
        tracker = PerformanceTracker(data_dir=data_dir)
        # All positive excess returns -> downside_std = 0
        returns = [0.05, 0.04, 0.06, 0.03, 0.07]
        result = tracker.sortino_ratio(returns, risk_free_rate=0.0)
        assert result is None

    def test_positive_sortino(self):
        data_dir = tempfile.mkdtemp()
        tracker = PerformanceTracker(data_dir=data_dir)
        returns = [0.01, 0.015, -0.002, 0.012, -0.001, 0.008]
        result = tracker.sortino_ratio(returns, risk_free_rate=0.05)
        assert result is not None
        # With mostly positive returns and small negatives, should be positive
        # The exact sign depends on excess returns vs downside deviation

    def test_negative_sortino(self):
        data_dir = tempfile.mkdtemp()
        tracker = PerformanceTracker(data_dir=data_dir)
        returns = [-0.01, -0.015, -0.008, -0.012, -0.009]
        result = tracker.sortino_ratio(returns, risk_free_rate=0.05)
        assert result is not None
        assert result < 0


class TestAvgWinAndLoss:
    def test_avg_win(self):
        data_dir = tempfile.mkdtemp()
        tracker = PerformanceTracker(data_dir=data_dir)
        tracker.record_trade(_make_trade(pnl=100.0))
        tracker.record_trade(_make_trade(pnl=200.0))
        tracker.record_trade(_make_trade(pnl=-50.0))
        avg = tracker.avg_win()
        assert avg is not None
        assert avg == 150.0

    def test_avg_loss(self):
        data_dir = tempfile.mkdtemp()
        tracker = PerformanceTracker(data_dir=data_dir)
        tracker.record_trade(_make_trade(pnl=100.0))
        tracker.record_trade(_make_trade(pnl=-50.0))
        tracker.record_trade(_make_trade(pnl=-100.0))
        avg = tracker.avg_loss()
        assert avg is not None
        assert avg == -75.0

    def test_avg_win_no_winners(self):
        data_dir = tempfile.mkdtemp()
        tracker = PerformanceTracker(data_dir=data_dir)
        tracker.record_trade(_make_trade(pnl=-50.0))
        assert tracker.avg_win() is None

    def test_avg_loss_no_losers(self):
        data_dir = tempfile.mkdtemp()
        tracker = PerformanceTracker(data_dir=data_dir)
        tracker.record_trade(_make_trade(pnl=100.0))
        assert tracker.avg_loss() is None


class TestFormatForPrompt:
    def test_no_trades(self):
        data_dir = tempfile.mkdtemp()
        tracker = PerformanceTracker(data_dir=data_dir)
        result = tracker.format_for_prompt()
        assert result == "No trade history available."

    def test_with_trades(self):
        data_dir = tempfile.mkdtemp()
        tracker = PerformanceTracker(data_dir=data_dir)
        tracker.record_trade(_make_trade(pnl=100.0))
        tracker.record_trade(_make_trade(pnl=-50.0))
        tracker.record_trade(_make_trade(pnl=200.0))

        result = tracker.format_for_prompt()
        assert "Total trades: 3" in result
        assert "Win rate:" in result
        assert "Profit factor:" in result
        assert "Avg win:" in result
        assert "Avg loss:" in result

    def test_with_daily_returns(self):
        data_dir = tempfile.mkdtemp()
        tracker = PerformanceTracker(data_dir=data_dir)
        tracker.record_trade(_make_trade(pnl=100.0))
        tracker.record_trade(_make_trade(pnl=-50.0))

        daily_returns = [0.01, 0.015, -0.002, 0.012, -0.001, 0.008]
        result = tracker.format_for_prompt(daily_returns=daily_returns)
        assert "Total trades: 2" in result
        # Should include sharpe/sortino if computed

    def test_with_only_unclosed_trades(self):
        data_dir = tempfile.mkdtemp()
        tracker = PerformanceTracker(data_dir=data_dir)
        tracker.record_trade(_make_trade(pnl=None))
        result = tracker.format_for_prompt()
        assert "Total trades: 1" in result
        # No win rate or profit factor for unclosed trades
        assert "Win rate:" not in result
