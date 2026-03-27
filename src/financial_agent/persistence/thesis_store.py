"""Persistent storage for trade theses across trading sessions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger()


class TradeThesis(BaseModel):
    """A trade thesis capturing the reasoning behind a position."""

    symbol: str
    signal_type: str
    entry_price: float
    entry_date: str
    reason: str
    target_price: float | None = None
    stop_loss: float | None = None
    invalidation: str = ""
    confidence: float = 0.0
    status: str = "active"
    notes: list[str] = Field(default_factory=list)


class ThesisStore:
    """Manages persistence of trade theses to a JSON file.

    Theses are keyed by symbol. Only one thesis per symbol is stored;
    saving a new thesis for the same symbol overwrites the previous one.
    """

    def __init__(self, data_dir: str = ".data") -> None:
        dir_path = Path(data_dir)
        dir_path.mkdir(parents=True, exist_ok=True)
        self._path: Path = dir_path / "trade_theses.json"
        self._cooldown_path: Path = dir_path / "sell_cooldowns.json"
        self._theses: dict[str, TradeThesis] = {}
        self._cooldowns: dict[str, str] = {}  # symbol -> ISO timestamp of last sell
        self._load()
        self._load_cooldowns()

    def _load(self) -> None:
        """Load theses from disk. Starts empty on any error."""
        try:
            if self._path.exists():
                raw = self._path.read_text(encoding="utf-8")
                data: dict[str, object] = json.loads(raw)
                self._theses = {
                    symbol: TradeThesis.model_validate(entry) for symbol, entry in data.items()
                }
                log.info(
                    "theses_loaded",
                    count=len(self._theses),
                    path=str(self._path),
                )
        except Exception:
            log.warning(
                "theses_load_failed",
                path=str(self._path),
                exc_info=True,
            )
            self._theses = {}

    def _save(self) -> None:
        """Write all theses to disk."""
        try:
            data = {symbol: thesis.model_dump() for symbol, thesis in self._theses.items()}
            self._path.write_text(
                json.dumps(data, indent=2),
                encoding="utf-8",
            )
        except Exception:
            log.error(
                "theses_save_failed",
                path=str(self._path),
                exc_info=True,
            )

    def save_thesis(self, thesis: TradeThesis) -> None:
        """Store a thesis (keyed by symbol) and persist to disk."""
        self._theses[thesis.symbol] = thesis
        self._save()
        log.info(
            "thesis_saved",
            symbol=thesis.symbol,
            signal_type=thesis.signal_type,
            confidence=thesis.confidence,
        )

    def get_thesis(self, symbol: str) -> TradeThesis | None:
        """Return the thesis for *symbol*, or ``None`` if absent."""
        return self._theses.get(symbol)

    def get_active_theses(self) -> dict[str, TradeThesis]:
        """Return all theses whose status is ``'active'``."""
        return {
            symbol: thesis for symbol, thesis in self._theses.items() if thesis.status == "active"
        }

    def close_thesis(self, symbol: str, reason: str = "") -> None:
        """Mark a thesis as closed with an optional reason."""
        thesis = self._theses.get(symbol)
        if thesis is None:
            return
        thesis.status = "closed"
        timestamp = datetime.now(tz=UTC).isoformat()
        note = f"[{timestamp}] CLOSED"
        if reason:
            note += f": {reason}"
        thesis.notes.append(note)
        self._save()
        log.info("thesis_closed", symbol=symbol, reason=reason)

    def invalidate_thesis(self, symbol: str, reason: str = "") -> None:
        """Mark a thesis as invalidated with an optional reason."""
        thesis = self._theses.get(symbol)
        if thesis is None:
            return
        thesis.status = "invalidated"
        timestamp = datetime.now(tz=UTC).isoformat()
        note = f"[{timestamp}] INVALIDATED"
        if reason:
            note += f": {reason}"
        thesis.notes.append(note)
        self._save()
        log.info("thesis_invalidated", symbol=symbol, reason=reason)

    def add_note(self, symbol: str, note: str) -> None:
        """Append a timestamped note to the thesis for *symbol*."""
        thesis = self._theses.get(symbol)
        if thesis is None:
            return
        timestamp = datetime.now(tz=UTC).isoformat()
        thesis.notes.append(f"[{timestamp}] {note}")
        self._save()

    def record_sell(self, symbol: str) -> None:
        """Record that a symbol was sold, starting its cooldown timer."""
        self._cooldowns[symbol] = datetime.now(tz=UTC).isoformat()
        self._save_cooldowns()

    def is_on_cooldown(self, symbol: str, cooldown_hours: int) -> bool:
        """Check if a symbol is still within its post-sell cooldown period."""
        sell_time_str = self._cooldowns.get(symbol)
        if not sell_time_str:
            return False
        try:
            sell_time = datetime.fromisoformat(sell_time_str)
            if sell_time.tzinfo is None:
                sell_time = sell_time.replace(tzinfo=UTC)
            elapsed_hours = (datetime.now(tz=UTC) - sell_time).total_seconds() / 3600
            return elapsed_hours < cooldown_hours
        except (ValueError, TypeError):
            return False

    def _load_cooldowns(self) -> None:
        """Load sell cooldown timestamps from disk and prune expired entries."""
        try:
            if self._cooldown_path.exists():
                self._cooldowns = json.loads(self._cooldown_path.read_text(encoding="utf-8"))
                self._prune_expired_cooldowns()
        except Exception:
            self._cooldowns = {}

    def _prune_expired_cooldowns(self, max_age_hours: int = 72) -> None:
        """Remove cooldown entries older than max_age_hours."""
        now = datetime.now(tz=UTC)
        expired = []
        for symbol, sell_time_str in self._cooldowns.items():
            try:
                sell_time = datetime.fromisoformat(sell_time_str)
                if sell_time.tzinfo is None:
                    sell_time = sell_time.replace(tzinfo=UTC)
                if (now - sell_time).total_seconds() / 3600 >= max_age_hours:
                    expired.append(symbol)
            except (ValueError, TypeError):
                expired.append(symbol)
        for symbol in expired:
            del self._cooldowns[symbol]
        if expired:
            self._save_cooldowns()

    def _save_cooldowns(self) -> None:
        """Write sell cooldown timestamps to disk."""
        try:
            self._cooldown_path.write_text(json.dumps(self._cooldowns, indent=2), encoding="utf-8")
        except Exception:
            log.debug("cooldowns_save_failed", exc_info=True)

    def format_for_prompt(self) -> str:
        """Format active theses as a readable string for the AI prompt."""
        active = self.get_active_theses()
        if not active:
            return "No active trade theses."

        lines: list[str] = ["=== Active Trade Theses ==="]
        for symbol, thesis in active.items():
            lines.append(f"\n--- {symbol} ---")
            lines.append(f"  Signal: {thesis.signal_type}")
            lines.append(f"  Entry: ${thesis.entry_price:.2f} on {thesis.entry_date}")
            lines.append(f"  Reason: {thesis.reason}")
            if thesis.target_price is not None:
                lines.append(f"  Target: ${thesis.target_price:.2f}")
            if thesis.stop_loss is not None:
                lines.append(f"  Stop Loss: ${thesis.stop_loss:.2f}")
            lines.append(f"  Confidence: {thesis.confidence:.0%}")
            if thesis.invalidation:
                lines.append(f"  Invalidation: {thesis.invalidation}")
            if thesis.notes:
                recent = thesis.notes[-3:]
                lines.append("  Recent Notes:")
                for n in recent:
                    lines.append(f"    - {n}")

        return "\n".join(lines)
