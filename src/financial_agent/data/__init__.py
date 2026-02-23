"""Market data enrichment providers for fundamentals, earnings, news, and macro."""

from __future__ import annotations

from financial_agent.data.crypto_market import CryptoMarketProvider
from financial_agent.data.earnings import EarningsProvider
from financial_agent.data.fundamentals import FundamentalsProvider
from financial_agent.data.macro import MacroProvider
from financial_agent.data.news import NewsProvider
from financial_agent.data.sector_map import SECTOR_MAP, get_sector

__all__ = [
    "CryptoMarketProvider",
    "EarningsProvider",
    "FundamentalsProvider",
    "MacroProvider",
    "NewsProvider",
    "SECTOR_MAP",
    "get_sector",
]
