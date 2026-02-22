"""Risk management modules for portfolio protection."""

from __future__ import annotations

from financial_agent.risk.correlation import SectorExposureManager
from financial_agent.risk.drawdown import DrawdownAction, DrawdownCircuitBreaker
from financial_agent.risk.volatility import VolatilitySizer

__all__ = [
    "DrawdownCircuitBreaker",
    "DrawdownAction",
    "SectorExposureManager",
    "VolatilitySizer",
]
