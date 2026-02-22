"""Sector exposure management for concentration risk control.

Prevents over-allocation to any single GICS sector by comparing current
sector weights against configurable limits.
"""

from __future__ import annotations

from typing import TypedDict

import structlog

from financial_agent.data.sector_map import get_sector

log = structlog.get_logger()


class _PositionDict(TypedDict):
    """Minimal position representation used by exposure calculations."""

    symbol: str
    weight: float


class SectorExposureManager:
    """Enforces per-sector concentration limits across the portfolio.

    Parameters
    ----------
    max_sector_pct:
        Maximum allocation (as a fraction of equity) for any single sector.
    max_correlated_pct:
        Maximum combined allocation for correlated sector groups.
    """

    def __init__(
        self,
        max_sector_pct: float = 0.30,
        max_correlated_pct: float = 0.50,
    ) -> None:
        self._max_sector_pct = max_sector_pct
        self._max_correlated_pct = max_correlated_pct
        log.info(
            "sector_exposure_init",
            max_sector_pct=max_sector_pct,
            max_correlated_pct=max_correlated_pct,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_sector_exposure(
        self,
        positions: list[_PositionDict],
    ) -> dict[str, float]:
        """Aggregate position weights by GICS sector.

        Parameters
        ----------
        positions:
            Each element must have ``"symbol"`` and ``"weight"`` keys where
            weight is the position's fraction of total equity.

        Returns
        -------
        dict mapping sector name to total weight.
        """
        exposure: dict[str, float] = {}
        for pos in positions:
            sector = get_sector(pos["symbol"])
            exposure[sector] = exposure.get(sector, 0.0) + pos["weight"]
        return exposure

    def check_sector_limit(
        self,
        symbol: str,
        proposed_weight: float,
        current_exposure: dict[str, float],
    ) -> tuple[bool, str]:
        """Check whether adding *proposed_weight* for *symbol* stays within limits.

        Returns
        -------
        (allowed, reason) -- ``allowed`` is ``True`` when the trade is
        permitted; ``reason`` is an empty string when allowed or a
        human-readable explanation when blocked.
        """
        sector = get_sector(symbol)
        current = current_exposure.get(sector, 0.0)
        projected = current + proposed_weight

        if projected > self._max_sector_pct:
            reason = (
                f"sector {sector} at {current * 100:.1f}%, limit {self._max_sector_pct * 100:.0f}%"
            )
            log.warning(
                "sector_limit_breached",
                symbol=symbol,
                sector=sector,
                current_pct=round(current * 100, 2),
                proposed_pct=round(proposed_weight * 100, 2),
                limit_pct=round(self._max_sector_pct * 100, 2),
            )
            return False, reason

        return True, ""

    def adjusted_weight(
        self,
        symbol: str,
        proposed_weight: float,
        current_exposure: dict[str, float],
    ) -> float:
        """Return the maximum permissible weight for *symbol* given sector limits.

        If the sector already exceeds the cap, returns ``0.0``.  Otherwise
        returns the lesser of *proposed_weight* and the remaining headroom.
        """
        sector = get_sector(symbol)
        current = current_exposure.get(sector, 0.0)
        headroom = self._max_sector_pct - current

        if headroom <= 0.0:
            return 0.0

        capped = min(proposed_weight, headroom)
        if capped < proposed_weight:
            log.info(
                "sector_weight_capped",
                symbol=symbol,
                sector=sector,
                proposed=round(proposed_weight, 4),
                allowed=round(capped, 4),
                headroom=round(headroom, 4),
            )
        return capped
