# 2. Earnings: Why Stocks Jump or Crash Every 3 Months

## What is an "earnings report"?

Every quarter (every 3 months), US public companies must publish their results:
revenue, profit, margins and so on. That's the **earnings report**. Most companies
also hold an **earnings call**, where the CEO and CFO talk to analysts and answer
questions.

**Timing:**
- **"pm"** = after the market closes (4:00 pm ET). Intel reports after the close.
- **"am"** = before the market opens (9:30 am ET).
- Either way, the big price move happens when trading resumes, often as a **gap**
  (see [04-price-and-volume.md](04-price-and-volume.md)).

Intel's next report: around **January 21, 2027** (not yet confirmed).

## Earnings season: when do companies report?

Companies don't all report on the same day, but most report within the same
**4–6 week window** after each calendar quarter ends. That window is **earnings season**.

| Quarter ends | Earnings season (roughly) |
|---|---|
| Mar 31 (Q1) | mid-April → mid-May |
| Jun 30 (Q2) | mid-July → mid-August |
| Sep 30 (Q3) | mid-October → mid-November |
| Dec 31 (Q4) | mid-January → late February (often longer, since it's also the yearly report) |

**Typical order within a season:**
1. **Big banks go first** (JPMorgan, Wells Fargo and others), about 2 weeks after the quarter ends. They set the mood.
2. **Peak weeks** come 3–5 weeks after the quarter ends. Hundreds of companies report each week,
   including the big tech names (Microsoft, Apple, Amazon, Meta, Alphabet, Intel, AMD).
3. **Stragglers** report last: smaller companies, and retailers like Walmart and Target.

**Intel:** Q3 ended Sep 26 → reported Oct 29 (about 5 weeks later, in the peak weeks).

### Companies on a different calendar ("off-cycle")

Some companies' **fiscal year** doesn't match the calendar year, so they report at
other times.

| Company | Fiscal year ends | Reports around |
|---|---|---|
| NVIDIA | late January | late Feb, May, Aug, Nov |
| Oracle, Micron, FedEx, Nike | May / end of summer | mid-to-late March, June, Sept, Dec |
| Walmart, Target, Home Depot | late January | mid-to-late Feb, May, Aug, Nov |

**Why this matters:** One company's results can move others. NVIDIA reporting
off-cycle can move the whole chip sector between earnings seasons.

### Time of day

- **Before the open (BMO):** results around 6–8 am ET, call around 8–9 am ET.
- **After the close (AMC):** results around 4:00–4:15 pm ET, call around 4:30–5:00 pm ET.
- Companies almost never report **during** market hours, so the reaction happens
  in pre-market or after-hours and shows up as a **gap**.

### The legal deadline

The SEC requires the quarterly filing (**10-Q**) within about **40 days** of the quarter's
end for large companies, and the yearly filing (**10-K**) within about **60 days**.
That's why earnings seasons cluster in those windows.

### Ripple effects

Stocks in the same industry react to each other's reports. When Intel guided low
on Oct 29, **AMD fell 10% and Dell 13%** the next day even though they hadn't
reported. Investors assumed the PC slowdown would hurt them too. So even a stock
that isn't reporting carries earnings risk during earnings season.

## EPS: Earnings Per Share

**Formula:** `Net income ÷ Number of shares`
**In plain words:** how much profit belongs to each single share you own.

**Example:** A company earns $1B and has 500M shares → EPS = **$2.00**.

EPS is the single most-watched number in an earnings report.

## Estimates (the "consensus")

Before the report, analysts publish their predictions. The average is the
**consensus estimate**. The stock price *already reflects* these expectations.

## Beat, miss, in line

| Result | Meaning |
|---|---|
| **Beat** | Actual is better than the estimate |
| **Miss** | Actual is worse than the estimate |
| **In line** | About the same |

**Intel's history (adjusted EPS, from Robinhood):**

| Quarter | Estimate | Actual | Result |
|---|---|---|---|
| Q1 2026 | −$0.01 | $0.29 | Big beat |
| Q2 2026 | $0.19 | $0.42 | Big beat |
| Q3 2026 | $0.37 | $0.52 | Big beat |

Intel kept beating estimates by a wide margin. So why did it crash?

## Guidance: the number that really moves the stock

**Guidance** = what the company says it expects for the **next** quarter or year.

**The key idea:** A stock price is a bet on the **future**, not a reward for the past.
Last quarter is already history. Guidance tells you about the future.

### The Intel case study (October 29–30, 2026)

| | Wall Street expected | Intel guided | Gap |
|---|---|---|---|
| Q4 revenue | ~$17.1B | $15–16B | ~8% lower |
| Q4 adjusted EPS | ~$0.43 | ~$0.25 | ~40% lower |
| Q4 gross margin | — | ~38% (down from 44%) | — |

And the CFO said the PC slowdown would continue **"at least through the first
half of next year."**

**Result:** The stock closed at $92.07 on Oct 29. It opened at **$68.36** on Oct 30
and closed at **$65.76**, down **28.6%**, its worst day since 1974.

### Why the fall was so big: "priced for perfection"

1. Intel had beaten estimates every quarter, so people expected another strong
   beat **and** strong guidance.
2. The stock had climbed from $85 to $95 in the week before earnings, so the
   good news was already in the price.
3. The guidance said the problem would last **several quarters**, not one.

> **Rule of thumb:** Stock move = Reality − Expectations.
> Good results with even higher expectations can still mean the stock goes down.

## Other earnings terms

| Term | Meaning |
|---|---|
| **Fiscal quarter (Q1–Q4)** | The company's own 3-month periods. They don't always match the calendar. |
| **Beat and raise** | Beat estimates **and** raised guidance. The best outcome. |
| **Beat and lower / guide down** | Beat estimates but lowered the outlook. That's what Intel did. |
| **Earnings surprise** | How far the actual result was from the estimate, in %. |
| **Whisper number** | The unofficial expectation traders hold, often higher than the consensus. |
| **Earnings season** | The few weeks each quarter when most companies report. |
| **Pre-announcement** | A company warns about results *before* the official date. Usually bad news. |
| **Implied move** | How much options traders expect the stock to move on earnings, based on option prices. |

## What this means for our bot

**Earnings are the biggest single risk for a weeks-to-months investment.** A stock can
fall 20–30% overnight, and no stop-loss can protect you from an overnight gap.

Rules we can add:
1. **Avoid new buys within about 10 trading days before earnings**, or keep them small.
2. **After a big earnings drop, wait** for the stock to stabilize before buying.
3. **Always know the next earnings date** of everything you hold. Robinhood's
   `get_earnings_results` gives us this.
