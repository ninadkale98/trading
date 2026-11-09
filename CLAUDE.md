# Trading project

Building an investing assistant/bot that finds good entry points for multi-week to
multi-month holds (not day trading). The user is learning; explain terms simply and
add new concepts to `learning/` (keep `learning/glossary.md` in sync).

**The agreed system design is in [docs/architecture.md](docs/architecture.md). Read it before building anything, and update it when the design changes.**
**Build progress is tracked in [docs/build-plan.md](docs/build-plan.md): check its Status table and Build log, continue from the first unchecked item, and keep checkboxes and the log up to date.**

## Robinhood (MCP server `robinhood-trading`)
- Only the account nicknamed **MCP** is tradable by the agent; the main margin account is read-only to us.
- **Never place, modify, or cancel an order without the user's explicit confirmation in chat for that specific order.**
- Do not give personalized buy/sell advice; present data, both sides, and risk rules.
- Saved scan: "Quality Uptrend Pullback" (`5c72f6ca-0824-4dd5-a44c-ded2a2386141`), explained in `learning/08-our-scan-explained.md`.

## The running system (daemon + dashboard)
- Dashboard: http://ichigo:8090 (Tailscale) or localhost:8090. Status: `.venv/bin/tradebot status`, `tradebot plan`.
- Trading mode is `config/settings.yaml → trading.mode` (`dry_run` = simulated against real prices, `paper` = Alpaca PAPER
  orders). Switch to `paper` only when the user says so.
- **Approvals in chat:** when the user says "approve #3", "approve #3 half size" or "reject #3", run
  `.venv/bin/tradebot approve 3 [--size 0.5] [--comment "..."]` / `tradebot reject 3`. List with `tradebot approvals`.
- **Self-improving loop** (docs/architecture.md §9.1, learning/14): `lab.cycle` Sun 12:00 + Wed 23:00 ET is automatic
  (AI-written strategies go live in dry run/paper by fixed rules). The weekly engineer (Sat 12:30 ET) builds on a branch
  and **never merges by itself**: when the user says "merge engineer #N" run `.venv/bin/tradebot engineer-merge N`
  (review the diff first and tell the user what it does); "reject engineer #N" → `tradebot engineer-reject N`.
  Status: `tradebot lab`, `tradebot engineer`.
- Daily: news read by Haiku every 30 min; earnings press releases found on EDGAR every 20 min and read by Haiku (`tradebot earnings`, arch §7.1); 4:40 pm prices → features → snapshot → settle session → plan; 9 pm Opus
  market analysis (reports/market/); 9:30 pm briefing (reports/daily/).

## Alpaca (paper trading + market data)
- Keys are in `.env` (`ALPACA_KEY_ID`, `ALPACA_SECRET_KEY`); it is a **paper** account ($100k practice money). Never print or echo the key values.
- Use full-market data with `feed=sip` and an `end` at least 16 minutes in the past (the free plan requires that). `feed=iex` has only one exchange's volume, so don't use it for volume.
- Paper account is the testing ground for the bot's rules before any real money in the Robinhood MCP account.

## Stock View (VS Code extension in `stock-view/`)
Charts are files: `charts/<SYMBOL>.stock` (JSON) opens as a candlestick + volume chart.
Edit the file to change the chart live (range, indicators, note, highlights, markers, lines).

**To show the user something, write `.stockview/control.json`** (every command needs a new unique `id`):
```json
{ "commands": [
  { "id": "<unique>", "action": "open", "symbol": "AMD", "beside": true,
    "spec": { "range": "1y", "note": "...", "highlights": [{"from":"YYYY-MM-DD","to":"YYYY-MM-DD","label":"...","color":"#ef4444"}],
              "markers": [{"date":"YYYY-MM-DD","text":"...","position":"above"}], "lines": [{"price": 65.76, "label": "..."}] },
    "select": { "from": "YYYY-MM-DD", "to": "YYYY-MM-DD" } },
  { "id": "<unique>", "action": "select", "symbol": "INTC", "from": "2026-10-29", "to": "2026-11-05" },
  { "id": "<unique>", "action": "update", "symbol": "INTC", "spec": { "range": "1y" } },
  { "id": "<unique>", "action": "close", "symbol": "AMD" },
  { "id": "<unique>", "action": "closeAll" }
] }
```
- Then read `.stockview/state.json` for results (`lastCommands`) and which charts are open.
- **The user's current chart selection** (range + computed stats + bars) is in `.stockview/selection.json`. Read it when the user says "this part", "what I selected", "look at my selection", etc.
- `spec` fields merge into the file (`highlights`/`markers` arrays are replaced, so include existing ones to keep them).
- After changing extension code: `cd stock-view && npx --yes @vscode/vsce@3.6.0 package --allow-missing-repository --skip-license -o stock-view-0.1.0.vsix && code --install-extension stock-view-0.1.0.vsix --force`, then the user runs "Developer: Reload Window".
