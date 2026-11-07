# 8. Our Scan Explained: "Quality Uptrend Pullback"

Saved in Robinhood (you can see it in Legend). Scan ID: `5c72f6ca-0824-4dd5-a44c-ded2a2386141`

**Goal in one line:** find **good, profitable companies** in a **long-term uptrend**
that have **temporarily dipped**, so we can buy at a better price.

## Each filter, in plain words

| # | Filter | Setting | Why |
|---|---|---|---|
| 1 | Universe | Russell 1000 | The ~1,000 largest US companies. Skips tiny, risky stocks. |
| 2 | Asset type | Stocks only | No ETFs. We want individual companies. |
| 3 | Market cap | > $10B | Big, established companies ([03-valuation.md](03-valuation.md)) |
| 4 | Average volume (30d) | > 1M shares/day | Easy to buy and sell. Small spreads ([04-price-and-volume.md](04-price-and-volume.md)). |
| 5 | EPS | > 0 | Must be **profitable** ([02-earnings.md](02-earnings.md)) |
| 6 | Operating margin | > 10% | Core business is truly profitable ([01-income-statement.md](01-income-statement.md)) |
| 7 | Forward P/E | 5 – 40 | Not absurdly expensive, not suspiciously cheap |
| 8 | Price vs 200-day MA | Above | Long-term **uptrend** ([05-technical-indicators.md](05-technical-indicators.md)) |
| 9 | 50-day vs 200-day MA | 50 above 200 | Healthy trend structure |
| 10 | Distance from 50-day MA | −5% to +3% | Price has **come back near** the 50-day line, our "entry zone" |
| 11 | Distance from 52-week high | −25% to −5% | Has dipped, but isn't crashing |
| 12 | RSI (14-day) | 35 – 50 | Cooled off, not panicking |

Filters 3–7 are about the **quality** of the business.
Filters 8–9 are about the **trend**.
Filters 10–12 are about the **dip** (the entry point).

## Results on Nov 6, 2026 (13 stocks)

TXN, LNG, NUE, CVX, EXPD, XOM, EMR, EOG, COP, CF, SSNC, APA, AES

**Problem we noticed:** 6 of 13 are oil and gas, so this is **sector concentration**
([07-orders-and-risk.md](07-orders-and-risk.md)).

**Why Intel isn't in it:** It fails filters 8, 9, 10, 11 and 12. It's far below its
moving averages, 60% below its high and in a crash, not a pullback. Its trailing EPS
is also negative.

## What's missing (next improvements)

1. **Growth filter:** require revenue or EPS growth (right now we only check profitability).
2. **Earnings-date filter:** exclude stocks reporting in the next ~10 trading days.
3. **Sector cap:** at most 2 picks per sector in the final list.
4. **Ranking:** score candidates instead of just filtering, then show the top 5.
5. **Backtest:** test these rules on 5–10 years of history before using real money.
