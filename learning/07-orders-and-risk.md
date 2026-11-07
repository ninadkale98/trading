# 7. Orders and Risk: How Not to Lose Big

> Good investors aren't the ones who are always right. They're the ones who
> **lose small when wrong** and **win bigger when right**.

## Order types

| Order | What it does | When to use |
|---|---|---|
| **Market order** | Buy or sell **right now** at the best available price | When speed matters more than price. Risky in fast markets or for thinly traded stocks. |
| **Limit order** | Buy only at **this price or better** (sell at this price or higher) | **Default choice.** You control the price. It may not fill. |
| **Stop order (stop-loss)** | When the price hits X, send a **market** order to sell | Automatic exit if you're wrong |
| **Stop-limit order** | When the price hits X, send a **limit** order | Avoids a terrible fill, but may not sell at all in a crash |
| **Trailing stop** | A stop that **moves up** as the price rises (for example, always 10% below the highest price) | Locks in gains as a stock goes up |

**Time in force:**
- **Day:** cancels at the end of the day if not filled.
- **GTC (good 'til canceled):** stays open until filled or canceled (Robinhood cancels it after about 90 days).

## Stop-loss and gap risk

A **stop-loss** says "if I'm wrong, get me out at about this price."

**But it can't protect you from a gap.** Using Intel:
- You buy at $92, with a stop-loss at $85 (a planned loss of about 8%).
- Earnings come out after the close. The next day the stock **opens at $68.36**.
- Your stop triggers at the open, and you sell around **$68**, a **26% loss**, not 8%.

This is why we **avoid holding new positions through earnings**, or keep them
small if we do.

## Position sizing (the most important risk tool)

**Position sizing** = deciding **how much** to buy, so that one mistake can't hurt
you badly.

### The 1–2% rule

Risk only **1–2% of your total account** on any single position. "Risk" here means
the money you lose if your stop-loss is hit.

**Example:**
- Account: $5,000
- Max risk per position: 1% = **$50**
- Entry: $100, stop-loss: $92 → risk per share = **$8**
- Shares to buy: $50 ÷ $8 = **6 shares** (about $600 position)

**If you're wrong:** you lose about $50 (1%).
**If you're wrong 5 times in a row:** you lose about 5%. Painful, but you can recover.

Compare with putting all $5,000 into Intel at $92: after Oct 30 you'd have about $3,570
(**−29%**), and after Nov 5 about $2,840 (**−43%**).

## Diversification and concentration

- **Diversification** = spreading money across different stocks **and sectors**, so one
  bad event doesn't sink everything.
- **Concentration risk** = too much money in one stock or sector.

**From our scan:** 6 of 13 results were oil and gas (CVX, XOM, EOG, COP, APA, LNG).
If oil prices drop, **all six** fall together. Buying all six is really **one bet**,
not six. Pick one or two at most from the same sector.

**Correlation** = how much two stocks move together. Oil companies are highly
correlated with each other. Intel, AMD and Dell fell together on Oct 30.

## Scaling in (buying in steps)

Instead of buying everything at once, buy in **2–3 smaller steps**:
- 1/3 now, 1/3 if it holds support for a week, 1/3 after it confirms an uptrend.
- You get a better average price if it dips more, and less regret if you're wrong.

## Risk/reward ratio

**Formula:** `(Target price − Entry) ÷ (Entry − Stop-loss)`
**Example:** Entry $100, stop $92 (risk $8), target $124 (reward $24) → **3:1**.
Look for **at least 2:1**. Then you can be wrong more than half the time and still
make money.

## Account types

| Type | Meaning |
|---|---|
| **Cash account** | You can only spend money you actually have. **Our MCP account is a cash account.** |
| **Margin account** | You can borrow from the broker to buy more. That increases both gains **and losses**. Your main Robinhood account is margin. |
| **Settlement (T+1)** | After you sell a stock, the cash takes 1 business day to "settle" before you can use it again in a cash account. |
| **Buying power** | How much you can spend right now. |

## Emotional traps

| Trap | What it looks like |
|---|---|
| **FOMO** (fear of missing out) | Buying after a stock already went up a lot |
| **Anchoring** | "It was $140, so $56 must be cheap." The old price doesn't matter. |
| **Averaging down blindly** | Buying more of a loser without a reason other than "it's lower now" |
| **Revenge trading** | Making a bigger bet to win back a loss |
| **Moving your stop** | Lowering your stop-loss because you "believe" in the stock |

**The bot's real value is to follow the rules even when emotions say otherwise.**

## Our risk rules (draft)

1. Max **1–2% of the account at risk** per position.
2. Max **2 positions per sector**.
3. **No new buys within about 10 trading days before earnings**.
4. **Decide the stop-loss before buying**, and never move it lower.
5. **Limit orders** by default.
6. Start with **paper or small money** until the strategy proves itself.
