"""Strategy engine that combines technical analysis with AI insights to produce trade signals."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from financial_agent.portfolio.models import (
    SignalType,
    TradeOrder,
    TradeSignal,
)

if TYPE_CHECKING:
    from financial_agent.config import TradingConfig
    from financial_agent.portfolio.models import PortfolioSnapshot

log = structlog.get_logger()


class StrategyEngine:
    """Converts AI-produced trade signals into executable orders with risk management."""

    def __init__(self, config: TradingConfig) -> None:
        self._config = config

    def generate_orders(
        self,
        signals: list[TradeSignal],
        portfolio: PortfolioSnapshot,
    ) -> list[TradeOrder]:
        """Convert trade signals into concrete orders with position sizing and risk checks."""
        orders: list[TradeOrder] = []

        for signal in signals:
            if signal.signal == SignalType.HOLD:
                continue

            order = self._signal_to_order(signal, portfolio)
            if order is not None:
                orders.append(order)

        # Enforce daily trade limit
        if len(orders) > self._config.max_daily_trades:
            orders.sort(key=lambda o: o.signal_confidence, reverse=True)
            orders = orders[: self._config.max_daily_trades]
            log.warning(
                "orders_capped",
                max=self._config.max_daily_trades,
                total_signals=len(signals),
            )

        return orders

    def _signal_to_order(
        self,
        signal: TradeSignal,
        portfolio: PortfolioSnapshot,
    ) -> TradeOrder | None:
        """Convert a single signal to an order with position sizing."""
        if signal.signal == SignalType.BUY:
            return self._size_buy_order(signal, portfolio)
        elif signal.signal == SignalType.SELL:
            return self._size_sell_order(signal, portfolio)
        return None

    def _size_buy_order(
        self,
        signal: TradeSignal,
        portfolio: PortfolioSnapshot,
    ) -> TradeOrder | None:
        """Size a buy order respecting position limits and cash reserves."""
        # Enforce minimum cash reserve
        available_cash = portfolio.cash - (portfolio.equity * self._config.min_cash_reserve_pct)
        if available_cash <= 0:
            log.info("skip_buy_insufficient_cash", symbol=signal.symbol)
            return None

        # Calculate max position value
        max_position_value = portfolio.equity * self._config.max_position_pct

        # Check existing position weight
        current_weight = portfolio.position_weight(signal.symbol)
        remaining_allocation = self._config.max_position_pct - current_weight

        if remaining_allocation <= 0.001:
            log.info("skip_buy_position_full", symbol=signal.symbol, weight=current_weight)
            return None

        # Target allocation scaled by confidence
        target_value = min(
            max_position_value * signal.confidence,
            available_cash,
            remaining_allocation * portfolio.equity,
        )

        if target_value < 1.0:
            return None

        # Estimate qty (using current price from signal context)
        current_pos = portfolio.get_position(signal.symbol)
        est_price = current_pos.current_price if current_pos else target_value
        qty = round(target_value / est_price, 2) if est_price > 0 else 0

        if qty <= 0:
            return None

        return TradeOrder(
            symbol=signal.symbol,
            side="buy",
            qty=qty,
            reason=signal.reason,
            signal_confidence=signal.confidence,
            asset_class=signal.asset_class,
        )

    def _size_sell_order(
        self,
        signal: TradeSignal,
        portfolio: PortfolioSnapshot,
    ) -> TradeOrder | None:
        """Size a sell order based on current position."""
        position = portfolio.get_position(signal.symbol)
        if position is None or position.qty <= 0:
            log.info("skip_sell_no_position", symbol=signal.symbol)
            return None

        # Sell quantity scaled by confidence: high confidence = sell more
        sell_qty = round(position.qty * signal.confidence, 2)
        if sell_qty <= 0:
            return None

        return TradeOrder(
            symbol=signal.symbol,
            side="sell",
            qty=sell_qty,
            reason=signal.reason,
            signal_confidence=signal.confidence,
            asset_class=signal.asset_class,
        )
