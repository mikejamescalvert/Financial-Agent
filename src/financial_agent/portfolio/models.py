"""Core data models for portfolio, positions, and trades."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Position(BaseModel):
    """A single stock position."""

    symbol: str
    qty: float
    avg_entry_price: float
    current_price: float
    market_value: float
    unrealized_pl: float
    unrealized_pl_pct: float
    side: str = "long"


class PortfolioSnapshot(BaseModel):
    """Complete portfolio state at a point in time."""

    equity: float
    cash: float
    buying_power: float
    positions: list[Position]
    timestamp: datetime = Field(default_factory=datetime.now)

    @property
    def position_count(self) -> int:
        return len(self.positions)

    @property
    def total_unrealized_pl(self) -> float:
        return sum(p.unrealized_pl for p in self.positions)

    def get_position(self, symbol: str) -> Position | None:
        for p in self.positions:
            if p.symbol == symbol:
                return p
        return None

    def position_weight(self, symbol: str) -> float:
        """Get the weight of a position as fraction of equity."""
        pos = self.get_position(symbol)
        if pos is None or self.equity == 0:
            return 0.0
        return pos.market_value / self.equity


class SignalType(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class TradeSignal(BaseModel):
    """A trading signal produced by the strategy engine."""

    symbol: str
    signal: SignalType
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    target_weight: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None


class TradeOrder(BaseModel):
    """An order to be submitted to the broker."""

    symbol: str
    side: str  # "buy" or "sell"
    qty: float
    reason: str
    signal_confidence: float = 0.0
