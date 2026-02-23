# Risk Management

The system uses multiple layers of risk management, applied both before and after AI analysis.

## Drawdown Circuit Breaker

Monitors portfolio equity against its peak and progressively restricts trading as drawdown deepens.

| Level | Drawdown | Action | Buy Size Multiplier |
|-------|----------|--------|---------------------|
| NORMAL | < 5% | Full trading | 1.0x |
| REDUCE_SIZE | 5-10% | Reduce position sizes | 0.5x |
| BUYS_ONLY_BLOCKED | 10-15% | Block all new buys, sells allowed | 0.0x (buys) |
| DERISK | 15-20% | Block all trading | 0.0x |
| HALT | > 20% | Trading halted entirely | N/A |

- Peak equity persists across sessions via `.data/peak_equity.json`
- Recovery threshold: drawdown must improve by 5% before the level is relaxed
- The AI receives current drawdown level and equity history in its analysis prompt

**Configuration:** Thresholds are hard-coded. The drawdown circuit breaker is always active.

## Volatility-Adjusted Position Sizing

Position sizes are calculated based on each symbol's ATR (Average True Range):

```
Position Size = (Equity × Risk Budget %) / ATR
```

This means volatile assets get smaller positions and stable assets get larger ones.

| Parameter | Variable | Default |
|-----------|----------|---------|
| Risk budget per trade | `DATA_RISK_BUDGET_PCT` | 2% of equity |
| Max single position | `TRADING_MAX_POSITION_PCT` | 10% of portfolio |

The final position size is the minimum of:
1. ATR-based size (from risk budget)
2. Max position % cap
3. Drawdown-adjusted size (multiplied by circuit breaker level)
4. Available cash after reserve

## Trailing Stops

ATR-based trailing stops that adapt to each symbol's volatility:

```
Stop Price = Highest Price Since Entry - (ATR × Multiplier)
```

| Parameter | Variable | Default |
|-----------|----------|---------|
| ATR multiplier | `DATA_TRAILING_STOP_ATR_MULTIPLIER` | 2.0x |

- Checked on every trading cycle via `StrategyEngine.check_trailing_stops()`
- Generates sell signals when the current price breaches the stop level
- Crypto uses wider effective stops due to higher ATR values

## Sector Concentration Limits

Prevents over-exposure to any single GICS sector:

| Parameter | Variable | Default |
|-----------|----------|---------|
| Max sector allocation | `DATA_MAX_SECTOR_PCT` | 30% |

- Sector mapping is static (no API calls) covering 100+ symbols across all 11 GICS sectors
- Buy signals are blocked if executing would push sector exposure above the limit
- The AI receives current sector exposure data in its analysis prompt

## Earnings Buffer

Blocks buy signals within a configurable window before a company's earnings date:

| Parameter | Variable | Default |
|-----------|----------|---------|
| Buffer days | `DATA_EARNINGS_BUFFER_DAYS` | 3 days |

- Requires `DATA_FMP_API_KEY` for earnings calendar data
- Only blocks buys — existing positions are not automatically sold
- Sell signals (including trailing stops) are still processed during the buffer

## Position Scaling

Positions are entered and exited in 1/3 increments rather than all at once:

| Stage | Description |
|-------|-------------|
| INITIAL | First 1/3 entry |
| BUILDING | Adding second 1/3 |
| FULL | Complete position (3/3) |
| REDUCING | Exiting in 1/3 increments |

- Enabled by default (`DATA_ENABLE_POSITION_SCALING=true`)
- The AI can specify `scale_action: "add"` or `scale_action: "partial_exit"` in its signals
- When disabled, positions are entered and exited in full

## Limit Orders

Orders are placed as limit orders with a configurable slippage tolerance:

```
Buy Limit  = Current Price × (1 + Slippage Tolerance)
Sell Limit = Current Price × (1 - Slippage Tolerance)
```

| Parameter | Variable | Default |
|-----------|----------|---------|
| Use limit orders | `DATA_USE_LIMIT_ORDERS` | `true` |
| Slippage tolerance | `DATA_SLIPPAGE_TOLERANCE_PCT` | 0.2% |

When disabled, market orders are used instead.

## Daily Trade Limits

| Parameter | Variable | Default |
|-----------|----------|---------|
| Max daily trades | `TRADING_MAX_DAILY_TRADES` | 10 |

Prevents runaway execution. Once the limit is reached, no additional orders are submitted until the next day.

## Cash Reserve

| Parameter | Variable | Default |
|-----------|----------|---------|
| Min cash reserve | `TRADING_MIN_CASH_RESERVE_PCT` | 10% |

Ensures a minimum cash buffer is always maintained. Position sizing accounts for the reserve — orders that would reduce cash below this level are blocked or downsized.

## Crypto-Specific Rules

Crypto assets receive different risk treatment:

- **Wider stop losses** — Crypto's higher ATR naturally produces wider trailing stops (typically 8-15% vs 3-5% for stocks)
- **24/7 trading** — Crypto pipeline runs on every cycle, regardless of stock market hours
- **BTC dominance monitoring** — AI receives Bitcoin dominance data to inform altcoin allocation
- **Fear & Greed index** — Crypto market sentiment from CoinGecko is included in AI analysis
- **GTC time-in-force** — Crypto limit orders use good-til-cancelled (stocks use day orders)

## Risk Check Pipeline

Risk checks are applied at multiple points in the trading cycle:

1. **Pre-analysis**: Equity tracking, drawdown level calculation
2. **During analysis**: AI receives all risk data (drawdown, sector exposure, earnings dates, equity history)
3. **Post-analysis**: Strategy engine applies:
   - Drawdown circuit breaker (size multiplier or block)
   - Earnings buffer (block buys near earnings)
   - Sector concentration (block buys exceeding limit)
   - Trailing stops (generate sell signals)
   - Volatility sizing (ATR-based position size)
   - Position scaling (1/3 increments)
   - Cash reserve check
   - Daily trade limit check
4. **At execution**: Limit order pricing with slippage tolerance
