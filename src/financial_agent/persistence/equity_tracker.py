"""Tracks portfolio equity over time for drawdown and performance analysis."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import structlog
from pydantic import BaseModel

from financial_agent.utils.io import atomic_write

log = structlog.get_logger()

_MAX_HISTORY = 365


class EquityRecord(BaseModel):
    """A single equity snapshot."""

    timestamp: str
    equity: float
    cash: float
    positions_count: int
    daily_return_pct: float = 0.0


class EquityTracker:
    """Records and analyses portfolio equity history.

    History is persisted to JSON and capped at 365 entries to prevent
    unbounded growth. Peak equity is tracked separately so drawdown
    calculations survive across sessions.
    """

    def __init__(self, data_dir: str = ".data") -> None:
        dir_path = Path(data_dir)
        dir_path.mkdir(parents=True, exist_ok=True)
        self._path: Path = dir_path / "equity_history.json"
        self._peak_path: Path = dir_path / "peak_equity.json"
        self._history: list[EquityRecord] = []
        self._peak_equity: float = 0.0
        self._load()

    def _load(self) -> None:
        """Load history and peak from disk. Handles missing files."""
        try:
            if self._path.exists():
                raw = self._path.read_text(encoding="utf-8")
                data: list[object] = json.loads(raw)
                self._history = [EquityRecord.model_validate(entry) for entry in data]
                log.info(
                    "equity_history_loaded",
                    records=len(self._history),
                    path=str(self._path),
                )
        except Exception:
            log.warning(
                "equity_history_load_failed",
                path=str(self._path),
                exc_info=True,
            )
            self._history = []

        try:
            if self._peak_path.exists():
                raw = self._peak_path.read_text(encoding="utf-8")
                peak_data: dict[str, object] = json.loads(raw)
                self._peak_equity = float(peak_data.get("peak", 0.0))  # type: ignore[arg-type]
        except Exception:
            log.warning(
                "peak_equity_load_failed",
                path=str(self._peak_path),
                exc_info=True,
            )
            self._peak_equity = 0.0

        # Recover peak from history if peak file was missing/corrupt
        if not self._peak_equity and self._history:
            self._peak_equity = max(r.equity for r in self._history)
            log.info("peak_recovered_from_history", peak=self._peak_equity)

    def _save(self) -> None:
        """Persist history (capped) and peak to disk."""
        try:
            trimmed = self._history[-_MAX_HISTORY:]
            self._history = trimmed
            data = [record.model_dump() for record in self._history]
            atomic_write(self._path, json.dumps(data, indent=2))
            atomic_write(self._peak_path, json.dumps({"peak": self._peak_equity}))
        except Exception:
            log.error(
                "equity_save_failed",
                path=str(self._path),
                exc_info=True,
            )

    def record(self, equity: float, cash: float, positions_count: int) -> None:
        """Record a new equity snapshot and persist."""
        daily_return_pct = 0.0
        if self._history:
            prev_equity = self._history[-1].equity
            if prev_equity > 0:
                daily_return_pct = (equity - prev_equity) / prev_equity

        record = EquityRecord(
            timestamp=datetime.now(tz=UTC).isoformat(),
            equity=equity,
            cash=cash,
            positions_count=positions_count,
            daily_return_pct=daily_return_pct,
        )
        self._history.append(record)

        if equity > self._peak_equity:
            self._peak_equity = equity

        self._save()
        log.info(
            "equity_recorded",
            equity=equity,
            cash=cash,
            positions=positions_count,
            daily_return_pct=f"{daily_return_pct:.4f}",
        )

    def peak(self) -> float:
        """Return the all-time peak equity."""
        return self._peak_equity

    def current_drawdown(self, equity: float) -> float:
        """Return current drawdown as a positive fraction.

        Returns 0.0 if peak is zero (no history).
        """
        if self._peak_equity == 0:
            return 0.0
        dd = (self._peak_equity - equity) / self._peak_equity
        return max(dd, 0.0)

    def daily_returns(self, days: int = 30) -> list[float]:
        """Return the last *days* daily return percentages."""
        recent = self._history[-days:]
        return [r.daily_return_pct for r in recent]

    def max_drawdown(self, days: int = 90) -> float:
        """Calculate maximum drawdown over the last *days* entries.

        Returns the largest peak-to-trough decline as a positive fraction.
        """
        recent = self._history[-days:]
        if not recent:
            return 0.0

        running_peak = recent[0].equity
        max_dd = 0.0
        for record in recent:
            if record.equity > running_peak:
                running_peak = record.equity
            if running_peak > 0:
                dd = (running_peak - record.equity) / running_peak
                if dd > max_dd:
                    max_dd = dd
        return max_dd

    def format_for_prompt(self) -> str:
        """Summarise equity performance for the AI prompt."""
        if not self._history:
            return "No equity history available."

        latest = self._history[-1]
        current_dd = self.current_drawdown(latest.equity)
        max_dd_90 = self.max_drawdown(days=90)

        returns_7d = self.daily_returns(days=7)
        returns_30d = self.daily_returns(days=30)
        total_7d = sum(returns_7d)
        total_30d = sum(returns_30d)

        lines: list[str] = [
            "=== Equity Performance ===",
            f"  Peak Equity: ${self._peak_equity:,.2f}",
            f"  Current Equity: ${latest.equity:,.2f}",
            f"  Current Drawdown: {current_dd:.2%}",
            f"  7-Day Return: {total_7d:.2%}",
            f"  30-Day Return: {total_30d:.2%}",
            f"  Max Drawdown (90d): {max_dd_90:.2%}",
        ]
        return "\n".join(lines)
