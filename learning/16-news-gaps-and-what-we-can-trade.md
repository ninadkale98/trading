# 16. News, Gaps, and What We Can Actually Trade

A real case from our own system: **Nvidia, Sunday 8 November 2026**.

## What happened

| Time (ET) | Event | Nvidia price |
|---|---|---|
| Fri 4:00 pm | Market closes | **$186.7** |
| Sun 4:20 pm | Headline: CEO admits an affair with a suspected spy; board will investigate | (market closed) |
| Sun 4:37 pm | Our Haiku labels it: *management, negative, importance 3* | (market closed) |
| Sun 9:01 pm | "Board initiates independent investigation" → *importance 4* | (market closed) |
| **Mon 4:00 am** | **First trade of the pre-market** | **$178.7 (−4.3%)** |
| Mon 10:00 am | Regular session | about $179 (flat since 4 am) |

## The lesson: knowing is not the same as being able to trade

Our system **knew within 17 minutes**. But there was no moment when we could have sold at Friday's price:

- Between Sunday 4:20 pm and Monday 4 am, regular US exchanges were closed.
- The very **first** trade on Monday was already 4.3% lower.

This hole on the chart is called a **gap**. Every seller who reacted to the news met the gap at the first
price. So did every buyer.

**The whole move happened in the gap.** After 4 am the price was flat. Reading the news faster would not have
earned anything: no one could act on it before the price had already moved.

Who *could* have profited?
- Only someone already **short** before Friday's close. That is a bet, not reading the news.
- Possibly someone trading on an **overnight venue** on Sunday evening. Those prices usually adjust too.

## So what is news good for, for us?

We hold for weeks to months. For us news is useful in three ways:

1. **Don't walk into it.** If we had planned to buy Nvidia on Monday, buying blind into a CEO scandal is a mistake.
   Since 9 Nov 2026 the system checks before every open, at 9:20 am. If a planned buy got **major bad news**
   (importance 4–5) after the plan was made, that buy is skipped and the headline is saved as the reason.
2. **See it.** The 6:30 am briefing now lists the biggest companies with major news, including weekend and
   overnight news.
3. **The drift after the gap.** This is the research question. After big bad news, does the stock keep falling for
   weeks, or bounce back? Research says both can happen:
   - **Drift:** surprising news keeps moving prices for weeks, because investors adjust slowly. This is the same
     idea as post-earnings drift (learning/15).
   - **Overreaction:** scandal-type news often hits too hard, then recovers.

   We don't guess which. Haiku is labeling all headlines back to 2019. When it's done, the lab measures what really
   happened after news like this, across thousands of cases.

## Was the drop predictable from the news?

Not as clearly as it looks afterwards. The same morning:
- Goldman Sachs and RBC repeated their Buy ratings.
- The President said he backed the CEO.
- Some analysts called the drop a buying chance.

The news was clearly *bad*, but how much the price would fall, and whether it would keep falling, was not obvious.
That's why we test it on history instead of trusting a story.

## Do big companies always bounce back after a crash?

This was the user's idea (Nov 2026). The example: Qualcomm went from 147 to 170 in a month. We tested it on 10 years
of prices. A "crash" here means the stock closed 25% or more below its 60-day high.

| Which stocks | Beat the S&P 500 over 6 months |
|---|---|
| Any of the 50 most-traded stocks | about half the time (a coin flip) |
| Only **steadily big** companies (among the 100 most-traded for 2 years straight) | a bit more than half |
| Steadily big **+ heavy-volume selling** (a down day with 2× normal volume) | **58%**, about +9% on average |

What it means:
- **Not "always".** Netflix in Jan 2022 fell another 66% in 6 months, PayPal 56% and Shopify 71%.
- **"Big" has to mean established.** Hype stocks (Coinbase, AMC, Upstart) make the idea look bad.
- **Heavy-volume selling helps.** That's **capitulation**: the last panicked sellers give up.
- **It's still bumpy.** About half fell another 15% first.
- **Be careful with "the usual price".** Qualcomm traded between 128 and 249 in 2026 alone, so its "usual" price
  moved a lot. Treating an old price as the right one is called **anchoring**. "Far below its recent high" is a
  measurable version of the same idea.

You can watch it live: the **Crash watch** on the dashboard's Market page (and in the briefing) lists every steadily
big company that's 15%+ below its 60-day high, with its heavy-selling day and whether volume is calming.

Next: the lab tests it as a strategy with fixed rules. Then it's tested on years it wasn't designed on, and finally
in simulation.

> These notes are for learning. They are not financial advice.
