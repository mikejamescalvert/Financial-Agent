"""Static GICS sector mapping for common US equity symbols."""

from __future__ import annotations

SECTOR_MAP: dict[str, str] = {
    # Technology
    "AAPL": "Technology",
    "MSFT": "Technology",
    "GOOGL": "Technology",
    "NVDA": "Technology",
    "META": "Technology",
    "AVGO": "Technology",
    "ADBE": "Technology",
    "CRM": "Technology",
    "ORCL": "Technology",
    "CSCO": "Technology",
    "INTC": "Technology",
    "AMD": "Technology",
    "QCOM": "Technology",
    "NOW": "Technology",
    "IBM": "Technology",
    # Consumer Discretionary
    "AMZN": "Consumer Discretionary",
    "TSLA": "Consumer Discretionary",
    "HD": "Consumer Discretionary",
    "NFLX": "Consumer Discretionary",
    "COST": "Consumer Discretionary",
    "NKE": "Consumer Discretionary",
    "MCD": "Consumer Discretionary",
    "SBUX": "Consumer Discretionary",
    "TJX": "Consumer Discretionary",
    "BKNG": "Consumer Discretionary",
    # Financials
    "JPM": "Financials",
    "V": "Financials",
    "MA": "Financials",
    "GS": "Financials",
    "MS": "Financials",
    "BRK.B": "Financials",
    "BAC": "Financials",
    "WFC": "Financials",
    "BLK": "Financials",
    "SCHW": "Financials",
    # Healthcare
    "UNH": "Healthcare",
    "JNJ": "Healthcare",
    "LLY": "Healthcare",
    "PFE": "Healthcare",
    "ABT": "Healthcare",
    "TMO": "Healthcare",
    "ABBV": "Healthcare",
    "MRK": "Healthcare",
    "AMGN": "Healthcare",
    "ISRG": "Healthcare",
    # Industrials
    "BA": "Industrials",
    "CAT": "Industrials",
    "GE": "Industrials",
    "MMM": "Industrials",
    "LMT": "Industrials",
    "RTX": "Industrials",
    "UPS": "Industrials",
    "HON": "Industrials",
    "DE": "Industrials",
    "UNP": "Industrials",
    # Communication Services
    "GOOG": "Communication Services",
    "DIS": "Communication Services",
    "CMCSA": "Communication Services",
    "T": "Communication Services",
    "VZ": "Communication Services",
    # Energy
    "XOM": "Energy",
    "CVX": "Energy",
    "COP": "Energy",
    "SLB": "Energy",
    "EOG": "Energy",
    "MPC": "Energy",
    "PSX": "Energy",
    "OXY": "Energy",
    # Utilities
    "NEE": "Utilities",
    "SO": "Utilities",
    "DUK": "Utilities",
    "D": "Utilities",
    "AEP": "Utilities",
    # Real Estate
    "AMT": "Real Estate",
    "PLD": "Real Estate",
    "CCI": "Real Estate",
    "EQIX": "Real Estate",
    "SPG": "Real Estate",
    # Materials
    "LIN": "Materials",
    "APD": "Materials",
    "SHW": "Materials",
    "ECL": "Materials",
    "FCX": "Materials",
    # Consumer Staples
    "PG": "Consumer Staples",
    "PEP": "Consumer Staples",
    "KO": "Consumer Staples",
    "WMT": "Consumer Staples",
    "PM": "Consumer Staples",
    "MO": "Consumer Staples",
    "CL": "Consumer Staples",
}


def get_sector(symbol: str) -> str:
    """Return the GICS sector for a symbol, or 'Unknown' if not mapped."""
    return SECTOR_MAP.get(symbol, "Unknown")


def get_sector_symbols(sector: str) -> list[str]:
    """Return all symbols belonging to a given sector."""
    return [sym for sym, sec in SECTOR_MAP.items() if sec == sector]
