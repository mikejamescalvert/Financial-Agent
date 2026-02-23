"""Strategy engine: converts AI signals into executable orders with risk management."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from financial_agent.portfolio.models import (
    OrderType,
    SignalType,
    TradeOrder,
    TradeSignal,
)

if TYPE_CHECKING:
    from financial_agent.config import DataConfig, TradingConfig
    from financial_agent.data.models import MarketEnrichment
    from financial_agent.portfolio.models import PortfolioSnapshot
    from financial_agent.risk.drawdown import DrawdownCircuitBreaker
    from financial_agent.risk.volatility import VolatilitySizer

log = structlog.get_logger()


class StrategyEngine:
    """Converts AI-produced trade signals into executable orders with risk management."""

    def __init__(
        self,
        config: TradingConfig,
        data_config: DataConfig | None = None,
        drawdown_breaker: DrawdownCircuitBreaker | None = None,
        volatility_sizer: VolatilitySizer | None = None,
    ) -> None:
        self._config = config
        self._data_config = data_config
        self._drawdown = drawdown_breaker
        self._vol_sizer = volatility_sizer

    def generate_orders(
        self,
        signals: list[TradeSignal],
        portfolio: PortfolioSnapshot,
        technicals: dict[str, dict[str, float]] | None = None,
        enrichment: MarketEnrichment | None = None,
    ) -> list[TradeOrder]:
        """Convert trade signals into concrete orders with position sizing and risk checks."""
        orders: list[TradeOrder] = []
        technicals = technicals or {}

        # Drawdown circuit breaker check (Issue #17)
        size_multiplier = 1.0
        if self._drawdown:
            action = self._drawdown.get_action(portfolio.equity)
            size_multiplier = self._drawdown.size_multiplier(portfolio.equity)
            dd = self._drawdown.current_drawdown(portfolio.equity)
            log.info(
                "drawdown_check",
                drawdown_pct=round(dd * 100, 2),
                action=action.value,
                size_multiplier=size_multiplier,
            )
            if action.value == "halt":
                log.warning("trading_halted", reason="drawdown_circuit_breaker")
                return []

        for signal in signals:
            if signal.signal == SignalType.HOLD:
                continue

            # Block buys if drawdown breaker says so
            if signal.signal == SignalType.BUY and size_multiplier == 0.0:
                log.info("buy_blocked_drawdown", symbol=signal.symbol)
                continue

            # Earnings buffer check (Issue #13)
            if (
                signal.signal == SignalType.BUY
                and enrichment
                and self._data_config
                and self._is_near_earnings(signal.symbol, enrichment)
            ):
                log.info(
                    "buy_blocked_earnings",
                    symbol=signal.symbol,
                    buffer_days=self._data_config.earnings_buffer_days,
                )
                continue

            # Sector exposure check (Issue #16)
            if signal.signal == SignalType.BUY and self._data_config:
                exposure = portfolio.sector_exposure()
                allowed, reason = self._check_sector_limit(
                    signal.symbol, signal.confidence, exposure
                )
                if not allowed:
                    log.info("buy_blocked_sector", symbol=signal.symbol, reason=reason)
                    continue

            order = self._signal_to_order(signal, portfolio, technicals, size_multiplier)
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

    def _is_near_earnings(self, symbol: str, enrichment: MarketEnrichment) -> bool:
        """Check if a symbol is within the earnings buffer zone."""
        if not self._data_config:
            return False
        for event in enrichment.earnings:
            if (
                event.symbol == symbol
                and event.days_until_earnings <= self._data_config.earnings_buffer_days
            ):
                return True
        return False

    def _check_sector_limit(
        self,
        symbol: str,
        confidence: float,
        current_exposure: dict[str, float],
    ) -> tuple[bool, str]:
        """Check if adding to this symbol's sector would exceed limits."""
        if not self._data_config:
            return True, ""

        from financial_agent.data.sector_map import get_sector

        sector = get_sector(symbol)
        if sector == "Unknown":
            return True, ""

        sector_weight = current_exposure.get(sector, 0.0)
        proposed_add = self._config.max_position_pct * confidence
        if sector_weight + proposed_add > self._data_config.max_sector_pct:
            return False, (
                f"{sector} at {sector_weight:.0%}, limit {self._data_config.max_sector_pct:.0%}"
            )
        return True, ""

    def _signal_to_order(
        self,
        signal: TradeSignal,
        portfolio: PortfolioSnapshot,
        technicals: dict[str, dict[str, float]],
        size_multiplier: float,
    ) -> TradeOrder | None:
        """Convert a single signal to an order with position sizing."""
        if signal.signal == SignalType.BUY:
            return self._size_buy_order(signal, portfolio, technicals, size_multiplier)
        elif signal.signal == SignalType.SELL:
            return self._size_sell_order(signal, portfolio, technicals)
        return None

    def _size_buy_order(
        self,
        signal: TradeSignal,
        portfolio: PortfolioSnapshot,
        technicals: dict[str, dict[str, float]],
        size_multiplier: float,
    ) -> TradeOrder | None:
        """Size a buy order respecting position limits, volatility, and cash reserves."""
        # Enforce minimum cash reserve
        available_cash = portfolio.cash - (portfolio.equity * self._config.min_cash_reserve_pct)
        if available_cash <= 0:
            log.info("skip_buy_insufficient_cash", symbol=signal.symbol)
            return None

        # Calculate max position value
        max_position_value = portfolio.equity * self._config.max_position_pct

        # Volatility-adjusted cap (Issue #28)
        if self._vol_sizer and signal.symbol in technicals:
            sym_tech = technicals[signal.symbol]
            atr_pct = sym_tech.get("atr_pct", 0.0)
            if atr_pct > 0:
                vol_cap = self._vol_sizer.max_position_pct(atr_pct) * portfolio.equity
                max_position_value = min(max_position_value, vol_cap)

        # Check existing position weight
        current_weight = portfolio.position_weight(signal.symbol)
        max_weight = max_position_value / portfolio.equity if portfolio.equity > 0 else 0
        remaining_allocation = max_weight - current_weight

        if remaining_allocation <= 0.001:
            log.info("skip_buy_position_full", symbol=signal.symbol, weight=current_weight)
            return None

        # Position scaling (Issue #19): scale_action modifies entry size
        scale_factor = 1.0
        if self._data_config and self._data_config.enable_position_scaling:
            if signal.scale_action == "add":
                scale_factor = 0.33  # Add 1/3 position
            elif current_weight == 0:
                scale_factor = 0.5  # Initial entry: half position

        # Target allocation scaled by confidence, size_multiplier, and scale_factor
        target_value = min(
            max_position_value * signal.confidence * size_multiplier * scale_factor,
            available_cash,
            remaining_allocation * portfolio.equity,
        )

        if target_value < 1.0:
            return None

        # Get current price: existing position > technicals > skip
        current_pos = portfolio.get_position(signal.symbol)
        if current_pos:
            est_price = current_pos.current_price
        elif signal.symbol in technicals and "current_price" in technicals[signal.symbol]:
            est_price = technicals[signal.symbol]["current_price"]
        else:
            log.warning("skip_buy_no_price", symbol=signal.symbol)
            return None

        qty = round(target_value / est_price, 2) if est_price > 0 else 0

        if qty <= 0:
            return None

        # Limit order support (Issue #18)
        order_type = OrderType.MARKET
        limit_price: float | None = None
        if self._data_config and self._data_config.use_limit_orders:
            slippage = self._data_config.slippage_tolerance_pct
            order_type = OrderType.LIMIT
            limit_price = round(est_price * (1 + slippage), 2)

        return TradeOrder(
            symbol=signal.symbol,
            side="buy",
            qty=qty,
            reason=signal.reason,
            signal_confidence=signal.confidence,
            asset_class=signal.asset_class,
            order_type=order_type,
            limit_price=limit_price,
        )

    def _size_sell_order(
        self,
        signal: TradeSignal,
        portfolio: PortfolioSnapshot,
        technicals: dict[str, dict[str, float]] | None = None,
    ) -> TradeOrder | None:
        """Size a sell order based on current position."""
        position = portfolio.get_position(signal.symbol)
        if position is None or position.qty <= 0:
            log.info("skip_sell_no_position", symbol=signal.symbol)
            return None

        # Position scaling for exits (Issue #19)
        if (
            self._data_config
            and self._data_config.enable_position_scaling
            and signal.scale_action == "partial_exit"
        ):
            sell_qty = round(position.qty * 0.33, 2)  # Sell 1/3
        else:
            # Sell quantity scaled by confidence
            sell_qty = round(position.qty * signal.confidence, 2)

        if sell_qty <= 0:
            return None

        # Limit order support for sells
        order_type = OrderType.MARKET
        limit_price: float | None = None
        if self._data_config and self._data_config.use_limit_orders:
            slippage = self._data_config.slippage_tolerance_pct
            order_type = OrderType.LIMIT
            limit_price = round(position.current_price * (1 - slippage), 2)

        return TradeOrder(
            symbol=signal.symbol,
            side="sell",
            qty=sell_qty,
            reason=signal.reason,
            signal_confidence=signal.confidence,
            asset_class=signal.asset_class,
            order_type=order_type,
            limit_price=limit_price,
        )

    def check_trailing_stops(
        self,
        portfolio: PortfolioSnapshot,
        technicals: dict[str, dict[str, float]],
    ) -> list[TradeSignal]:
        """Generate sell signals for positions that hit their trailing stop."""
        if not self._data_config:
            return []

        signals: list[TradeSignal] = []
        atr_mult = self._data_config.trailing_stop_atr_multiplier

        for pos in portfolio.positions:
            if pos.symbol not in technicals:
                continue

            atr = technicals[pos.symbol].get("atr_14", 0.0)
            if atr <= 0:
                continue

            # Trailing stop level = highest_price - (ATR * multiplier)
            high_price = max(pos.highest_price, pos.current_price)
            trailing_stop = high_price - (atr * atr_mult)

            if pos.current_price <= trailing_stop and pos.current_price < high_price:
                signals.append(
                    TradeSignal(
                        symbol=pos.symbol,
                        signal=SignalType.SELL,
                        confidence=0.9,
                        reason=(
                            f"Trailing stop hit: price ${pos.current_price:.2f} "
                            f"below stop ${trailing_stop:.2f} "
                            f"(high ${high_price:.2f}, ATR×{atr_mult})"
                        ),
                        asset_class=pos.asset_class,
                    )
                )
                log.info(
                    "trailing_stop_triggered",
                    symbol=pos.symbol,
                    price=pos.current_price,
                    stop=round(trailing_stop, 2),
                    high=round(high_price, 2),
                )

        return signals
