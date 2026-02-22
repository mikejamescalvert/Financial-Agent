"""Volatility-based position sizing.

Adjusts individual position sizes so that each position contributes roughly
the same dollar risk (measured in ATR) to the portfolio.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger()

_DEFAULT_VOLATILITY_CAPS: dict[str, float] = {
    "low": 0.12,
    "medium": 0.08,
    "high": 0.05,
    "very_high": 0.03,
}

_VOL_TIER_NUMERIC: dict[str, float] = {
    "low": 0.0,
    "medium": 1.0,
    "high": 2.0,
    "very_high": 3.0,
}


class VolatilitySizer:
    """Size positions according to per-symbol volatility (ATR).

    Parameters
    ----------
    risk_budget_pct:
        Target risk per position as a fraction of total equity (e.g. 0.02 = 2%).
    volatility_caps:
        Maximum position size (fraction of equity) per volatility tier.
        Keys must be ``"low"``, ``"medium"``, ``"high"``, ``"very_high"``.
    """

    def __init__(
        self,
        risk_budget_pct: float = 0.02,
        volatility_caps: dict[str, float] | None = None,
    ) -> None:
        self._risk_budget_pct = risk_budget_pct
        self._caps = (
            volatility_caps if volatility_caps is not None else dict(_DEFAULT_VOLATILITY_CAPS)
        )
        log.info(
            "volatility_sizer_init",
            risk_budget_pct=risk_budget_pct,
            caps=self._caps,
        )

    # ------------------------------------------------------------------
    # Volatility classification
    # ------------------------------------------------------------------

    def classify_volatility(self, atr_pct: float) -> str:
        """Classify a symbol's volatility tier from its ATR-as-%-of-price.

        Parameters
        ----------
        atr_pct:
            ``(atr_14 / current_price) * 100`` -- ATR expressed as a
            percentage of the current price.

        Returns
        -------
        One of ``"low"``, ``"medium"``, ``"high"``, ``"very_high"``.
        """
        if atr_pct < 1.0:
            return "low"
        if atr_pct <= 3.0:
            return "medium"
        if atr_pct <= 5.0:
            return "high"
        return "very_high"

    def max_position_pct(self, atr_pct: float) -> float:
        """Return the maximum position size (fraction of equity) for the given ATR %."""
        tier = self.classify_volatility(atr_pct)
        return self._caps.get(tier, self._caps.get("medium", 0.08))

    # ------------------------------------------------------------------
    # Position sizing
    # ------------------------------------------------------------------

    def size_position(self, equity: float, price: float, atr: float) -> float:
        """Calculate the number of shares to buy based on the risk budget.

        The core idea: one ATR move should equal the risk budget in dollar
        terms.  The result is then capped so the total position value does
        not exceed the volatility-tier ceiling.

        Parameters
        ----------
        equity:
            Total portfolio equity.
        price:
            Current price per share.
        atr:
            14-period Average True Range (dollar value).

        Returns
        -------
        Number of shares, rounded to 2 decimal places.
        """
        if atr <= 0 or price <= 0 or equity <= 0:
            return 0.0

        risk_amount = equity * self._risk_budget_pct
        qty = risk_amount / atr

        # Cap by volatility tier
        atr_pct = (atr / price) * 100
        max_value = self.max_position_pct(atr_pct) * equity
        position_value = qty * price

        if position_value > max_value:
            qty = max_value / price

        return round(qty, 2)

    # ------------------------------------------------------------------
    # Bulk context
    # ------------------------------------------------------------------

    def get_sizing_context(
        self,
        technicals: dict[str, dict[str, float]],
    ) -> dict[str, dict[str, float]]:
        """Build a sizing-context dict from pre-computed technicals.

        For each symbol the returned dict contains:

        * ``atr_pct`` -- ATR as a percentage of current price.
        * ``vol_tier_numeric`` -- 0 (low) through 3 (very_high).
        * ``max_position_pct`` -- maximum position fraction of equity.

        Symbols missing ``atr_14`` or ``current_price`` are skipped.
        """
        context: dict[str, dict[str, float]] = {}
        for symbol, indicators in technicals.items():
            atr_14 = indicators.get("atr_14")
            current_price = indicators.get("current_price")
            if atr_14 is None or current_price is None or current_price <= 0:
                log.debug(
                    "volatility_skip_symbol",
                    symbol=symbol,
                    reason="missing atr_14 or current_price",
                )
                continue

            atr_pct = (atr_14 / current_price) * 100
            tier = self.classify_volatility(atr_pct)
            context[symbol] = {
                "atr_pct": round(atr_pct, 4),
                "vol_tier_numeric": _VOL_TIER_NUMERIC.get(tier, 1.0),
                "max_position_pct": self.max_position_pct(atr_pct),
            }
        return context
