"""Trade performance tracking, risk-adjusted metrics, and trade journal."""

from __future__ import annotations

import json
import math
from pathlib import Path

import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger()


class TradeRecord(BaseModel):
    """A single completed trade entry in the journal."""

    symbol: str
    side: str
    qty: float
    price: float
    timestamp: str
    reason: str = ""
    confidence: float = 0.0
    order_type: str = "market"
    pnl: float | None = Field(default=None, description="Set when trade is closed")
    holding_days: int | None = Field(default=None, description="Set when trade is closed")


class PerformanceTracker:
    """Tracks trade history and computes risk-adjusted performance metrics."""

    def __init__(self, data_dir: str = ".data") -> None:
        self._path: Path = Path(data_dir) / "trade_journal.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._trades: list[TradeRecord] = []
        self._load()

    def _load(self) -> None:
        """Load trade journal from disk, handling missing or corrupt files."""
        if not self._path.exists():
            log.info("trade_journal_not_found", path=str(self._path))
            return
        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
            self._trades = [TradeRecord.model_validate(entry) for entry in data]
            log.info("trade_journal_loaded", count=len(self._trades))
        except (json.JSONDecodeError, ValueError):
            log.warning("trade_journal_corrupt", path=str(self._path))
            self._trades = []

    def _save(self) -> None:
        """Persist the trade journal to disk, keeping only the last 1000 trades."""
        self._trades = self._trades[-1000:]
        data = [record.model_dump() for record in self._trades]
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        log.debug("trade_journal_saved", count=len(self._trades))

    def record_trade(self, record: TradeRecord) -> None:
        """Append a trade to the journal and persist."""
        self._trades.append(record)
        self._save()
        log.info(
            "trade_recorded",
            symbol=record.symbol,
            side=record.side,
            qty=record.qty,
            price=record.price,
        )

    def _closed_trades(self) -> list[TradeRecord]:
        """Return trades that have a realized P&L."""
        return [t for t in self._trades if t.pnl is not None]

    def win_rate(self) -> float | None:
        """Fraction of closed trades with positive P&L."""
        closed = self._closed_trades()
        if not closed:
            return None
        wins = sum(1 for t in closed if t.pnl is not None and t.pnl > 0)
        return wins / len(closed)

    def profit_factor(self) -> float | None:
        """Gross profits divided by gross losses from closed trades."""
        closed = self._closed_trades()
        if not closed:
            return None
        gross_profits = sum(t.pnl for t in closed if t.pnl is not None and t.pnl > 0)
        gross_losses = abs(sum(t.pnl for t in closed if t.pnl is not None and t.pnl < 0))
        if gross_losses == 0:
            return None
        return gross_profits / gross_losses

    def avg_win(self) -> float | None:
        """Average P&L of winning trades."""
        winners = [t.pnl for t in self._closed_trades() if t.pnl is not None and t.pnl > 0]
        if not winners:
            return None
        return sum(winners) / len(winners)

    def avg_loss(self) -> float | None:
        """Average P&L of losing trades."""
        losers = [t.pnl for t in self._closed_trades() if t.pnl is not None and t.pnl < 0]
        if not losers:
            return None
        return sum(losers) / len(losers)

    @staticmethod
    def _mean(values: list[float]) -> float:
        """Compute arithmetic mean without numpy."""
        return sum(values) / len(values)

    @staticmethod
    def _std(values: list[float]) -> float:
        """Compute sample standard deviation without numpy."""
        if len(values) < 2:
            return 0.0
        m = sum(values) / len(values)
        variance = sum((x - m) ** 2 for x in values) / (len(values) - 1)
        return math.sqrt(variance)

    def sharpe_ratio(
        self,
        daily_returns: list[float],
        risk_free_rate: float = 0.05,
    ) -> float | None:
        """Annualized Sharpe ratio from a series of daily returns.

        Args:
            daily_returns: Daily portfolio returns as decimals (e.g. 0.01 = 1%).
            risk_free_rate: Annualized risk-free rate (default 5%).

        Returns:
            Annualized Sharpe ratio, or None if insufficient data.
        """
        if len(daily_returns) < 5:
            return None
        daily_rf = risk_free_rate / 252
        excess = [r - daily_rf for r in daily_returns]
        std = self._std(excess)
        if std == 0:
            return None
        return self._mean(excess) / std * math.sqrt(252)

    def sortino_ratio(
        self,
        daily_returns: list[float],
        risk_free_rate: float = 0.05,
    ) -> float | None:
        """Annualized Sortino ratio from a series of daily returns.

        Like Sharpe but only penalizes downside deviation.

        Args:
            daily_returns: Daily portfolio returns as decimals (e.g. 0.01 = 1%).
            risk_free_rate: Annualized risk-free rate (default 5%).

        Returns:
            Annualized Sortino ratio, or None if insufficient data.
        """
        if len(daily_returns) < 5:
            return None
        daily_rf = risk_free_rate / 252
        excess = [r - daily_rf for r in daily_returns]
        downside = [min(r, 0) for r in excess]
        downside_std = math.sqrt(self._mean([d**2 for d in downside]))
        if downside_std == 0:
            return None
        return self._mean(excess) / downside_std * math.sqrt(252)

    def trade_count(self) -> int:
        """Total number of trades in the journal."""
        return len(self._trades)

    def format_for_prompt(self, daily_returns: list[float] | None = None) -> str:
        """Format performance summary for inclusion in an AI prompt."""
        if not self._trades:
            return "No trade history available."

        lines: list[str] = []
        lines.append(f"Total trades: {self.trade_count()}")

        wr = self.win_rate()
        if wr is not None:
            lines.append(f"Win rate: {wr:.1%}")

        pf = self.profit_factor()
        if pf is not None:
            lines.append(f"Profit factor: {pf:.2f}")

        aw = self.avg_win()
        if aw is not None:
            lines.append(f"Avg win: ${aw:,.2f}")

        al = self.avg_loss()
        if al is not None:
            lines.append(f"Avg loss: ${al:,.2f}")

        if daily_returns is not None:
            sr = self.sharpe_ratio(daily_returns)
            if sr is not None:
                lines.append(f"Sharpe ratio: {sr:.2f}")

            so = self.sortino_ratio(daily_returns)
            if so is not None:
                lines.append(f"Sortino ratio: {so:.2f}")

        return "\n".join(lines)
