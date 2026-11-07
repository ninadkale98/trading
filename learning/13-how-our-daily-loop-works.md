# 13. How Our System Works Each Day

All times are New York time (ET). Everything runs by itself on ichigo. The dashboard is at http://ichigo:8090.

| When | What happens | Where to see it |
|---|---|---|
| Every 30 min | Haiku reads new headlines: which company, what kind of event, good or bad, how important | Market page (movers + news) |
| 4:40 pm | Prices for ~5,400 stocks → ~50 numbers per stock → market snapshot (breadth, rotation, regime) | Market page |
| ~5 pm | **Settle today:** simulated fills, stops, targets (dry run) or sync with the Alpaca practice account (paper) | Trading page |
| ~5 pm | **Plan tomorrow:** each strategy suggests stocks → the planner sizes them under the risk rules | Trading page |
| 9:00 pm | **Opus** writes the market analysis and makes checkable predictions | Journal page |
| 9:30 pm | **Daily briefing** (your 10–15 minute read) | Review page |
| 9:15 am | **Approval deadline** for anything unusual. No answer means no trade | Review page |
| 9:20 am | Paper mode only: orders go to the Alpaca practice account | Trading page |

## Dry run vs paper trading
- **Dry run:** the plans are simulated against the real next-day prices, with the same rules as our backtester. Buy only
  if the stock opens at or below our limit price; a gap below the stop sells at the open, not at the stop. It's a real
  **forward test**: nobody knew the future when the plan was made.
- **Paper:** the same plans become real orders in the Alpaca **practice** account ($100,000 of pretend money). Fills
  and slippage are more realistic. Switched on only when you say so.
- **Real money:** never automatic. Every real order needs your explicit OK for that order.

## How a trade is sized (the planner)
1. Each strategy is still **experimental**, so each trade risks **0.5%** of the account: if the stop is hit, we lose
   about $500 on $100,000. Shares = risk ÷ (entry price − stop price).
2. Then the hard limits cut it down if needed: ≤ 15% of the account per stock, ≤ 1% of the stock's daily trading,
   ≤ 25% per sector, ≤ 40% per unproven strategy, and total invested ≤ the **exposure dial** (50% this week).
3. Thinly traded stocks need **your approval**. Say "approve #3", "approve #3 half size" or "reject #3" in chat,
   or use the buttons on the Review page.

## Predictions
Opus writes 2–5 predictions a day that a computer can check, for example "Healthcare (XLV) will beat SPY over the
next 20 trading days, 57%". When the time is up they're scored automatically. Over weeks this shows whether the
AI's market reading is any good: if its "60%" calls come true about 60% of the time, it's **well calibrated**.

> These notes are for learning. They are not financial advice.
