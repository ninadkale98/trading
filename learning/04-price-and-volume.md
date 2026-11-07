# 4. Reading a Chart: Price and Volume

## Candlestick chart

Each **candle** shows one period of trading. On a **daily chart**, one candle = one day.

```
        │   ← High (wick): highest price of the day
      ┌─┴─┐
      │   │ ← Body: from Open to Close
      │   │
      └─┬─┘
        │   ← Low (wick): lowest price of the day
```

- **Green (or hollow) candle:** Close > Open. The price went **up** during the period.
- **Red (or filled) candle:** Close < Open. The price went **down** during the period.
- **Long body** = strong move. **Long wicks** = the price swung but got pushed back.

## OHLC

The four prices in every candle: **Open, High, Low, Close**.

**Intel on October 30, 2026:**

| Open | High | Low | Close |
|---|---|---|---|
| $68.36 | $68.77 | $63.20 | $65.76 |

**Close** is the most important. It's the "official" price of the day and what most
indicators use.

## Volume

**What:** The number of shares traded in that period.
**In plain words:** how many people are buying and selling, and how *seriously*.
On a chart it's the bars at the bottom.

**Why it matters:** Volume shows **conviction**.
- A big price move on **high volume** usually means big funds are behind it, so the move is real.
- A big price move on **low volume** usually means few people took part, so it's less reliable.

## Average volume and relative volume

- **Average volume** = typical daily volume over the last N days (for example, 30 days).
- **Relative volume (RVOL)** = today's volume ÷ average volume.

| RVOL | Meaning |
|---|---|
| ~1 | Normal day |
| 2–3 | Unusual. Something is happening. |
| 5+ | Major event (earnings, news) |

**Intel:**

| Date | Volume | vs normal (~90M) |
|---|---|---|
| Oct 28 (normal day) | 83M | ~1× |
| **Oct 30 (crash day)** | **456M** | **~5×** |
| Nov 2–5 (continued selling) | 150–270M | 2–3× |
| Nov 6 (first bounce) | ~127M | ~1.4× |

**Reading it:** The crash happened on enormous volume, so large investors were
selling. The Nov 6 bounce came on fairly normal volume, a weaker signal than the
selling.

## Gap

**What:** The stock **opens** far from the previous day's **close**, leaving an empty
space on the chart.
**Cause:** News that came out while the market was closed (earnings, mergers,
lawsuits and so on).

**Intel:** Closed at **$92.07** on Oct 29 and opened at **$68.36** on Oct 30.
That's a **gap down of about 26%**. No trade happened at any price in between.

**Why gaps are dangerous:** A stop-loss can't fill inside a gap. A stop at $85 would
have filled around $68. See [07-orders-and-risk.md](07-orders-and-risk.md).

## 52-week high and low

The highest and lowest prices of the past year.

**Intel:**
- 52-week **high**: **$142.35** (June 30, 2026)
- 52-week **low**: **$32.89** (November 21, 2025)
- Now: **$56.81**, 60% below the high but about 73% above the low

**Why it matters:** It gives context. "Down 60% from the high" sounds cheap, but it's
still far above where the stock traded a year ago.

## Timeframes and intervals

- **Interval** = what one candle represents (1 minute, 5 minutes, 1 day, 1 week).
- **Timeframe** = how much history the chart shows (1 month, 1 year, 5 years).

**For investing over weeks to months, use daily or weekly candles.** Minute charts are
mostly noise for our purpose.

## Market sessions (US, Eastern Time)

| Session | Time (ET) | Notes |
|---|---|---|
| Pre-market | 4:00 – 9:30 am | Lower volume, bigger price swings |
| **Regular** | **9:30 am – 4:00 pm** | Main session |
| After-hours | 4:00 – 8:00 pm | Earnings reactions start here |

## Bid, ask and spread

- **Bid** = the highest price a buyer is offering right now.
- **Ask** = the lowest price a seller is accepting right now.
- **Spread** = Ask − Bid. Big, liquid stocks have tiny spreads (a cent). Small stocks
  can have wide spreads, which is a hidden cost.
- **Liquidity** = how easily you can buy or sell without moving the price. Our scan
  requires 1M+ shares a day of average volume for this reason.
