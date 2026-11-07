# 5. Technical Indicators: Choosing *When* to Buy

**Fundamentals** (files 1–3) help you decide **what** to buy.
**Technicals** (this file) help you decide **when** to buy.

Technical indicators are math applied to past price and volume. They don't predict
the future. They describe what's happening right now (trend, momentum, levels)
so your entries follow rules instead of emotion.

## Moving average (MA)

**What:** The average closing price over the last N days, recalculated every day.
It smooths out daily noise to show the **direction** of the trend.

- **SMA (simple moving average):** every day counts equally.
- **EMA (exponential moving average):** recent days count more, so it reacts faster.

| Moving average | Used for |
|---|---|
| 20-day | Short-term trend (about 1 month) |
| **50-day** | **Medium-term trend (about 2.5 months)** |
| **200-day** | **Long-term trend (about 10 months)** |

### Reading moving averages

| Situation | Meaning |
|---|---|
| Price **above** the 200-day | Long-term **uptrend**. Buyers are in control. |
| Price **below** the 200-day | Long-term **downtrend**. Be careful. |
| 50-day **above** the 200-day | Healthy uptrend structure |
| **Golden cross**: 50-day crosses **above** 200-day | Bullish signal |
| **Death cross**: 50-day crosses **below** 200-day | Bearish signal |

Big funds watch the 50- and 200-day averages closely, so prices often **bounce near
them**. That makes them natural "entry zones" in an uptrend.

**Our scan uses this:** price above the 200-day, 50-day above the 200-day, and price
within −5% to +3% of the 50-day. That finds stocks in an uptrend that have come
back near their 50-day line.

## Trend

- **Uptrend:** higher highs and higher lows (a staircase going up).
- **Downtrend:** lower highs and lower lows.
- **Sideways / range:** bouncing between two levels.

> "The trend is your friend." Buying a dip in an uptrend has better odds than
> buying a stock that's falling.

## Pullback vs reversal

- **Pullback:** a temporary dip **inside** an uptrend, usually 5–15%, often to the 50-day.
  The trend continues afterwards. **This is what our scan looks for.**
- **Reversal:** the trend actually **changes direction**. The dip keeps going.

You can't be 100% sure which one you're seeing, which is why we combine trend,
RSI and fundamentals, and use a stop-loss.

**Intel is not a pullback.** It fell 45% in a week on bad news and broke far below
its averages. That's closer to a reversal or a crash.

## RSI (Relative Strength Index)

**What:** A momentum score from **0 to 100**, usually over 14 days. It compares the
size of recent up days with recent down days.

| RSI | Meaning |
|---|---|
| > 70 | **Overbought**: rose fast, may cool off |
| 50 | Neutral |
| 30–50 | Cooled off, a possible pullback zone |
| < 30 | **Oversold**: fell fast, may bounce (or keep falling) |

**Our scan uses RSI 35–50:** the stock has cooled off but isn't in a panic. In a
strong uptrend, RSI often bottoms around 40, so that's our "buy the dip" zone.

**Careful:** "Oversold" can stay oversold. A crashing stock can sit below 30 for
weeks.

## Support and resistance

- **Support:** a price level where buyers keep stepping in, so the price tends to stop falling there (a "floor").
- **Resistance:** a price level where sellers keep showing up, so the price tends to stop rising there (a "ceiling").
- When a support level breaks, it often becomes resistance, and the other way round.

**How to spot them:** prior lows and highs, round numbers ($50, $100), and moving
averages.

## Falling knife

Trying to buy a stock **while it's crashing**. "Don't catch a falling knife": you
might get cut.

**Signs the knife has "landed"** (that it has stabilized):
1. The stock stops making new lows for several days or weeks.
2. Volume calms down back toward normal.
3. It forms a **higher low**: it dips again but not as deep as before.
4. It starts holding above a short-term moving average, like the 20-day.

**Intel as of Nov 6, 2026:** down 5 days in a row, then the first bounce.
None of the signs above are confirmed yet.

## Other indicators (for later)

| Indicator | What it shows |
|---|---|
| **MACD** | Momentum. Uses the gap between two EMAs (12 and 26 day). Crossovers signal a shift. |
| **Bollinger Bands** | A band of ±2 standard deviations around the 20-day MA. Shows when the price is stretched. |
| **ATR (Average True Range)** | How much a stock moves per day on average. Useful for setting stop-loss distance. |
| **VWAP** | Average price weighted by volume. Mostly used by day traders. |
| **ADX** | How *strong* a trend is (not its direction). Above 25 = strong trend. |

## Important reminder

No indicator works all the time. They improve your **odds** and keep your decisions
consistent. They don't guarantee anything. That's why we **backtest** rules on past
data before trusting them with money.
