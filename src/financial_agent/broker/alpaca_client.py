"""Alpaca broker client for portfolio data and trade execution."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import structlog
from alpaca.data.historical import CryptoHistoricalDataClient, StockHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, OrderType, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, LimitOrderRequest, MarketOrderRequest

from financial_agent.portfolio.models import (
    AssetClass,
    PortfolioSnapshot,
    Position,
    TradeOrder,
)
from financial_agent.portfolio.models import (
    OrderType as OType,
)

if TYPE_CHECKING:
    import pandas as pd

    from financial_agent.config import BrokerConfig

log = structlog.get_logger()


class AlpacaBroker:
    """Interface to Alpaca for market data and trade execution."""

    def __init__(self, config: BrokerConfig) -> None:
        self._trading = TradingClient(
            config.api_key, config.secret_key, url_override=config.base_url
        )
        self._data = StockHistoricalDataClient(
            config.api_key, config.secret_key, url_override=config.data_url
        )
        self._crypto_data = CryptoHistoricalDataClient(url_override=config.data_url)

    def get_account_info(self) -> dict[str, Any]:
        """Get account balance and status."""
        account: Any = self._trading.get_account()
        return {
            "equity": float(account.equity),
            "cash": float(account.cash),
            "buying_power": float(account.buying_power),
            "portfolio_value": float(account.portfolio_value),
            "day_trade_count": account.daytrade_count,
            "status": account.status,
        }

    def get_positions(self) -> list[Position]:
        """Get all current positions."""
        raw_positions: Any = self._trading.get_all_positions()
        positions = []
        for p in raw_positions:
            asset_cls = (
                AssetClass.CRYPTO
                if getattr(p, "asset_class", None) == "crypto"
                else AssetClass.US_EQUITY
            )
            positions.append(
                Position(
                    symbol=p.symbol,
                    qty=float(p.qty),
                    avg_entry_price=float(p.avg_entry_price),
                    current_price=float(p.current_price),
                    market_value=float(p.market_value),
                    unrealized_pl=float(p.unrealized_pl),
                    unrealized_pl_pct=float(p.unrealized_plpc),
                    side=p.side.value,
                    asset_class=asset_cls,
                )
            )
        return positions

    def get_portfolio_snapshot(self) -> PortfolioSnapshot:
        """Get a complete snapshot of the portfolio."""
        account = self.get_account_info()
        positions = self.get_positions()
        return PortfolioSnapshot(
            equity=account["equity"],
            cash=account["cash"],
            buying_power=account["buying_power"],
            positions=positions,
            timestamp=datetime.now(),
        )

    def get_historical_bars(
        self,
        symbols: list[str],
        days: int = 30,
        timeframe: TimeFrame = TimeFrame.Day,
    ) -> pd.DataFrame:
        """Fetch historical bar data for analysis."""
        request = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=timeframe,
            start=datetime.now() - timedelta(days=days),
        )
        bars: Any = self._data.get_stock_bars(request)
        return cast("pd.DataFrame", bars.df)

    def get_crypto_historical_bars(
        self,
        symbols: list[str],
        days: int = 30,
        timeframe: TimeFrame = TimeFrame.Day,
    ) -> pd.DataFrame:
        """Fetch historical crypto bar data for analysis."""
        request = CryptoBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=timeframe,
            start=datetime.now() - timedelta(days=days),
        )
        bars: Any = self._crypto_data.get_crypto_bars(request)
        return cast("pd.DataFrame", bars.df)

    def get_todays_filled_sides(self) -> dict[str, set[str]]:
        """Get symbols and sides that have filled orders today.

        Returns a dict like {"AAPL": {"buy"}, "JPM": {"buy", "sell"}}.
        Used to detect potential day trades before submitting new orders.
        """
        try:
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            request = GetOrdersRequest(
                status=QueryOrderStatus.CLOSED,
                after=today_start,
                limit=200,
            )
            raw_orders: Any = self._trading.get_orders(request)
            result: dict[str, set[str]] = {}
            for o in raw_orders:
                if str(o.status) == "filled":
                    sym = o.symbol
                    side = o.side.value if hasattr(o.side, "value") else str(o.side)
                    if sym not in result:
                        result[sym] = set()
                    result[sym].add(side)
            return result
        except Exception:
            log.warning("get_todays_fills_failed", exc_info=True)
            return {}

    def get_pending_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """Get open (pending/partially filled) orders, optionally filtered by symbol."""
        try:
            request = GetOrdersRequest(status=QueryOrderStatus.OPEN)
            if symbol:
                request = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
            raw_orders: Any = self._trading.get_orders(request)
            results = []
            for o in raw_orders:
                results.append(
                    {
                        "id": str(o.id),
                        "symbol": o.symbol,
                        "side": str(o.side),
                        "qty": str(o.qty),
                        "type": str(o.type),
                        "status": str(o.status),
                    }
                )
            return results
        except Exception:
            log.warning("get_pending_orders_failed", symbol=symbol, exc_info=True)
            return []

    def cancel_pending_orders(self, symbol: str) -> int:
        """Cancel all open orders for a given symbol. Returns count cancelled."""
        pending = self.get_pending_orders(symbol)
        cancelled = 0
        for order in pending:
            try:
                self._trading.cancel_order_by_id(order["id"])
                cancelled += 1
                log.info(
                    "pending_order_cancelled",
                    symbol=symbol,
                    order_id=order["id"],
                    side=order["side"],
                    qty=order["qty"],
                )
            except Exception:
                log.warning(
                    "cancel_order_failed",
                    symbol=symbol,
                    order_id=order["id"],
                    exc_info=True,
                )
        return cancelled

    def submit_order(self, order: TradeOrder, dry_run: bool = True) -> dict[str, Any]:
        """Submit a trade order. Supports market and limit orders."""
        log.info(
            "order_submitted",
            symbol=order.symbol,
            side=order.side,
            qty=order.qty,
            order_type=order.order_type.value,
            limit_price=order.limit_price,
            dry_run=dry_run,
        )

        if dry_run:
            log.info("dry_run_order", order=order.model_dump())
            return {"status": "dry_run", "order": order.model_dump()}

        # Detect crypto: check asset_class or "/" in symbol (e.g. BTC/USD)
        is_crypto = order.asset_class == AssetClass.CRYPTO or "/" in order.symbol
        tif = TimeInForce.GTC if is_crypto else TimeInForce.DAY
        side = OrderSide.BUY if order.side == "buy" else OrderSide.SELL

        if order.order_type == OType.LIMIT and order.limit_price is not None:
            request: Any = LimitOrderRequest(
                symbol=order.symbol,
                qty=order.qty,
                side=side,
                type=OrderType.LIMIT,
                time_in_force=tif,
                limit_price=order.limit_price,
            )
        else:
            request = MarketOrderRequest(
                symbol=order.symbol,
                qty=order.qty,
                side=side,
                type=OrderType.MARKET,
                time_in_force=tif,
            )

        try:
            result: Any = self._trading.submit_order(request)
        except Exception:
            log.error(
                "order_submission_failed",
                symbol=order.symbol,
                side=order.side,
                qty=order.qty,
                exc_info=True,
            )
            return {
                "status": "failed",
                "symbol": order.symbol,
                "qty": str(order.qty),
                "side": order.side,
                "type": order.order_type.value,
            }

        log.info("order_executed", order_id=result.id, status=result.status)
        return {
            "status": str(result.status),
            "order_id": str(result.id),
            "symbol": result.symbol,
            "qty": str(result.qty),
            "side": str(result.side),
            "type": order.order_type.value,
        }

    def is_market_open(self) -> bool:
        """Check if the market is currently open."""
        clock: Any = self._trading.get_clock()
        return cast("bool", clock.is_open)
