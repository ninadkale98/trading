# Stock View

Open a stock like a file. Any `*.stock` file opens as an interactive candlestick
chart with volume, moving averages, highlights, markers and a range-selection tool.

## Use it

- **Open a stock:** Command Palette → `Stock View: Open Stock…` → type `INTC`.
  This creates `charts/INTC.stock` and opens it.
- **Select a range:** hold **Shift and drag** across the chart, or press **S**
  (Select mode) and drag. A stats panel shows change, high/low, drawdown, best and
  worst day, gaps, volume vs normal, and RSI at the end.
  - **📌 Pin** saves the range as a highlight in the `.stock` file.
  - **Copy** copies a text summary (for example, to paste into Claude).
  - **Esc** clears the selection.
- **Hover** any candle to see OHLC, % change, gap, volume, RSI and moving averages.
- **Range buttons** (1M … Max), **moving-average toggles** (20/50/200), **F** to fit all data.
- See the raw file: right-click the tab → *Reopen Editor With…* → *Text Editor*.

The current selection is also shown in the status bar (click it to copy) and
written to `.stockview/selection.json`.

## The `.stock` file

```json
{
  "symbol": "INTC",
  "range": "6mo",
  "interval": "1d",
  "indicators": ["sma50", "sma200"],
  "note": "Free text shown under the header",
  "highlights": [{ "from": "2026-10-29", "to": "2026-11-05", "label": "Post-earnings selloff", "color": "#ef4444" }],
  "markers": [{ "date": "2026-10-30", "text": "Q4 guide-down", "position": "above", "color": "#ef4444" }],
  "lines": [{ "price": 65.76, "label": "Oct 30 close", "color": "#f59e0b" }]
}
```

`range`: `1mo 3mo 6mo ytd 1y 2y 5y max` · `interval`: `1d 1wk 1mo` ·
`indicators`: `sma20 sma50 sma200`. Optional `"bars": [{ "t","o","h","l","c","v" }]`
uses your own data instead of downloading it.

Edits to the file show up on the chart right away.

## Control from Claude / scripts

Write `.stockview/control.json` (each command needs a unique `id`):

```json
{ "commands": [
  { "id": "1", "action": "open", "symbol": "AMD", "beside": true, "spec": { "range": "1y" } },
  { "id": "2", "action": "select", "symbol": "INTC", "from": "2026-10-29", "to": "2026-11-05" },
  { "id": "3", "action": "close", "symbol": "AMD" }
] }
```

Actions: `open`, `update`, `select`, `clearSelection`, `focus`, `close`, `closeAll`.
Results and the list of open charts are in `.stockview/state.json`.

## Data

Prices come from **Alpaca** (full-market data, ≥15 min delayed) when `ALPACA_KEY_ID` / `ALPACA_SECRET_KEY` are in the workspace `.env`, otherwise from Yahoo Finance's public chart endpoint. Set `"source": "yahoo"` in a `.stock` file to force Yahoo. Prices
refresh every 60 seconds while a chart is visible. Charts use TradingView
Lightweight Charts (Apache 2.0, see `media/LIGHTWEIGHT-CHARTS-LICENSE`).
