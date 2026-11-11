# 15. Reading Earnings Press Releases

Every three months a company reports its results. The first full version is a **press release**, filed with the SEC
as part of an **8-K** (item 2.02 = "results of operations"). The release itself is attached as **exhibit 99.1**.
Professionals read it within minutes of it coming out. Our system now does the same for every stock we could trade.

## What's in a release

1. **The numbers for the quarter:** revenue, profit, and **EPS** (profit per share). There are usually two versions:
   - **GAAP**, the official accounting rules;
   - **adjusted (non-GAAP)**, which leaves out items the company calls one-time.
2. **The outlook (guidance):** what the company expects for the next quarter or the full year.
3. **The story:** management's quotes, highlights and explanations.

## Why guidance matters more than the quarter

The stock price already includes what people expect. The quarter that just ended is old news, half-guessed already.
The **outlook** is new information about the future, and it moves prices most. What counts is the *change* in it:

| Guidance | Example (real releases, Nov 2026) | Usual meaning |
|---|---|---|
| **Raised** | "Full-year revenue guidance raised to $344–346M from $334–340M" | Business is better than the company thought 3 months ago |
| **Maintained** | "Maintains annual revenue guidance of $330–340M" | On track; no new information |
| **Lowered / withdrawn** | "Now expects …, compared with … previously" (lower), or "suspends its outlook" | Something got worse, or management can't see clearly |
| **Initiated** | First outlook for next year | New information, but nothing to compare it with |
| **Mixed** | Revenue up, profit down | Read the details |

## How our reader works

1. **Find it fast.** Every 20 minutes the system checks the SEC's live list of new 8-K filings. A release filed at
   4:05 pm is found by about 4:20 pm.
2. **Hide who it is.** Before Claude (Haiku) reads it, we remove anything that identifies the company or the date:
   - names → "the Company", and the ticker → "TICKER";
   - executives' names and web addresses;
   - years → "Y0" (this year), "Y-1" (last year), "Y+1" (next year).

   Why: Claude knows what happened to famous stocks in past years. If it recognised "Nvidia, 2023", it might call the
   tone great *because it knows the stock soared*. That's **hindsight**, and it would make our backtests lie.
3. **Read with a fixed form.** Claude fills in:
   - revenue and EPS;
   - guidance (raised / maintained / lowered / initiated / withdrawn / mixed / none);
   - tone from −2 to +2;
   - one-offs;
   - up to 3 positives and 3 negatives.

   It must answer only from the text.
4. **Measure the surprise ourselves.** The **surprise** is actual minus expected (the **consensus estimate**). We take
   the estimate from our own daily calendar snapshot taken *before* the release, not from Claude. So nothing can leak.

   We show the EPS surprise two ways. **As % of the estimate** is the usual headline, but it blows up when the
   estimate is near zero: beating −$0.085 with +$0.17 reads "+300%". **As % of the share price** (professionals
   call it SUE-style) stays sensible: a $0.21 beat on a $78 stock is +0.27%. The briefing shows the dollar beat and
   the % of price; the feature `eps_surprise_px` stores it for strategies.
5. **Turn it into numbers strategies can use:**
   - `release_tone` (−2…+2);
   - `guidance_change` (+1 raised, −1 lowered or withdrawn, 0 otherwise);
   - `rev_surprise`.

   Each appears on the release's **reaction day**, the first trading day that could react to it, and is replaced at
   the company's next release.

## Live reads vs history reads

- **Live** reads happen within 3 days of the release. Claude can't know what happened next, so these are clean.
- **History** reads cover old releases (2016 onward), about 40 an hour, in a random order. A random order means any
  partial fill is a fair sample of all years. Masking helps, but it isn't perfect: in testing, one company's old name
  survived inside a business-segment name. So history reads are good for research. Real proof comes from live results.

## Why Haiku (the cheapest model)?

We tested Haiku against Sonnet on 6 real releases:
- They gave the same guidance label and tone in all 6, and the same numbers.
- Sonnet found one extra adjusted EPS.
- Haiku costs about 1/13 as much.

Using one model for every read also keeps the numbers comparable across years.

## What we'll test next

- Does "guidance raised" predict that a stock beats the average over the next 1–3 months?
  This is **post-earnings drift**: research says prices adjust to earnings news slowly.
- Is it stronger when the price gap on the reaction day *holds* instead of fading?
- Does a good tone with a bad price reaction mean the market overreacted?

The lab tests these once about 10,000 history reads exist (about 2 weeks).

Try it: `.venv/bin/tradebot earnings` shows the latest reads.

> These notes are for learning. They are not financial advice.
