"""Tests for the drawdown circuit breaker."""

from __future__ import annotations

from financial_agent.risk.drawdown import DrawdownAction, DrawdownCircuitBreaker


class TestDrawdownCircuitBreaker:
    def test_no_drawdown_returns_normal(self):
        breaker = DrawdownCircuitBreaker(peak_equity=100_000.0)
        action = breaker.get_action(100_000.0)
        assert action == DrawdownAction.NORMAL

    def test_small_drawdown_still_normal(self):
        breaker = DrawdownCircuitBreaker(peak_equity=100_000.0)
        # 3% drawdown, below the 5% threshold
        action = breaker.get_action(97_000.0)
        assert action == DrawdownAction.NORMAL

    def test_5pct_drawdown_triggers_reduce_size(self):
        breaker = DrawdownCircuitBreaker(peak_equity=100_000.0)
        # 5% drawdown (exactly at threshold)
        action = breaker.get_action(95_000.0)
        assert action == DrawdownAction.REDUCE_SIZE

    def test_7pct_drawdown_triggers_reduce_size(self):
        breaker = DrawdownCircuitBreaker(peak_equity=100_000.0)
        # 7% drawdown (between 5% and 10%)
        action = breaker.get_action(93_000.0)
        assert action == DrawdownAction.REDUCE_SIZE

    def test_10pct_drawdown_triggers_buys_blocked(self):
        breaker = DrawdownCircuitBreaker(peak_equity=100_000.0)
        action = breaker.get_action(90_000.0)
        assert action == DrawdownAction.BUYS_ONLY_BLOCKED

    def test_15pct_drawdown_triggers_derisk(self):
        breaker = DrawdownCircuitBreaker(peak_equity=100_000.0)
        action = breaker.get_action(85_000.0)
        assert action == DrawdownAction.DERISK

    def test_20pct_drawdown_triggers_halt(self):
        breaker = DrawdownCircuitBreaker(peak_equity=100_000.0)
        action = breaker.get_action(80_000.0)
        assert action == DrawdownAction.HALT

    def test_25pct_drawdown_triggers_halt(self):
        breaker = DrawdownCircuitBreaker(peak_equity=100_000.0)
        action = breaker.get_action(75_000.0)
        assert action == DrawdownAction.HALT


class TestSizeMultiplier:
    def test_normal_returns_1(self):
        breaker = DrawdownCircuitBreaker(peak_equity=100_000.0)
        mult = breaker.size_multiplier(100_000.0)
        assert mult == 1.0

    def test_reduce_size_returns_half(self):
        breaker = DrawdownCircuitBreaker(peak_equity=100_000.0)
        mult = breaker.size_multiplier(95_000.0)
        assert mult == 0.5

    def test_buys_blocked_returns_zero(self):
        breaker = DrawdownCircuitBreaker(peak_equity=100_000.0)
        mult = breaker.size_multiplier(90_000.0)
        assert mult == 0.0

    def test_derisk_returns_zero(self):
        breaker = DrawdownCircuitBreaker(peak_equity=100_000.0)
        mult = breaker.size_multiplier(85_000.0)
        assert mult == 0.0

    def test_halt_returns_zero(self):
        breaker = DrawdownCircuitBreaker(peak_equity=100_000.0)
        mult = breaker.size_multiplier(80_000.0)
        assert mult == 0.0


class TestUpdatePeak:
    def test_updates_when_equity_increases(self):
        breaker = DrawdownCircuitBreaker(peak_equity=100_000.0)
        breaker.update_peak(110_000.0)
        # After updating peak, current drawdown at 110k should be 0
        assert breaker.current_drawdown(110_000.0) == 0.0
        # And at 100k should be ~9.09% drawdown from new peak of 110k
        dd = breaker.current_drawdown(100_000.0)
        assert abs(dd - 10_000.0 / 110_000.0) < 1e-9

    def test_does_not_update_when_equity_decreases(self):
        breaker = DrawdownCircuitBreaker(peak_equity=100_000.0)
        breaker.update_peak(90_000.0)
        # Peak should still be 100k; drawdown at 90k should be 10%
        dd = breaker.current_drawdown(90_000.0)
        assert abs(dd - 0.10) < 1e-9


class TestCurrentDrawdown:
    def test_no_drawdown(self):
        breaker = DrawdownCircuitBreaker(peak_equity=100_000.0)
        assert breaker.current_drawdown(100_000.0) == 0.0

    def test_above_peak_returns_zero(self):
        breaker = DrawdownCircuitBreaker(peak_equity=100_000.0)
        # Above peak, drawdown is clamped to 0
        assert breaker.current_drawdown(110_000.0) == 0.0

    def test_ten_percent_drawdown(self):
        breaker = DrawdownCircuitBreaker(peak_equity=100_000.0)
        dd = breaker.current_drawdown(90_000.0)
        assert abs(dd - 0.10) < 1e-9

    def test_zero_peak_returns_zero(self):
        breaker = DrawdownCircuitBreaker(peak_equity=0.0)
        assert breaker.current_drawdown(50_000.0) == 0.0


class TestIsRecovered:
    def test_recovered_when_drawdown_below_5pct(self):
        breaker = DrawdownCircuitBreaker(peak_equity=100_000.0)
        # 3% drawdown is below the 5% recovery threshold
        assert breaker.is_recovered(97_000.0) is True

    def test_not_recovered_when_drawdown_above_5pct(self):
        breaker = DrawdownCircuitBreaker(peak_equity=100_000.0)
        # 10% drawdown is above the recovery threshold
        assert breaker.is_recovered(90_000.0) is False

    def test_recovered_at_peak(self):
        breaker = DrawdownCircuitBreaker(peak_equity=100_000.0)
        assert breaker.is_recovered(100_000.0) is True

    def test_not_recovered_at_exactly_5pct(self):
        breaker = DrawdownCircuitBreaker(peak_equity=100_000.0)
        # Exactly at 5% is not strictly less than threshold
        assert breaker.is_recovered(95_000.0) is False


class TestRecoveryThreshold:
    def test_default_recovery_threshold(self):
        breaker = DrawdownCircuitBreaker(peak_equity=100_000.0)
        assert breaker.recovery_threshold() == 0.05


class TestCustomTiers:
    def test_custom_tiers(self):
        custom_tiers = {
            0.03: DrawdownAction.REDUCE_SIZE,
            0.08: DrawdownAction.HALT,
        }
        breaker = DrawdownCircuitBreaker(peak_equity=100_000.0, drawdown_tiers=custom_tiers)
        # 3% drawdown with custom tiers
        assert breaker.get_action(97_000.0) == DrawdownAction.REDUCE_SIZE
        # 8% drawdown jumps to HALT with custom tiers
        assert breaker.get_action(92_000.0) == DrawdownAction.HALT
