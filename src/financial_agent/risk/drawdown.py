"""Drawdown-based circuit breaker for portfolio protection.

Monitors portfolio drawdown from peak equity and triggers protective actions
at configurable threshold tiers.
"""

from __future__ import annotations

from enum import StrEnum

import structlog

log = structlog.get_logger()

_SIZE_MULTIPLIERS: dict[DrawdownAction, float] = {}


class DrawdownAction(StrEnum):
    """Actions triggered at various drawdown severity levels."""

    NORMAL = "normal"
    REDUCE_SIZE = "reduce_size"
    BUYS_ONLY_BLOCKED = "buys_only_blocked"
    DERISK = "derisk"
    HALT = "halt"


# Populate after class is defined to avoid forward reference issues.
_SIZE_MULTIPLIERS = {
    DrawdownAction.NORMAL: 1.0,
    DrawdownAction.REDUCE_SIZE: 0.5,
    DrawdownAction.BUYS_ONLY_BLOCKED: 0.0,
    DrawdownAction.DERISK: 0.0,
    DrawdownAction.HALT: 0.0,
}

_DEFAULT_TIERS: dict[float, DrawdownAction] = {
    0.05: DrawdownAction.REDUCE_SIZE,
    0.10: DrawdownAction.BUYS_ONLY_BLOCKED,
    0.15: DrawdownAction.DERISK,
    0.20: DrawdownAction.HALT,
}

_RECOVERY_THRESHOLD = 0.05


class DrawdownCircuitBreaker:
    """Monitors portfolio drawdown and triggers protective actions.

    Tracks peak equity and compares current equity to determine the drawdown
    percentage.  Each drawdown tier maps to a ``DrawdownAction`` that controls
    whether trading should proceed, be reduced, or halted entirely.
    """

    def __init__(
        self,
        peak_equity: float,
        drawdown_tiers: dict[float, DrawdownAction] | None = None,
    ) -> None:
        self._peak_equity = peak_equity
        self._tiers = drawdown_tiers if drawdown_tiers is not None else dict(_DEFAULT_TIERS)
        self._last_action = DrawdownAction.NORMAL
        log.info(
            "drawdown_breaker_init",
            peak_equity=peak_equity,
            tiers={str(k): v.value for k, v in self._tiers.items()},
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_peak(self, current_equity: float) -> None:
        """Update the high-water mark if *current_equity* exceeds it."""
        if current_equity > self._peak_equity:
            log.info(
                "peak_equity_updated",
                old_peak=self._peak_equity,
                new_peak=current_equity,
            )
            self._peak_equity = current_equity

    def current_drawdown(self, current_equity: float) -> float:
        """Return the current drawdown as a positive fraction (e.g. 0.12 = 12%)."""
        if self._peak_equity <= 0:
            return 0.0
        dd = (self._peak_equity - current_equity) / self._peak_equity
        return max(dd, 0.0)

    def get_action(self, current_equity: float) -> DrawdownAction:
        """Determine the protective action for the current equity level.

        Updates the peak first, then evaluates drawdown against configured
        tiers.  Logs whenever the action changes.
        """
        self.update_peak(current_equity)
        dd = self.current_drawdown(current_equity)
        action = DrawdownAction.NORMAL

        # Walk tiers in ascending order; the highest breached tier wins.
        for threshold in sorted(self._tiers):
            if dd >= threshold:
                action = self._tiers[threshold]

        if action != self._last_action:
            log.warning(
                "drawdown_action_changed",
                drawdown_pct=round(dd * 100, 2),
                previous=self._last_action.value,
                current=action.value,
                peak_equity=self._peak_equity,
                current_equity=current_equity,
            )
            self._last_action = action

        return action

    def size_multiplier(self, current_equity: float) -> float:
        """Return a position-sizing multiplier for the current drawdown state.

        * NORMAL -> 1.0
        * REDUCE_SIZE -> 0.5
        * BUYS_ONLY_BLOCKED / DERISK / HALT -> 0.0
        """
        action = self.get_action(current_equity)
        return _SIZE_MULTIPLIERS.get(action, 0.0)

    def recovery_threshold(self) -> float:
        """Return the drawdown level (fraction) below which trading resumes normally."""
        return _RECOVERY_THRESHOLD

    def is_recovered(self, current_equity: float) -> bool:
        """Return ``True`` if drawdown is below the recovery threshold."""
        return self.current_drawdown(current_equity) < self.recovery_threshold()
