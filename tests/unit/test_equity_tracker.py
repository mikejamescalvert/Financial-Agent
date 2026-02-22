"""Tests for equity history tracking and analysis."""

from __future__ import annotations

import tempfile

from financial_agent.persistence.equity_tracker import EquityTracker


class TestRecord:
    def test_updates_peak_equity(self):
        data_dir = tempfile.mkdtemp()
        tracker = EquityTracker(data_dir=data_dir)
        tracker.record(100_000.0, cash=20_000.0, positions_count=5)
        assert tracker.peak() == 100_000.0

        tracker.record(110_000.0, cash=22_000.0, positions_count=5)
        assert tracker.peak() == 110_000.0

    def test_peak_does_not_decrease(self):
        data_dir = tempfile.mkdtemp()
        tracker = EquityTracker(data_dir=data_dir)
        tracker.record(100_000.0, cash=20_000.0, positions_count=5)
        tracker.record(90_000.0, cash=18_000.0, positions_count=5)
        assert tracker.peak() == 100_000.0

    def test_daily_return_first_record(self):
        data_dir = tempfile.mkdtemp()
        tracker = EquityTracker(data_dir=data_dir)
        tracker.record(100_000.0, cash=20_000.0, positions_count=5)
        returns = tracker.daily_returns(days=1)
        assert len(returns) == 1
        assert returns[0] == 0.0  # First record has no prior, so 0%

    def test_daily_return_subsequent_records(self):
        data_dir = tempfile.mkdtemp()
        tracker = EquityTracker(data_dir=data_dir)
        tracker.record(100_000.0, cash=20_000.0, positions_count=5)
        tracker.record(102_000.0, cash=20_400.0, positions_count=5)
        returns = tracker.daily_returns(days=2)
        assert len(returns) == 2
        assert returns[0] == 0.0
        assert abs(returns[1] - 0.02) < 1e-9

    def test_persists_across_instances(self):
        data_dir = tempfile.mkdtemp()
        tracker1 = EquityTracker(data_dir=data_dir)
        tracker1.record(100_000.0, cash=20_000.0, positions_count=5)

        tracker2 = EquityTracker(data_dir=data_dir)
        assert tracker2.peak() == 100_000.0
        returns = tracker2.daily_returns(days=1)
        assert len(returns) == 1


class TestCurrentDrawdown:
    def test_no_history_returns_zero(self):
        data_dir = tempfile.mkdtemp()
        tracker = EquityTracker(data_dir=data_dir)
        assert tracker.current_drawdown(50_000.0) == 0.0

    def test_at_peak_returns_zero(self):
        data_dir = tempfile.mkdtemp()
        tracker = EquityTracker(data_dir=data_dir)
        tracker.record(100_000.0, cash=20_000.0, positions_count=5)
        assert tracker.current_drawdown(100_000.0) == 0.0

    def test_below_peak_calculates_correctly(self):
        data_dir = tempfile.mkdtemp()
        tracker = EquityTracker(data_dir=data_dir)
        tracker.record(100_000.0, cash=20_000.0, positions_count=5)
        dd = tracker.current_drawdown(90_000.0)
        assert abs(dd - 0.10) < 1e-9

    def test_above_peak_returns_negative(self):
        data_dir = tempfile.mkdtemp()
        tracker = EquityTracker(data_dir=data_dir)
        tracker.record(100_000.0, cash=20_000.0, positions_count=5)
        # Formula: (peak - equity) / peak = (100k - 110k) / 100k = -0.1
        dd = tracker.current_drawdown(110_000.0)
        assert dd < 0


class TestDailyReturns:
    def test_returns_correct_window(self):
        data_dir = tempfile.mkdtemp()
        tracker = EquityTracker(data_dir=data_dir)
        for eq in [100_000.0, 101_000.0, 102_000.0, 103_000.0, 104_000.0]:
            tracker.record(eq, cash=20_000.0, positions_count=5)

        returns = tracker.daily_returns(days=3)
        assert len(returns) == 3  # Last 3 entries

    def test_returns_all_if_window_larger(self):
        data_dir = tempfile.mkdtemp()
        tracker = EquityTracker(data_dir=data_dir)
        tracker.record(100_000.0, cash=20_000.0, positions_count=5)
        tracker.record(101_000.0, cash=20_000.0, positions_count=5)

        returns = tracker.daily_returns(days=30)
        assert len(returns) == 2

    def test_empty_history(self):
        data_dir = tempfile.mkdtemp()
        tracker = EquityTracker(data_dir=data_dir)
        returns = tracker.daily_returns(days=30)
        assert returns == []


class TestMaxDrawdown:
    def test_no_history_returns_zero(self):
        data_dir = tempfile.mkdtemp()
        tracker = EquityTracker(data_dir=data_dir)
        assert tracker.max_drawdown(days=90) == 0.0

    def test_rising_market_zero_drawdown(self):
        data_dir = tempfile.mkdtemp()
        tracker = EquityTracker(data_dir=data_dir)
        for eq in [100_000.0, 101_000.0, 102_000.0, 103_000.0]:
            tracker.record(eq, cash=20_000.0, positions_count=5)
        assert tracker.max_drawdown(days=90) == 0.0

    def test_drawdown_calculation(self):
        data_dir = tempfile.mkdtemp()
        tracker = EquityTracker(data_dir=data_dir)
        # Peak at 100k, drop to 90k = 10% drawdown
        for eq in [90_000.0, 95_000.0, 100_000.0, 95_000.0, 90_000.0]:
            tracker.record(eq, cash=20_000.0, positions_count=5)
        max_dd = tracker.max_drawdown(days=90)
        assert abs(max_dd - 0.10) < 1e-9

    def test_drawdown_with_recovery(self):
        data_dir = tempfile.mkdtemp()
        tracker = EquityTracker(data_dir=data_dir)
        # Rise to 100k, drop to 85k (15% dd), recover to 105k, drop to 95k (9.5% dd)
        for eq in [80_000.0, 100_000.0, 85_000.0, 105_000.0, 95_000.0]:
            tracker.record(eq, cash=20_000.0, positions_count=5)
        max_dd = tracker.max_drawdown(days=90)
        assert abs(max_dd - 0.15) < 1e-9


class TestFormatForPrompt:
    def test_no_history(self):
        data_dir = tempfile.mkdtemp()
        tracker = EquityTracker(data_dir=data_dir)
        result = tracker.format_for_prompt()
        assert result == "No equity history available."

    def test_with_history(self):
        data_dir = tempfile.mkdtemp()
        tracker = EquityTracker(data_dir=data_dir)
        tracker.record(100_000.0, cash=20_000.0, positions_count=5)
        tracker.record(102_000.0, cash=20_400.0, positions_count=5)

        result = tracker.format_for_prompt()
        assert "Equity Performance" in result
        assert "Peak Equity" in result
        assert "Current Equity" in result
        assert "Current Drawdown" in result
        assert "7-Day Return" in result
        assert "30-Day Return" in result
        assert "Max Drawdown (90d)" in result

    def test_format_includes_correct_values(self):
        data_dir = tempfile.mkdtemp()
        tracker = EquityTracker(data_dir=data_dir)
        tracker.record(100_000.0, cash=20_000.0, positions_count=5)

        result = tracker.format_for_prompt()
        assert "$100,000.00" in result
