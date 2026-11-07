# 11. The Numbers Our System Computes Every Day

Every evening, after prices load, the system computes ~30 numbers for each of ~5,400 stocks, then a market snapshot
and a set of economy readings. This page explains what each one tells you. The dashboard's **Market** page shows them.

## Per stock

| Number | What it tells you | Example (Nov 6, 2026) |
|---|---|---|
| **Returns** (day, week, month, 3/6/12 months) | How much the price changed | AMD +92% over a year |
| **Distance from 20/50/200-day average** | Above (+) or below (−) its recent "normal" price | INTC −35% below its 200-day: deep damage |
| **Slope of the 50/200-day average** | Is the trend itself rising or falling? | |
| **RSI** | 0–100 momentum. Above 70 = stretched up, below 30 = stretched down | INTC 26 after its crash |
| **ATR %** | How much it usually moves in a day | |
| **Volatility** | How bumpy the ride is, in yearly terms | |
| **Relative volume** | Today's volume ÷ normal. 2× = something is happening | AMD 1.8× on its +11% day |
| **Accumulation** (−1 … +1) | Is more volume on up days (buyers in control, +) or down days (sellers, −)? | INTC −0.18: selling pressure |
| **Distance from 52-week high/low** | Near highs = strength; near lows = weakness | |
| **Relative strength vs SPY / its sector** | Is it beating the market and its own industry? | QCOM +14.5% vs its sector over 3 months |
| **RS rank** (1–99) | Rank of its past-year performance among all stocks; 99 = top 1% | AMD 92, NVDA 46 |
| **Beta** | How much it moves when the market moves 1%. Above 1 = amplifies the market | AMD 3.3: a 1% market drop ≈ 3% AMD drop |
| **Trend score** (0–5) | Uptrend checklist: above 50-day, 50-day above 200-day, 200-day rising, above 200-day, within 25% of the high | 5 = textbook uptrend |
| **Days since / to earnings** | Where it is in the earnings cycle. To-earnings uses the real calendar when known | NVDA reports Nov 17 |
| **Earnings reaction** | How it moved on its last earnings day, minus the market's move | INTC −26.8% |

## Market snapshot

- **Breadth:** % of stocks above their 50-day and 200-day averages, new highs vs new lows, up vs down stocks.
  On Nov 6 only **45%** of stocks were above their 200-day average even though the S&P 500 was in an uptrend: a **narrow** market.
- **Rotation:** each sector/theme ETF vs SPY, put in one of four boxes: **leading, weakening, lagging, improving**
  (see [10-reading-the-whole-market.md](10-reading-the-whole-market.md)).
- **Risk signals:** junk bonds vs Treasuries, small vs large, cyclical vs defensive, the fear gauge.
- **Regime and exposure dial:** a simple rule turns the trend, breadth and risk signals into **healthy** (~95% invested),
  **mixed** (~50%) or **defensive** (~25%). Nov 6: *mixed* (uptrend, but narrow and risk-off).

## Economy (from FRED)

| Measure | What it means for stocks |
|---|---|
| **Fed funds rate** | The Federal Reserve's main interest rate. Lower = cheaper borrowing, usually good for stocks |
| **2-year / 10-year Treasury yield** | What the government pays to borrow. Rising yields make future profits worth less today (hurts expensive growth stocks most) |
| **Yield curve (10y − 2y)** | Below 0 ("inverted") has often come before recessions |
| **Real yield** | The 10-year yield after expected inflation: the "true" cost of money |
| **Junk-bond spread** | Extra interest risky companies must pay. Widening = lenders getting nervous |
| **CPI / core CPI / core PCE** | Inflation. Core leaves out food and energy; core PCE is the Fed's favorite. High inflation → higher rates |
| **Unemployment, jobs added, jobless claims** | Health of the job market. Claims are weekly, so they're the earliest warning |
| **Retail sales, industrial production, consumer sentiment** | Are people spending and factories producing? How do people feel? |
| **Oil, dollar** | Oil drives costs and inflation; a strong dollar hurts US companies that sell abroad |
| **Financial conditions (NFCI)** | Below 0 = money is easy to get; above 0 = tight |

**First published vs revised:** economic numbers get revised later. Our database keeps the number **as first published**
and the day it came out, so backtests only use what was actually known at the time.

> These notes are for learning. They are not financial advice.
