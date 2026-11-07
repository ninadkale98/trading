# 12. What Research Says About Strategies (beyond price charts)

Compiled Nov 2026 by an AI research agent from academic papers and practitioner studies (links below each section).
Treat it as a map of the evidence, not gospel: check a source before relying on a specific number.

## Two facts to keep in mind first

1. **Published effects shrink.** Across 97 published stock-return patterns, returns fell **~58% after publication**:
   part was luck in the original data, part was investors trading it away
   ([McLean & Pontiff 2016](https://counterpointfunds.com/wp-content/uploads/2017/07/PredictabilityMcleanPontiff.pdf)).
2. **Many effects only exist in tiny stocks.** Of 447 published patterns, **64% fail** once tiny "microcap" stocks stop
   dominating the test ([Hou, Xue & Zhang](https://www.nber.org/papers/w23394.pdf)). We trade liquid stocks, so expect
   roughly half of any number in a paper.

## The families, in plain words

| Family | Idea | Evidence | Can we test it on history? |
|---|---|---|---|
| **News tone** | Prices react slowly to company news, especially bad news | Negative wording in company news predicts weaker earnings and returns ([Tetlock et al. 2008](https://econpapers.repec.org/RePEc:bla:jfinan:v:63:y:2008:i:3:p:1437-1467)); a **week** of news sentiment predicts returns for ~13 weeks ([Heston & Sinha](https://www.federalreserve.gov/econresdata/feds/2016/files/2016048pap.pdf)) | Yes, with a fixed word list (no AI) on 2019–2025 news |
| **AI reading news** | An LLM scores each headline | Strong results, but an AI that was trained on the future "remembers" what happened, which inflates old-data tests ([Glasserman & Lin](https://arxiv.org/abs/2309.17322)); cleaner tests keep about half the edge ([He et al.](https://arxiv.org/abs/2510.11677v2)) | **Only going forward** (what we do now with Haiku) |
| **Earnings surprise drift** | After a surprise, prices keep drifting that way | Historically strong; **largely gone in non-tiny stocks since ~2006** ([Martineau](https://cfr.ivo-welch.info/published/papers/martineau2021rest.pdf)); earnings momentum explains much of price momentum ([Novy-Marx](https://mysimon.rochester.edu/novy-marx/research/FMFM.pdf)) | Yes (SEC filings). Best used as a **filter** with momentum |
| **Earnings-call tone** | How managers talk predicts the next ~3 months | Word-count tone beat the earnings surprise ([Price et al. 2012](https://econpapers.repec.org/RePEc:eee:jbfina:v:36:y:2012:i:4:p:992-1011)) | Word lists: yes. Claude reading calls: forward only |
| **Analyst estimate revisions** | When analysts raise estimates, stocks keep rising | One of the stronger historical signals ([Chan, Jegadeesh & Lakonishok](https://rpc.cfainstitute.org/research/financial-analysts-journal/1999/the-profitability-of-momentum-strategies)); rating *changes* matter, rating *levels* don't | No free history: we started saving daily snapshots (Nov 2026) |
| **Insider buying** | Executives buying their own stock with their own money | Purchases earn **> 6%/year** above the market, sales ≈ nothing ([Jeng et al.](https://scholar.harvard.edu/sites/scholar.harvard.edu/files/rzeckhauser/files/insider_trading.pdf)); "opportunistic" (non-routine) buys ≈ **0.8%/month** ([Cohen, Malloy & Pomorski](https://www.nber.org/digest/apr11/decoding-inside-information)); clusters of insiders stronger | **Yes, fully** (SEC Form 4, 2.3M trades loaded) |
| **Customer → supplier links** | News about a big customer reaches suppliers late | ~1.5%/month originally ([Cohen & Frazzini](https://ideas.repec.org/a/bla/jfinan/v63y2008i4p1977-2011.html)), **much weaker since publication** ([Pinchuk](https://ideas.repec.org/p/arx/papers/2301.11394.html)) | Yes, once the economy map has links (from 10-Ks) |
| **Themes ("AI needs chips")** | Buy what the big story favors | Thematic funds **underperform after launch**: they buy after the story is famous ([Ben-David et al.](https://www.nber.org/system/files/working_papers/w28369/revisions/w28369.rev2.pdf)) | The edge, if any, is in **less-watched second-order** companies, with a delay |
| **Macro timing / sector rotation** | Use the economy to switch sectors or time the market | Popular predictors failed out of sample ([Goyal & Welch](https://econpapers.repec.org/RePEc:oup:rfinst:v:21:y:2008:i:4:p:1455-1508)); even *perfect* recession foresight gave little after costs ([CXO](https://www.cxoadvisory.com/economic-indicators/perfect-sector-rotation)); credit stress does warn of recessions ([Fed](https://www.federalreserve.gov/econresdata/notes/feds-notes/2016/recession-risk-and-the-excess-bond-premium-20160408.html)) | Yes, but expect little: use it as a **risk dial**, not a picker |
| **Quality** | Profitable, solid companies | Gross profitability predicts returns about as well as cheapness ([Novy-Marx 2013](https://www.ivey.uwo.ca/media/3775548/novy-marx.pdf)) | Yes (SEC filings) |
| **CANSLIM / Minervini** | Popular trader checklists | No rigorous tests; their pieces (near 52-week high, earnings momentum) do have evidence ([George & Hwang](https://typeset.io/pdf/the-52-week-high-and-momentum-investing-4u9j16d52p.pdf)) | Yes, piece by piece |

## What this means for us

- **Most promising to test first:** insider cluster buying · earnings surprise + momentum + 52-week high · weekly news
  tone · quality as a filter · Claude reading earnings calls and guidance (forward) · analyst revisions (once we have
  months of snapshots).
- **Understanding the economy still matters**, but mainly to *explain* the market and to manage risk (how much to
  invest), not as a direct stock picker. The obvious story is usually in the price already.
- **The honest way to judge AI judgment:** write predictions down *today*, score them later. That's the predictions log.

> These notes are for learning. They are not financial advice.
