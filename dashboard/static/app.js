// Tradebot dashboard: one page, hash routes, plain JS. Every view reads /api/* and refreshes itself.
"use strict";

const $ = (sel) => document.querySelector(sel);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (v, d = 0) => (v == null || v === "" || isNaN(v)) ? "—" : Number(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const money = (v, d = 2) => (v == null || isNaN(v)) ? "—" : "$" + num(v, d);
const pct = (v, d = 2) => (v == null || isNaN(v)) ? "—" : (v > 0 ? "+" : "") + num(v, d) + "%";
const cls = (v) => (v > 0 ? "up" : v < 0 ? "down" : "");

function when(ts) {
  if (!ts) return "—";
  const d = new Date(ts);
  if (isNaN(d)) return esc(ts);
  const today = new Date().toDateString() === d.toDateString();
  return today ? d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
               : d.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}
function ago(ts) {
  if (!ts) return "never";
  const s = (Date.now() - new Date(ts).getTime()) / 1000;
  const fut = s < 0, a = Math.abs(s);
  const t = a < 60 ? `${Math.round(a)}s` : a < 3600 ? `${Math.round(a / 60)} min` : a < 172800 ? `${(a / 3600).toFixed(1)} h` : `${Math.round(a / 86400)} days`;
  return fut ? `in ${t}` : `${t} ago`;
}
function dur(fromTs) {
  const s = (Date.now() - new Date(fromTs).getTime()) / 1000;
  return s < 120 ? `${Math.round(s)}s` : s < 7200 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`;
}
const badge = (text, kind) => `<span class="badge b-${kind}">${esc(text)}</span>`;
const statusBadge = (s) => badge(s, { done: "good", failed: "bad", running: "info", pending: "mute", deferred: "warn", expired: "mute", cancelled: "mute" }[s] || "mute");
const table = (head, rows, empty = "Nothing here.") => rows.length
  ? `<div class="table-wrap"><table><thead><tr>${head.map((h) => `<th class="${h.startsWith("#") ? "num" : ""}">${esc(h.replace(/^#/, ""))}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`
  : `<p class="muted">${esc(empty)}</p>`;

function progressText(p) {
  if (!p || !Object.keys(p).length) return "";
  return Object.entries(p).filter(([, v]) => typeof v !== "object").map(([k, v]) => `${k}: ${typeof v === "number" ? num(v) : esc(v)}`).join(" · ");
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 3500);
}
async function act(path, body) {
  try {
    const r = await api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    toast(r.message || "Done"); refresh();
  } catch (e) { toast("Failed: " + e.message); }
}
window.act = act;

function alertsBlock(items) {
  if (!items.length) return `<div class="allgood">✓ All good: the system is running and the data is up to date.</div>`;
  return `<ul class="alerts">${items.map((a) => `<li class="${esc(a.level)}">${esc(a.text)}</li>`).join("")}</ul>`;
}

// Minimal Markdown for briefings: headings, bold, italics, links, lists, tables, paragraphs.
function md(src) {
  const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\*(.+?)\*/g, "<i>$1</i>")
    .replace(/`(.+?)`/g, "<code>$1</code>").replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2">$1</a>');
  const out = []; let list = null, tbl = null;
  const flush = () => { if (list) { out.push(`<ul>${list.join("")}</ul>`); list = null; } if (tbl) { out.push(table(tbl[0], tbl.slice(1).map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`))); tbl = null; } };
  for (const line of src.split("\n")) {
    const h = line.match(/^(#{1,3})\s+(.*)/);
    if (h) { flush(); out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); continue; }
    if (/^\s*[-*]\s+/.test(line)) { if (tbl) flush(); (list ||= []).push(`<li>${inline(line.replace(/^\s*[-*]\s+/, ""))}</li>`); continue; }
    if (/^\|/.test(line)) { if (list) flush(); if (/^\|[\s:|-]+\|$/.test(line)) continue; (tbl ||= []).push(line.split("|").slice(1, -1).map((c) => c.trim())); continue; }
    flush(); if (line.trim()) out.push(`<p>${inline(line)}</p>`);
  }
  flush(); return out.join("");
}

// ── Views ─────────────────────────────────────────────────────────────────────────────────────────────────
const views = {
  async review() {
    const d = await api("/api/review");
    const last = d.last24h.map((t) => `<tr><td>${esc(t.type)}</td><td class="num">${num(t.n)}</td><td class="small">${esc(t.summary || "")}</td><td class="num small">${when(t.last)}</td></tr>`);
    return `
      <h1>Review</h1><p class="sub">Your daily 10–15 minutes: what needs you, and what happened.</p>
      <div class="card"><h2>Needs attention</h2>${alertsBlock(d.attention)}</div>
      <div class="card"><h2>Decisions needed</h2>
        ${d.approvals.length ? d.approvals.map((a) => `<div class="card" style="margin:8px 0">
            <div class="row"><b>#${a.id} ${esc(a.title)}</b><span class="spacer"></span><span class="small muted">deadline ${when(a.deadline)}</span></div>
            <p class="small"><b class="up">For:</b> ${esc(a.case_for || "")}</p><p class="small"><b class="down">Against:</b> ${esc(a.case_against || "")}</p>
            <p class="small muted">Risk ${money(a.risk_dollars, 0)} · position ${money(a.position_value, 0)} · limit ${money(a.limit_price)} · stop ${money(a.stop)}</p>
            <div class="row"><button class="primary" onclick="act('/api/approvals/${a.id}',{approve:true,size:1})">Approve</button>
              <button onclick="act('/api/approvals/${a.id}',{approve:true,size:0.5})">Approve half size</button>
              <button onclick="act('/api/approvals/${a.id}',{approve:false})">Reject</button></div></div>`).join("")
          : `<div class="placeholder">No approval requests. Thinly traded stocks, conviction bets and other unusual trades wait here for your OK. No answer by 9:15 am ET means no trade.</div>`}
      </div>
      <div class="card md"><h2>Daily briefing ${d.briefing ? `<span class="muted small">${esc(d.briefing.date)}</span>` : ""}</h2>
        ${d.briefing ? md(d.briefing.markdown) : `<div class="placeholder">The first daily briefing is published at 9:30 pm ET once the briefing step is built (Phase 2.7).</div>`}
      </div>
      <div class="card"><h2>Last 24 hours</h2>${table(["Job", "#Runs", "Latest result", "#Last"], last, "Nothing ran in the last 24 hours.")}</div>`;
  },

  async market(param) {
    const d = await api("/api/market" + (param ? `?day=${encodeURIComponent(param)}` : ""));
    const m = d.snapshot;
    if (!m) return `<h1>Market</h1><div class="placeholder">The first market snapshot appears after the evening price update (4:40 pm ET on trading days).</div>`;
    const lvl = m.regime_detail.level, b = m.breadth || {}, sg = m.signals || {};
    const lvlKind = { healthy: "good", mixed: "warn", defensive: "bad" }[lvl] || "mute";
    const p = (v, dd = 1) => (v == null ? "—" : `<span class="${cls(v)}">${pct(v * 100, dd)}</span>`);
    const quad = (q) => q ? badge(q, { leading: "good", improving: "info", weakening: "warn", lagging: "bad" }[q]) : "";
    const gRows = (rows, sortKey = "rel_20d") => [...rows].sort((a, b) => (b[sortKey] ?? -9) - (a[sortKey] ?? -9)).map((r) =>
      `<tr><td><b>${esc(r.symbol)}</b> <span class="small muted">${esc(r.name)}</span></td><td class="num">${p(r.ret_1d)}</td><td class="num">${p(r.ret_5d)}</td>
       <td class="num">${p(r.ret_20d)}</td><td class="num hide-sm">${p(r.ret_60d)}</td><td class="num">${p(r.rel_20d)}</td><td>${quad(r.quadrant)}</td></tr>`);
    const gHead = ["ETF", "#Day", "#Week", "#Month", "#3 months", "#vs SPY (month)", "Rotation"];
    const sigInfo = [
      ["credit_hy_vs_treasuries_20d", "Junk bonds vs Treasuries", "Up = investors comfortable lending to risky companies"],
      ["small_vs_large_20d", "Small vs large companies", "Up = appetite for riskier, smaller stocks"],
      ["cyclical_vs_defensive_20d", "Cyclical vs defensive sectors", "Up = betting on a strong economy"],
      ["equal_vs_capweight_60d", "Average stock vs S&P 500 (3 months)", "Down = the rally is carried by a few giants"],
      ["growth_vs_value_20d", "Growth vs value", "Up = market prefers fast growers"],
      ["long_bonds_20d", "Long-term Treasuries", "Up = yields falling (often fear or slowing growth)"],
      ["dollar_20d", "US dollar", "Up = money seeking safety or higher US rates"],
      ["gold_20d", "Gold", "Up = hedging against fear or inflation"],
      ["oil_20d", "Oil", ""], ["bitcoin_20d", "Bitcoin", "A speculative-appetite gauge"],
      ["fear_vixy_5d", "Fear gauge (week)", "Up = investors paying for crash protection"],
    ].map(([k, label, note]) => `<tr><td><b>${esc(label)}</b><div class="small muted">${esc(note)}</div></td><td class="num">${p(sg[k])}</td></tr>`);
    const sec = (m.sectors || []).map((r) => `<tr><td>${esc(r.sector)}</td><td class="num">${num(r.stocks)}</td><td class="num">${p(r.median_ret_20d)}</td>
      <td class="num hide-sm">${p(r.median_ret_60d)}</td><td class="num">${r.pct_above_50d == null ? "—" : num(r.pct_above_50d * 100, 0) + "%"}</td><td class="num">${num(r.avg_rs_rank, 0)}</td></tr>`);
    const stockRows = (rows) => rows.map((r) => `<tr><td><b>${esc(r.symbol)}</b><div class="small muted">${esc(r.sector || "")}</div></td>
      <td class="num">${money(r.close)}</td><td class="num">${p(r.ret_1d)}</td><td class="num">${p(r.ret_20d)}</td><td class="num hide-sm">${p(r.ret_60d)}</td>
      <td class="num">${num(r.rs_rank)}</td><td class="num hide-sm">${r.rvol == null ? "—" : num(r.rvol, 1) + "×"}</td></tr>`);
    const sHead = ["Stock", "#Price", "#Day", "#Month", "#3 months", "#RS rank", "#Rel. volume"];
    const fmtMacro = (r, v) => v == null ? "—" : r.unit === "%" ? num(v, 2) + "%" : r.unit === "k" ? num(v, 0) + "k" : num(v, Math.abs(v) < 20 ? 2 : 0);
    const macro = d.macro.map((r) => `<tr><td><b>${esc(r.label)}</b><div class="small muted">${esc(r.series)} · ${esc(r.date)}</div></td>
      <td class="num">${fmtMacro(r, r.value)}</td><td class="num muted">${fmtMacro(r, r.prev)}</td><td class="num hide-sm muted">${r.year_ago == null ? "" : fmtMacro(r, r.year_ago)}</td></tr>`);
    return `
      <div class="row"><h1>Market</h1><span class="spacer"></span><span class="muted small">${esc(m.date)}</span></div>
      <div class="card"><div class="row">${badge(lvl, lvlKind)} <b>${esc(m.regime)}</b></div>
        <p class="small muted" style="margin:8px 0 0">Exposure dial: the system would keep about <b>${num(m.exposure * 100, 0)}%</b> invested in these conditions
        (healthy 90–100%, mixed ~50%, defensive 20–30%). Risk-appetite votes: ${esc(m.regime_detail.appetite_votes)}.</p></div>
      <div class="kpis">
        <div class="kpi"><div class="label">Above 200-day average</div><div class="value">${b.pct_above_200d == null ? "—" : num(b.pct_above_200d * 100, 0) + "%"}</div><div class="note">of ${num(b.stocks)} stocks (long-term health)</div></div>
        <div class="kpi"><div class="label">Above 50-day average</div><div class="value">${b.pct_above_50d == null ? "—" : num(b.pct_above_50d * 100, 0) + "%"}</div><div class="note">shorter-term health</div></div>
        <div class="kpi"><div class="label">Up / down today</div><div class="value">${num(b.advancers)} / ${num(b.decliners)}</div><div class="note">median stock ${p(b.median_ret_1d)}</div></div>
        <div class="kpi"><div class="label">Near 52-week high / low</div><div class="value">${num(b.near_52w_high)} / ${num(b.near_52w_low)}</div><div class="note">within 1%</div></div>
      </div>
      <div class="card"><h2>Breadth and S&amp;P 500 (last year)</h2>${lines(d.history, d.spy)}</div>
      <div class="card"><h2>Risk signals (last month)</h2><p class="small muted">Spreads between assets show whether investors are taking risk or hiding.</p>${table(["Signal", "#Change"], sigInfo)}</div>
      <div class="card"><h2>Sectors</h2>${table(gHead, gRows(m.groups.sector || []))}
        <details><summary>Inside each sector (median stock)</summary>${table(["Sector", "#Stocks", "#Month", "#3 months", "#Above 50-day", "#Avg RS"], sec)}</details></div>
      <div class="card"><h2>Themes</h2>${table(gHead, gRows(m.groups.theme || []))}</div>
      <div class="grid">
        <div class="card"><h2>Style</h2>${table(gHead.slice(0, 4), (m.groups.style || []).concat(m.groups.index || []).map((r) => `<tr><td><b>${esc(r.symbol)}</b> <span class="small muted">${esc(r.name)}</span></td><td class="num">${p(r.ret_1d)}</td><td class="num">${p(r.ret_5d)}</td><td class="num">${p(r.ret_20d)}</td></tr>`))}</div>
        <div class="card"><h2>Bonds, commodities, currency, world</h2>${table(gHead.slice(0, 4), [...(m.groups.rates_credit || []), ...(m.groups.commodity_fx || []), ...(m.groups.global || [])].map((r) => `<tr><td><b>${esc(r.symbol)}</b> <span class="small muted">${esc(r.name)}</span></td><td class="num">${p(r.ret_1d)}</td><td class="num">${p(r.ret_5d)}</td><td class="num">${p(r.ret_20d)}</td></tr>`))}</div>
      </div>
      <div class="card" style="margin-top:16px"><h2>Economy</h2><p class="small muted">From FRED. "Before" = a month earlier for daily data, the previous release otherwise.</p>${table(["Measure", "#Latest", "#Before", "#Year ago"], macro)}</div>
      <div class="card"><h2>Leaders</h2><p class="small muted">Strongest liquid stocks in uptrends, within 5% of their 52-week high.</p>${table(sHead, stockRows(m.leaders || []), "No stocks meet the leader rules today.")}</div>
      <div class="grid"><div class="card"><h2>Biggest gainers today</h2>${table(sHead, stockRows(m.top_gainers || []))}</div>
        <div class="card"><h2>Biggest losers today</h2>${table(sHead, stockRows(m.top_losers || []))}</div></div>`;
  },

  async journal(param) {
    const d = await api("/api/journal" + (param ? `?day=${encodeURIComponent(param)}` : ""));
    const sc = d.score || {};
    const preds = d.predictions.map((p) => `<tr><td class="small">${esc(p.made_on)}</td><td>${esc(p.statement)}<div class="small muted">${esc(p.reasoning || "")}</div></td>
      <td class="num">${num(p.probability * 100, 0)}%</td><td class="num">${p.horizon_days}d</td>
      <td>${badge(p.status, { right: "good", wrong: "bad", open: "info", void: "mute" }[p.status])}</td>
      <td class="num ${cls(p.outcome)}">${p.outcome == null ? "" : pct(p.outcome * 100, 1)}</td></tr>`);
    const days = d.days.map((x) => `<a class="btn" href="#journal/${x.date}">${esc(String(x.date).slice(5))}</a>`).join(" ");
    return `<h1>Journal</h1><p class="sub">Opus's daily market analysis (written at 9 pm ET) and every prediction it made, scored automatically.</p>
      <div class="kpis"><div class="kpi"><div class="label">Predictions scored</div><div class="value">${num(sc.n)}</div><div class="note">${d.predictions.filter((p) => p.status === "open").length} still open</div></div>
        <div class="kpi"><div class="label">Hit rate</div><div class="value">${sc.n ? num(sc.hit * 100, 0) + "%" : "—"}</div><div class="note">vs stated confidence ${sc.n ? num(sc.conf * 100, 0) + "%" : "—"}</div></div></div>
      <div class="card"><div class="row">${days || '<span class="muted">No analyses yet.</span>'}</div></div>
      <div class="card md">${d.analysis ? md(d.analysis) : '<p class="muted">Nothing for this day.</p>'}</div>
      <div class="card"><h2>Predictions</h2>${table(["Made", "Prediction", "#Prob.", "#Horizon", "Status", "#Outcome"], preds, "No predictions yet.")}</div>`;
  },

  async trading() {
    const d = await api("/api/trading");
    const dry = d.mode === "dry_run";
    const plans = d.plans.map((p) => `<tr><td class="small">${esc(p.trade_date)}</td><td>${badge(p.side, p.side === "buy" ? "info" : "warn")}</td>
      <td><b>${esc(p.symbol)}</b><div class="small muted">${esc(p.strategy)}</div></td><td class="num">${num(p.shares)}</td>
      <td class="num">${p.limit_price ? money(p.limit_price) : "market"}</td><td class="num">${p.stop ? money(p.stop) : ""}</td>
      <td class="num">${money(p.position_value, 0)}<div class="small muted">risk ${money(p.risk_dollars, 0)}</div></td>
      <td>${badge(p.status, { simulated: "good", filled: "good", planned: "mute", waiting_approval: "warn", expired: "mute", rejected: "bad", error: "bad", submitted: "info" }[p.status] || "mute")}
        <div class="small muted">${esc(p.error || "")}</div></td></tr>`);
    const book = d.book.map((b) => { const r = b.last ? b.last / b.entry_price - 1 : 0, spy = b.spy_entry && b.spy_last ? b.spy_last / b.spy_entry - 1 : null;
      return `<tr><td><b>${esc(b.symbol)}</b><div class="small muted">${esc(b.strategy)}</div></td><td class="small">${esc(b.entry_date)}</td>
      <td class="num">${num(b.shares)}</td><td class="num">${money(b.entry_price)}</td><td class="num">${money(b.last)}</td>
      <td class="num ${cls(r)}">${pct(r * 100, 1)}<div class="small muted">SPY ${spy == null ? "—" : pct(spy * 100, 1)}</div></td>
      <td class="num">${money(b.stop)}${b.trail_pct ? `<div class="small muted">trails ${num(b.trail_pct * 100, 0)}%</div>` : ""}</td></tr>`; });
    const closed = d.closed.map((c) => `<tr><td><b>${esc(c.symbol)}</b><div class="small muted">${esc(c.strategy)}</div></td>
      <td class="small">${esc(c.entry_date)} → ${esc(c.exit_date)}</td><td class="num ${cls(c.pnl)}">${money(c.pnl, 0)}</td>
      <td class="num ${cls(c.exit_price / c.entry_price - 1)}">${pct((c.exit_price / c.entry_price - 1) * 100, 1)}</td><td class="small">${esc(c.exit_reason)}</td></tr>`);
    const stats = d.stats.map((s) => `<tr><td>${esc(s.strategy)}</td><td class="num">${num(s.n)}</td><td class="num">${num(s.win * 100, 0)}%</td>
      <td class="num ${cls(s.avg_ret)}">${pct(s.avg_ret * 100, 2)}</td><td class="num ${cls(s.pnl)}">${money(s.pnl, 0)}</td></tr>`);
    const cands = d.candidates.map((c) => `<tr><td>${esc(c.strategy)}</td><td><b>${esc(c.symbol)}</b></td><td class="num">${money(c.close)}</td>
      <td class="num">${money(c.stop)}</td><td class="num">${num(c.score, 2)}</td></tr>`);
    const unreal = d.book.reduce((s, b) => s + ((b.last || b.entry_price) - b.entry_price) * b.shares, 0);
    const realized = d.closed.reduce((s, c) => s + (c.pnl || 0), 0);
    return `<h1>Trading</h1><p class="sub">${dry ? "<b>Dry run</b>: plans are simulated against real prices each evening (a forward test; no orders sent)."
        : "<b>Paper trading</b> on the Alpaca practice account."} All strategies are experimental, so each trade risks 0.5% of the account.</p>
      <div class="kpis"><div class="kpi"><div class="label">Open positions</div><div class="value">${d.book.length}</div><div class="note">unrealized ${money(unreal, 0)}</div></div>
        <div class="kpi"><div class="label">Closed trades</div><div class="value">${d.closed.length}</div><div class="note">realized ${money(realized, 0)}</div></div></div>
      <div class="card"><h2>Plans</h2>${table(["Session", "Side", "Stock", "#Shares", "#Limit", "#Stop", "#Value", "Status"], plans, "No plans yet: the first are made after Monday's close.")}</div>
      <div class="card"><h2>Open positions</h2>${table(["Stock", "Since", "#Shares", "#Entry", "#Last", "#Return", "#Stop"], book, "None yet.")}</div>
      <div class="card"><h2>By strategy (closed trades)</h2>${table(["Strategy", "#Trades", "#Win rate", "#Avg return", "#P&L"], stats, "No closed trades yet.")}</div>
      <div class="card"><h2>Closed trades</h2>${table(["Stock", "Held", "#P&L", "#Return", "Exit"], closed, "None yet.")}</div>
      <div class="card"><details><summary>Candidates on ${esc(d.candidates_date || "—")}</summary>${table(["Strategy", "Stock", "#Close", "#Stop", "#Score"], cands)}</details></div>`;
  },

  async live() {
    const d = await api("/api/live");
    const hb = d.heartbeat;
    const paused = Object.fromEntries(d.pauses.map((p) => [p.resource, p]));
    const running = d.running.map((t) => `<tr><td>#${t.id}</td><td><b>${esc(t.type)}</b><div class="small muted">${progressText(t.progress)}</div></td>
      <td class="num">${dur(t.started_at)}</td><td class="num">${t.attempts}/${t.max_attempts}</td></tr>`);
    // group the waiting queue by type so a flood of small jobs stays readable
    const groups = {};
    for (const t of d.waiting) { (groups[t.type] ||= []).push(t); }
    const waiting = Object.entries(groups).map(([type, ts]) => {
      const first = ts[0], deferred = ts.filter((t) => t.status === "deferred").length, errored = ts.find((t) => t.last_error);
      return `<tr><td><b>${esc(type)}</b>${errored ? `<div class="small down">${esc(errored.last_error.slice(0, 140))}</div>` : ""}</td>
        <td class="num">${num(d.waiting_totals[type] ?? ts.length)}</td><td>${deferred ? badge(`${deferred} deferred`, "warn") : badge("pending", "mute")}</td>
        <td class="num small">${new Date(first.next_try_at) > new Date() ? ago(first.next_try_at) : "now"}</td>
        <td>${errored ? `<button onclick="act('/api/tasks/${errored.id}/retry')">Retry #${errored.id}</button>` : ""}</td></tr>`;
    });
    const sched = d.schedules.map((s) => `<tr><td><b>${esc(s.name)}</b><div class="small muted mono">${esc(s.cron)} ET → ${esc(s.task_type)}</div></td>
      <td class="small">${s.next_run ? `${when(s.next_run)}<div class="muted">${ago(s.next_run)}</div>` : "—"}</td>
      <td class="small">${s.last ? `${statusBadge(s.last.status)} ${when(s.last.finished_at)}<div class="muted">${esc((s.last.summary || s.last.last_error || "").slice(0, 90))}</div>` : `<span class="muted">not run yet</span>`}</td>
      <td><button onclick="act('/api/schedules/${encodeURIComponent(s.name)}/run')">Run now</button></td></tr>`);
    const res = d.resources.map((r) => `<tr><td><b>${esc(r)}</b></td>
      <td>${paused[r] ? badge(`paused until ${when(paused[r].paused_until)}`, "warn") + `<div class="small muted">${esc(paused[r].reason || "")}</div>` : badge("active", "good")}</td>
      <td class="row">${paused[r] ? `<button onclick="act('/api/resources/${encodeURIComponent(r)}/resume')">Resume</button>`
        : `<button onclick="act('/api/resources/${encodeURIComponent(r)}/pause',{minutes:60})">Pause 1 h</button>`}</td></tr>`);
    return `
      <h1>Live</h1><p class="sub">What the background service is doing right now. Refreshes every 10 seconds.</p>
      <div class="kpis">
        <div class="kpi"><div class="label">Service</div><div class="value ${hb.ok ? "up" : "down"}">${hb.ok ? "Running" : "Down"}</div><div class="note">heartbeat ${ago(hb.ts)}</div></div>
        <div class="kpi"><div class="label">Workers busy</div><div class="value">${d.running.length} / ${hb.info?.threads ?? "?"}</div><div class="note">${hb.info?.alive ?? "?"} alive</div></div>
        <div class="kpi"><div class="label">Waiting</div><div class="value">${num(Object.values(d.waiting_totals).reduce((a, b) => a + b, 0))}</div><div class="note">tasks in the queue</div></div>
        <div class="kpi"><div class="label">Scheduler</div><div class="value ${(hb.info?.scheduler_age_s ?? 999) < 300 ? "up" : "down"}">${(hb.info?.scheduler_age_s ?? 999) < 300 ? "OK" : "Stuck"}</div><div class="note">last pass ${hb.info?.scheduler_age_s ?? "?"}s ago</div></div>
      </div>
      <div class="card"><h2>Running now</h2>${table(["#", "Job and progress", "#Time", "#Try"], running, "Nothing running.")}</div>
      <div class="card"><h2>Queue</h2>${table(["Job", "#Count", "State", "#Next try", ""], waiting, "The queue is empty.")}</div>
      <div class="card"><h2>Schedule</h2>${table(["Job", "Next run", "Last run", ""], sched)}</div>
      <div class="card"><h2>Data sources and AI</h2><p class="small muted">Pausing a source makes its jobs wait (nothing is lost). Usage limits pause sources automatically.</p>${table(["Source", "State", ""], res)}</div>`;
  },

  async today(param) {
    const d = await api("/api/today" + (param ? `?day=${encodeURIComponent(param)}` : ""));
    const day = new Date(d.date + "T12:00:00");
    const shift = (n) => { const x = new Date(day); x.setDate(x.getDate() + n); return x.toISOString().slice(0, 10); };
    // a finished job's own log line repeats its summary; keep only the grouped job row for those
    const summaries = new Set(d.tasks.map((t) => `${t.type}|${t.summary}`));
    const items = [
      ...d.events.filter((e) => !summaries.has(`${e.kind}|${e.message}`))
        .map((e) => ({ ts: e.ts, kind: e.kind, level: e.level, text: e.message })),
      ...d.tasks.map((t) => ({ ts: t.last, kind: t.type, level: t.failed ? "error" : "info",
        text: t.summary ? (t.n > 1 ? `${num(t.n)} runs${t.failed ? `, ${t.failed} failed` : ""}. Latest: ` : "") + t.summary
                        : `${num(t.n)} run${t.n > 1 ? "s" : ""}${t.failed ? `, ${t.failed} failed` : ", all done"}` })),
    ].sort((a, b) => new Date(b.ts) - new Date(a.ts));
    const li = items.map((i) => `<li><div class="t">${new Date(i.ts).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</div>
      <div><div class="${i.level === "error" ? "down" : ""}">${esc(i.text)}</div><div class="k">${esc(i.kind)}</div></div></li>`);
    return `
      <div class="row"><h1>Today</h1><span class="spacer"></span>
        <a class="btn" href="#today/${shift(-1)}">← ${shift(-1).slice(5)}</a>
        <a class="btn" href="#today">Today</a>
        <a class="btn" href="#today/${shift(1)}">${shift(1).slice(5)} →</a></div>
      <p class="sub">${day.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" })}: everything the system did, newest first.
        News checked ${num(d.news_polls.n)} times (${num(d.news_polls.items)} new items).</p>
      <div class="card">${li.length ? `<ul class="timeline">${li.join("")}</ul>` : `<p class="muted">Nothing recorded on this day.</p>`}</div>`;
  },

  async portfolio() {
    const d = await api("/api/portfolio");
    if (d.error) return `<h1>Portfolio</h1><div class="card"><ul class="alerts"><li class="error">Couldn't reach Alpaca: ${esc(d.error)}</li></ul></div>`;
    const a = d.account, eq = +a.equity, last = +a.last_equity, chg = eq - last, chgPct = last ? (chg / last) * 100 : 0;
    const pos = d.positions.map((p) => `<tr><td><b>${esc(p.symbol)}</b></td><td class="num">${num(p.qty)}</td><td class="num">${money(p.avg_entry_price)}</td>
      <td class="num">${money(p.current_price)}</td><td class="num">${money(p.market_value, 0)}</td>
      <td class="num ${cls(+p.unrealized_pl)}">${money(p.unrealized_pl, 0)} <span class="small">(${pct(p.unrealized_plpc * 100, 1)})</span></td></tr>`);
    const ord = d.orders.map((o) => `<tr><td><b>${esc(o.symbol)}</b></td><td>${esc(o.side)}</td><td>${esc(o.type)}${o.order_class ? ` / ${esc(o.order_class)}` : ""}</td>
      <td class="num">${num(o.qty)}</td><td class="num">${o.limit_price ? money(o.limit_price) : o.stop_price ? "stop " + money(o.stop_price) : "—"}</td><td class="small">${when(o.submitted_at)}</td></tr>`);
    return `
      <h1>Portfolio</h1><p class="sub">Alpaca <b>paper</b> account ${esc(a.account_number || "")}: practice money, no real orders. Compared with SPY.</p>
      <div class="kpis">
        <div class="kpi"><div class="label">Account value</div><div class="value">${money(eq, 0)}</div><div class="note ${cls(chg)}">${chg >= 0 ? "+" : ""}${money(chg, 0)} today (${pct(chgPct)})</div></div>
        <div class="kpi"><div class="label">Cash</div><div class="value">${money(a.cash, 0)}</div><div class="note">${eq ? num((a.cash / eq) * 100, 0) : "—"}% of account</div></div>
        <div class="kpi"><div class="label">Invested</div><div class="value">${money(a.long_market_value, 0)}</div><div class="note">${d.positions.length} positions</div></div>
        <div class="kpi"><div class="label">Open orders</div><div class="value">${d.orders.length}</div><div class="note">status: ${esc(a.status)}</div></div>
      </div>
      <div class="card"><h2>Account vs SPY (3 months)</h2>${chart(d.curve, d.spy)}</div>
      <div class="card"><h2>Positions</h2>${table(["Stock", "#Shares", "#Avg cost", "#Price", "#Value", "#Gain/loss"], pos, "No positions yet. Paper trading starts after the dry run at the end of Phase 2.")}</div>
      <div class="card"><h2>Open orders</h2>${table(["Stock", "Side", "Type", "#Qty", "#Price", "Placed"], ord, "No open orders.")}</div>`;
  },

  async lab(param) {
    const d = await api("/api/lab" + (param ? `?report=${encodeURIComponent(param)}` : ""));
    const stageOf = {};
    for (const [st, names] of Object.entries(d.stages)) for (const n of names) stageOf[n] = st;
    const rows = d.runs.map((r) => {
      const m = r.metrics, g = m.gates || {};
      const gate = (k) => g[k] ? (g[k].ok ? "✅" : "❌") : "";
      return `<tr><td><b>${esc(r.strategy)}</b> <span class="small muted">v${esc(r.version || "")}</span><div class="small muted">${esc(stageOf[r.strategy] || "")} · ${esc(r.period)}</div></td>
        <td class="num">${num(m.trades)}</td><td class="num">${pct((m.win_rate ?? 0) * 100, 0)}</td>
        <td class="num ${cls(m.avg_excess)}">${pct((m.avg_excess ?? 0) * 100)}<div class="small muted">t ${num(m.t_excess, 1)}</div></td>
        <td class="num ${cls(m.excess_vs_twin)}">${pct((m.excess_vs_twin ?? 0) * 100)}<div class="small muted">t ${num(m.t_vs_twin, 1)}</div></td>
        <td class="num hide-sm">${pct((m.sleeve_return ?? 0) * 100, 0)}<div class="small muted">SPY ${pct((m.benchmark_return ?? 0) * 100, 0)}</div></td>
        <td class="small">${gate("enough_trades")}${gate("beats_spy_per_trade")}${gate("beats_random_twin")}${gate("works_most_years")}</td>
        <td>${m.passed ? badge("passed", "good") : badge("not yet", "mute")}</td></tr>`;
    });
    const reps = d.reports.map((r) => `<a class="btn" href="#lab/${encodeURIComponent(r)}">${esc(r.replace(".md", ""))}</a>`).join(" ");
    return `<h1>Idea lab</h1><p class="sub">Every strategy is tested on 2016–2022 against SPY and against a random twin
      (same number of picks, random stocks, same exits). ${num(d.total_backtests)} backtests run so far: the more we try,
      the higher the bar for "significant".</p>
      <div class="card"><h2>Latest result per strategy</h2>${table(["Strategy", "#Trades", "#Win rate", "#Excess vs SPY per trade", "#vs random twin", "#With SPY sleeve", "Gates", ""], rows, "No backtests yet.")}
        <p class="small muted">Gates: enough trades · beats SPY per trade (multiple-testing bar) · beats the random twin · works in most years.</p></div>
      <div class="card md"><div class="row">${reps}</div>${d.report ? md(d.report) : ""}</div>`;
  },

  async data() {
    const d = await api("/api/data");
    const u = d.universe, r = d.rows;
    const total = d.tiers.reduce((s, t) => s + t.n, 0) || 1;
    const tierInfo = { liquid: "≥ $5M traded per day: automatic trading", thin: "$1–5M per day: automatic, smaller size", emerging: "< $1M per day or price < $5: manual approval only" };
    const tiers = d.tiers.map((t) => `<tr><td><b>${esc(t.tier)}</b><div class="small muted">${esc(tierInfo[t.tier] || "")}</div></td><td class="num">${num(t.n)}</td>
      <td style="width:40%"><div class="bar"><span style="width:${(t.n / total) * 100}%"></span></div></td></tr>`);
    const maxS = Math.max(...d.sectors.map((s) => s.n), 1);
    const sectors = d.sectors.map((s) => `<tr><td>${esc(s.sector)}</td><td class="num">${num(s.n)}</td><td style="width:40%"><div class="bar"><span style="width:${(s.n / maxS) * 100}%"></span></div></td></tr>`);
    const since = (v) => v ? new Date(v).toLocaleDateString([], { year: "numeric", month: "short" }) : "—";
    return `
      <h1>Data</h1><p class="sub">What the system knows. All of it lives in the local database (${num(d.db_gb, 1)} GB).</p>
      <div class="kpis">
        <div class="kpi"><div class="label">Stocks covered</div><div class="value">${num(u.stocks)}</div><div class="note">+ ${num(u.etfs)} reference ETFs · ${num(u.delisted)} delisted kept</div></div>
        <div class="kpi"><div class="label">Daily price bars</div><div class="value">${num(r.daily_prices / 1e6, 1)}M</div><div class="note">since ${since(d.since.p0)}</div></div>
        <div class="kpi"><div class="label">News articles</div><div class="value">${num(r.news / 1e3, 0)}k</div><div class="note">since ${since(d.since.n0)}</div></div>
        <div class="kpi"><div class="label">SEC filings</div><div class="value">${num(r.filings / 1e6, 2)}M</div><div class="note">${num(r.financials / 1e6, 1)}M financial numbers</div></div>
        <div class="kpi"><div class="label">Insider trades</div><div class="value">${num(r.insider_trades / 1e6, 2)}M</div><div class="note">since ${since(d.since.i0)}</div></div>
        <div class="kpi"><div class="label">Daily features</div><div class="value">${num(r.features_daily / 1e6, 2)}M</div><div class="note">30+ numbers per stock per day</div></div>
        <div class="kpi"><div class="label">Sector known</div><div class="value">${num(u.with_sector)}</div><div class="note">of ${num(u.stocks + u.etfs)} (fills in as SEC data loads)</div></div>
      </div>
      <div class="grid">
        <div class="card"><h2>Liquidity tiers</h2><p class="small muted">How easily each stock trades decides how (and whether) the system can trade it.</p>${table(["Tier", "#Stocks", ""], tiers)}</div>
        <div class="card"><h2>Sectors</h2>${table(["Sector", "#Stocks", ""], sectors)}</div>
      </div>
      <p class="small muted">Row counts are fast estimates from the database's statistics.</p>`;
  },

  async health() {
    const d = await api("/api/health");
    const fr = d.freshness.map((f) => `<tr><td><b>${esc(f.name)}</b><div class="small muted">${esc(f.note)}</div></td>
      <td>${f.ok ? badge("up to date", "good") : badge("behind", "bad")}</td>
      <td class="small">${f.latest ? (String(f.latest).length > 10 ? when(f.latest) : esc(f.latest)) : "none"}</td><td class="small muted">${esc(f.expected)}</td></tr>`);
    const failed = d.failed.map((t) => `<tr><td>#${t.id}</td><td><b>${esc(t.type)}</b><div class="small down">${esc((t.last_error || "").slice(0, 200))}</div></td>
      <td class="small">${when(t.finished_at)}</td><td><button onclick="act('/api/tasks/${t.id}/retry')">Retry</button></td></tr>`);
    const deferred = d.deferred.map((t) => `<tr><td>#${t.id}</td><td><b>${esc(t.type)}</b><div class="small muted">${esc((t.last_error || "").slice(0, 160))}</div></td>
      <td class="num">${t.attempts}/${t.max_attempts}</td><td class="small">${ago(t.next_try_at)}</td><td><button onclick="act('/api/tasks/${t.id}/retry')">Retry now</button></td></tr>`);
    const errs = d.errors.map((e) => `<tr><td class="small">${when(e.ts)}</td><td><b>${esc(e.task_type || "")}</b> ${e.task_id ? `#${e.task_id}` : ""}
      <div class="small down">${esc(e.error_type)}: ${esc((e.message || "").slice(0, 200))}</div></td></tr>`);
    const lastOk = d.last_ok.map((t) => `<tr><td>${esc(t.type)}</td><td class="small">${when(t.finished_at)}</td><td class="small muted">${esc((t.summary || "").slice(0, 110))}</td></tr>`);
    return `
      <h1>Health</h1><p class="sub">Problems show up here first. Failed and waiting jobs can be retried.</p>
      <div class="kpis">
        <div class="kpi"><div class="label">Service</div><div class="value ${d.heartbeat.ok ? "up" : "down"}">${d.heartbeat.ok ? "Running" : "Down"}</div><div class="note">heartbeat ${ago(d.heartbeat.ts)}</div></div>
        <div class="kpi"><div class="label">Failed (14 days)</div><div class="value ${d.failed.length ? "down" : "up"}">${d.failed.length}</div><div class="note">gave up after retries</div></div>
        <div class="kpi"><div class="label">Retrying</div><div class="value">${d.deferred.length}</div><div class="note">waiting to try again</div></div>
        <div class="kpi"><div class="label">Disk free</div><div class="value">${num(d.disk.free_gb, 0)} GB</div><div class="note">database ${num(d.db_gb, 1)} GB</div></div>
      </div>
      <div class="card"><h2>Data freshness</h2>${table(["Dataset", "Status", "Newest", "Expected"], fr)}</div>
      <div class="card"><h2>Failed jobs</h2>${table(["#", "Job and error", "When", ""], failed, "No failures in the last 14 days.")}</div>
      <div class="card"><h2>Retrying</h2>${table(["#", "Job and last error", "#Tries", "Next try", ""], deferred, "Nothing is waiting to retry.")}</div>
      <div class="card"><h2>Recent errors</h2>${table(["When", "Where"], errs, "No errors logged.")}</div>
      <div class="card"><details><summary>Last success of every job type</summary>${table(["Job", "When", "Result"], lastOk)}</details></div>`;
  },
};

// Account vs SPY, both rebased to 100 at the start, as a small inline SVG.
function chart(curve, spy) {
  if (!curve || curve.length < 2) return `<p class="muted">Not enough history yet.</p>`;
  const spyBy = Object.fromEntries((spy || []).map((s) => [s.date, +s.close]));
  const pts = curve.map((c) => ({ date: c.date, a: +c.equity, s: spyBy[c.date] })).filter((p) => p.a);
  const a0 = pts[0].a, s0 = pts.find((p) => p.s)?.s;
  const A = pts.map((p) => (p.a / a0) * 100), S = pts.map((p) => (p.s && s0 ? (p.s / s0) * 100 : null));
  const vals = [...A, ...S.filter((v) => v != null)], lo = Math.min(...vals) - 0.5, hi = Math.max(...vals) + 0.5;
  const W = 600, H = 200, x = (i) => (i / (pts.length - 1)) * (W - 40) + 30, y = (v) => H - 20 - ((v - lo) / (hi - lo)) * (H - 30);
  const path = (arr) => arr.map((v, i) => (v == null ? "" : `${i && arr[i - 1] != null ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`)).join("");
  const fin = (arr) => arr.filter((v) => v != null).slice(-1)[0];
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Account vs SPY">
      <line x1="30" x2="${W - 10}" y1="${y(100)}" y2="${y(100)}" stroke="#e4e7ec" stroke-dasharray="4 4"/>
      <path d="${path(S)}" fill="none" stroke="#9aa4b2" stroke-width="2"/>
      <path d="${path(A)}" fill="none" stroke="#1f6feb" stroke-width="2.5"/>
    </svg>
    <div class="row small"><span><b style="color:#1f6feb">━ Account</b> ${pct(fin(A) - 100)}</span><span><b style="color:#9aa4b2">━ SPY</b> ${pct(fin(S) - 100)}</span>
      <span class="muted">${esc(pts[0].date)} → ${esc(pts[pts.length - 1].date)}</span></div>`;
}

// Breadth (% above 200-day, % above 50-day) with SPY on its own scale, as one small SVG.
function lines(hist, spy) {
  if (!hist || hist.length < 2) return `<p class="muted">Not enough history yet.</p>`;
  const W = 600, H = 200, n = hist.length, x = (i) => (i / (n - 1)) * (W - 40) + 30;
  const y = (v) => H - 20 - v * (H - 30);
  const pth = (key) => hist.map((h, i) => (h[key] == null ? "" : `${i && hist[i - 1][key] != null ? "L" : "M"}${x(i).toFixed(1)},${y(h[key]).toFixed(1)}`)).join("");
  const spyBy = Object.fromEntries(spy.map((s) => [s.date, +s.c]));
  const sv = hist.map((h) => spyBy[h.date] ?? null), lo = Math.min(...sv.filter((v) => v)), hi = Math.max(...sv.filter((v) => v));
  const ys = (v) => H - 20 - ((v - lo) / (hi - lo || 1)) * (H - 30);
  const sp = sv.map((v, i) => (v == null ? "" : `${i && sv[i - 1] != null ? "L" : "M"}${x(i).toFixed(1)},${ys(v).toFixed(1)}`)).join("");
  const grid = [0.25, 0.5, 0.75].map((g) => `<line x1="30" x2="${W - 10}" y1="${y(g)}" y2="${y(g)}" stroke="#e4e7ec" stroke-dasharray="3 4"/><text x="0" y="${y(g) + 4}" font-size="11" fill="#7a8494">${g * 100}%</text>`).join("");
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Market breadth">${grid}
      <path d="${sp}" fill="none" stroke="#c3cad5" stroke-width="2"/>
      <path d="${pth("a50")}" fill="none" stroke="#9a6700" stroke-width="1.5"/>
      <path d="${pth("a200")}" fill="none" stroke="#1f6feb" stroke-width="2.5"/></svg>
    <div class="row small"><span><b style="color:#1f6feb">━ % above 200-day</b></span><span><b style="color:#9a6700">━ % above 50-day</b></span>
      <span><b style="color:#c3cad5">━ S&amp;P 500</b> (own scale)</span><span class="muted">${esc(hist[0].date)} → ${esc(hist[n - 1].date)}</span></div>`;
}

// ── Router + refresh loop ─────────────────────────────────────────────────────────────────────────────────
const REFRESH = { review: 30, journal: 300, trading: 60, market: 120, lab: 300, live: 10, today: 20, portfolio: 60, data: 120, health: 20 };
let timer = null, busy = false;

function route() {
  const [name, param] = (location.hash.slice(1) || "review").split("/");
  return { name: views[name] ? name : "review", param };
}
async function refresh() {
  if (busy) return; busy = true;
  const { name, param } = route();
  document.querySelectorAll("#tabs a").forEach((a) => a.classList.toggle("on", a.getAttribute("href") === `#${name}`));
  try {
    const html = await views[name](param);
    const y = window.scrollY, open = [...document.querySelectorAll("details[open]")].length;
    $("#page").innerHTML = html;
    if (open) document.querySelectorAll("details").forEach((d) => (d.open = true));
    window.scrollTo(0, y);
  } catch (e) {
    $("#page").innerHTML = `<div class="card"><ul class="alerts"><li class="error">Couldn't load this page: ${esc(e.message)}</li></ul></div>`;
  } finally { busy = false; }
  clearTimeout(timer); timer = setTimeout(refresh, (REFRESH[name] || 30) * 1000);
}
async function pulse() {
  try {
    const o = await api("/api/overview");
    const p = $("#pulse"), hb = o.heartbeat, alerts = o.attention.filter((a) => a.level !== "info").length;
    p.className = "pulse " + (hb.ok && !alerts ? "ok" : "bad");
    p.textContent = !hb.ok ? "Service down" : alerts ? `${alerts} issue${alerts > 1 ? "s" : ""}` : `Running · ${o.running.length} busy`;
  } catch { $("#pulse").className = "pulse bad"; $("#pulse").textContent = "Offline"; }
}
window.addEventListener("hashchange", () => { window.scrollTo(0, 0); refresh(); });
refresh(); pulse(); setInterval(pulse, 15000);
