"""Core data models for portfolio, positions, and trades."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class AssetClass(StrEnum):
    US_EQUITY = "us_equity"
    CRYPTO = "crypto"


class SignalType(StrEnum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP_LIMIT = "stop_limit"


class PositionStage(StrEnum):
    """Tracks where a position is in its lifecycle for scaling."""

    INITIAL = "initial"  # First 1/3 entry
    BUILDING = "building"  # Second 1/3 added
    FULL = "full"  # Full position
    REDUCING = "reducing"  # Taking partial profits


class Position(BaseModel):
    """A single position (stock or crypto)."""

    symbol: str
    qty: float
    avg_entry_price: float
    current_price: float
    market_value: float
    unrealized_pl: float
    unrealized_pl_pct: float
    side: str = "long"
    asset_class: AssetClass = AssetClass.US_EQUITY
    sector: str = ""
    highest_price: float = 0.0
    stage: PositionStage = PositionStage.FULL


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

    def stock_positions(self) -> list[Position]:
        """Return only US equity positions."""
        return [p for p in self.positions if p.asset_class == AssetClass.US_EQUITY]

    def crypto_positions(self) -> list[Position]:
        """Return only crypto positions."""
        return [p for p in self.positions if p.asset_class == AssetClass.CRYPTO]

    def sector_exposure(self) -> dict[str, float]:
        """Return sector allocation as {sector: weight}."""
        exposure: dict[str, float] = {}
        for p in self.positions:
            if p.sector and self.equity > 0:
                weight = p.market_value / self.equity
                exposure[p.sector] = exposure.get(p.sector, 0.0) + weight
        return exposure


class TradeSignal(BaseModel):
    """A trading signal produced by the AI analyzer."""

    symbol: str
    signal: SignalType
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    target_weight: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    asset_class: AssetClass = AssetClass.US_EQUITY
    scale_action: str = ""  # "add", "partial_exit", "" for full


class TradeOrder(BaseModel):
    """An order to be submitted to the broker."""

    symbol: str
    side: str  # "buy" or "sell"
    qty: float
    reason: str
    signal_confidence: float = 0.0
    asset_class: AssetClass = AssetClass.US_EQUITY
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
