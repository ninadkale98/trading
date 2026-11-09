# 14. How the System Improves Itself

The goal: the system keeps getting better at understanding the market without anyone writing every idea by hand.
It works in a loop. Each turn uses what the last turn learned. That's why it's called a **self-improving loop**.

## Level 1: the strategy lab (automatic, twice a week)

Sunday 12:00 and Wednesday 11 pm (New York time):

1. **Propose (Opus).** Opus reads the lab notebook (every lesson so far), the results of every strategy (backtest and
   live), what research says works, and the list of numbers we have for each stock. Then it suggests about 4 new ideas,
   or variations of ideas that showed promise. For each one it writes the **hypothesis first**: why it might work, and
   what result would prove it wrong. Writing that before testing keeps us honest.
2. **Build (Sonnet).** Sonnet turns each idea into a small Python strategy file.
3. **Safety check.** Fixed code reads the file before it ever runs. Only math is allowed: no files, no internet, no
   loops that could hang, and **no peeking at the future** (like using tomorrow's price).
4. **Smoke test.** The file runs in its own separate program on the last 2 years of data for 300 stocks. It must work,
   be fast, and pass the **look-ahead check**: its answer for a day must stay the same when every later day is deleted.
   If it breaks, the error goes back to Sonnet to fix (up to 3 tries).
5. **Full test.** 2016–2022 for ~9,000 stocks, including companies that later went bankrupt or were bought (so we don't
   fool ourselves with only survivors). Two questions: do the picked stocks beat the average stock over 1, 4 and 12
   weeks (the **signal study**)? And does the full strategy, with its stops, beat SPY and a **random twin**?
6. **Decide (fixed rules, not the AI).**
   - Any **sign of life** (picks beat the average stock, even weakly) → it goes **live** in our dry run / paper account
     at a small size (0.5% risk per trade). The bar is low on purpose: it's practice money, and live results are the
     real test.
   - Passes the strict gates *and* still works on 2023–2024, years it never saw → promoted to `paper/`.
   - No edge, too few signals, or errors → **retired**. The file is kept so the same idea isn't tried again blindly.
   - More than 16 live strategies → the one with the weakest evidence is retired. A strategy that loses against SPY
     over 15+ live trades is retired too.
7. **Report (Opus).** What each idea tested, the numbers, the decision, and the **lessons**. These are added to
   `lab/notebook.md`, which step 1 reads next time. When Opus wishes it had some data we don't have (say, short
   interest), it writes a **feature request** in `lab/requests.md`.

## Level 2: the engineer (weekly, needs your OK)

Saturday 12:30 pm, Claude Code works as the **engineer**. It reads the feature requests, the week's errors and the
trade-review lessons, and picks one improvement, usually adding the data or numbers the lab asked for. It works on its
own copy of the code (a separate **git branch**), writes tests, and records its work there.

Then fixed checks run: all tests pass, every live strategy still works, new numbers pass the look-ahead check, and
nothing touches the protected parts (money, risk limits, the tests that grade strategies, secrets).

**It never changes the running system on its own.** You see it on the Lab page and in `reports/engineer/`. Say
"merge engineer #N" in chat to accept it, or "reject engineer #N". Once merged, the next lab round can use the new
numbers. That closes the loop: the lab asks, the engineer builds, the lab uses it.

## Why the AI can't fool itself

| Risk | Guard |
|---|---|
| Code that peeks at the future looks brilliant in tests and fails live | Safety check + look-ahead check (the day-t answer must not change when later days are deleted) |
| Trying many ideas: some look good by pure luck | Every test raises the bar for "significant" (the **multiple-testing** penalty); live results decide |
| The AI grading its own homework | The rules, tests and gates are fixed code the AI can't edit |
| A broken strategy stopping the daily plan | Each strategy runs separately; a failing one is skipped and logged |
| An AI change breaking the system | Engineer changes wait for your OK; tests run again before merging |
| Real money | Never automatic. The AI has no access to the Robinhood account |

## Where to see it
- **Lab page** on the dashboard: ideas, rounds (with Opus's reasoning), strategy moves, engineer runs.
- `reports/lab/` (round reports), `lab/notebook.md` (all lessons), `lab/requests.md` (feature requests).
- In the terminal: `tradebot lab`, `tradebot engineer`.

> These notes are for learning. They are not financial advice.
