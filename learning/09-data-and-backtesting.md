# 9. Where Our Data Comes From, and How We Test Ideas Honestly

## Stock splits, dividends and "adjusted" prices

- **Stock split:** a company cuts each share into several smaller ones. Apple did a **4-for-1 split** in Aug 2020: one
  $400 share became four $100 shares. Nobody gained or lost anything, but the raw price chart shows a fake 75% "crash".
- **Dividend:** cash the company pays out per share. On the payout date (the "ex-dividend date") the price drops by about
  that amount, which is also not a real loss.
- **Adjusted price:** history rewritten so splits and dividends don't look like price moves. We store the **raw** price and
  an **adjustment factor**: adjusted = raw × factor.
  Example from our database: Apple's first 2016 bar has factor **0.2249** (÷4 for the split, a bit more for dividends).

Always use **adjusted** prices to measure returns, and **raw** price × volume to measure how much money actually traded.

## SEC filings: the official company documents

| Form | What it is |
|---|---|
| **10-K** | Annual report (full financials, risks, major customers) |
| **10-Q** | Quarterly report |
| **8-K** | "Something important happened" report. **Item 2.02 = earnings results**, which gives a free earnings calendar |
| **20-F / 6-K** | The annual / current reports of foreign companies listed in the US |
| **Form 4** | An insider (executive, director, or 10%+ owner) bought or sold shares, filed within ~2 business days |
| **13D / 13G** | Someone now owns more than 5% of the company |
| **SIC code** | The SEC's industry code for a company (Qualcomm 3663 = communications equipment). We map it to 11 sectors. |

## Insider trades: who inside is buying or selling

| Code | Meaning | How much it tells you |
|---|---|---|
| **P** | Open-market **purchase**: the insider spent their own money | **The strongest signal**: insiders buy for one reason |
| **S** | Open-market **sale** | Weak signal: people sell for many reasons (taxes, a house, diversification) |
| A / M / F | Stock grants, option exercises, shares withheld for tax | Mostly noise: part of their pay |

In Q1 2026 alone there were ~96,000 insider transactions in our companies, but only ~4,400 were real purchases ("P").

## Liquidity and ADV
**ADV (average daily dollar volume)** = how many dollars of a stock trade per day (20-day average). We only trade
automatically where ADV is big enough that our order won't move the price (see the liquidity tiers in
[07-orders-and-risk.md](07-orders-and-risk.md)).

## Backtesting: testing an idea on the past

A **backtest** replays history day by day, as if the strategy had been running, and records every trade.
It tells us whether an idea *would have* worked. It's easy to fool yourself, so our backtester guards against these traps:

| Trap | What goes wrong | Our guard |
|---|---|---|
| **Look-ahead bias** | Using information that wasn't available yet (e.g. today's close to decide a trade at today's open) | Each day the strategy only sees data up to that day's close, and trades at the **next** open. An automatic detector scrambles the "future" and checks the decisions don't change. |
| **Survivorship bias** | Testing only companies that still exist today. The ones that went bankrupt are missing, so everything looks better. | Delisted stocks are kept. Our data source only knows ~660 of them, so we measure that gap. |
| **Ignoring costs** | Every trade loses a little to the bid/ask spread | We charge 0.05% per trade for liquid stocks, 0.15% for thin ones and 0.40% for emerging ones |
| **Too-kind fills** | Assuming a stop-loss always sells exactly at the stop | If a stock **gaps** below the stop overnight, we sell at the opening price (Intel: stop $85 → sold ~$68) |
| **Too many tries** | Test 1,000 ideas and ~50 look great by luck | Every backtest is recorded and counted; ideas must also work on years they weren't designed on |

### Data periods
- **Train (2016–2022):** where ideas are designed and tuned.
- **Validate (2023–2024):** the idea must still work on these unseen years.
- **Holdout (2025–2026):** touched **once**, at the end, as the final exam.

### Our first validation results
- Buy-and-hold SPY: the backtester got **+329.54%** vs SPY's actual **+329.64%**. The engine is accurate.
- "Own SPY only above its 200-day average" made **+169%** with a worst drop of **−19.5%**, vs buy-and-hold's **+330%** with
  **−33.8%**. That's the classic trade-off: less pain, but also less gain.
