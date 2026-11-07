// Price data loader. Uses Yahoo Finance's public chart endpoint (no API key).
// A .stock file can also carry its own "bars" array (e.g. written by Claude from
// Robinhood data); in that case no network request is made.

'use strict';

// For daily charts we load extra history so 50/200-day averages are correct
// on the first visible bar. The visible window is set by the chart itself.
const FETCH_RANGE_DAILY = {
  '1mo': '2y', '3mo': '2y', '6mo': '2y', 'ytd': '2y', '1y': '2y',
  '2y': '5y', '5y': '10y', '10y': 'max', 'max': 'max'
};
const INTERVALS = { '1d': '1d', '1wk': '1wk', '1w': '1wk', '1mo': '1mo' };

const cache = new Map();
const TTL_MS = 55 * 1000;

function toYahooSymbol(symbol) {
  return String(symbol).trim().toUpperCase().replace(/\./g, '-');
}

// ------------------------------------------------------------------ Alpaca
// Free "Basic" plan: full-market (SIP) history is allowed as long as the
// request ends more than 15 minutes ago. Keys come from the workspace .env.

const ALPACA_TIMEFRAME = { '1d': '1Day', '1wk': '1Week', '1w': '1Week', '1mo': '1Month' };
const YEARS_BACK = { '2y': 2, '5y': 5, '10y': 10, 'max': 11 };
const assetCache = new Map();

async function alpacaGet(url, creds) {
  const res = await fetch(url, {
    headers: { 'APCA-API-KEY-ID': creds.key, 'APCA-API-SECRET-KEY': creds.secret, 'Accept': 'application/json' }
  });
  const text = await res.text();
  let json;
  try { json = JSON.parse(text); } catch { json = null; }
  if (!res.ok) throw new Error(`Alpaca HTTP ${res.status}: ${(json && json.message) || text.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 80)}`);
  return json;
}

async function alpacaAsset(symbol, creds) {
  if (assetCache.has(symbol)) return assetCache.get(symbol);
  let a = null;
  try { a = await alpacaGet(`https://paper-api.alpaca.markets/v2/assets/${encodeURIComponent(symbol)}`, creds); } catch { /* name is optional */ }
  assetCache.set(symbol, a);
  return a;
}

async function fetchBarsAlpaca(symbol, range, interval, creds) {
  const sym = String(symbol).trim().toUpperCase();
  const tf = ALPACA_TIMEFRAME[interval] || '1Day';
  const yrange = tf === '1Day' ? (FETCH_RANGE_DAILY[range] || '2y') : '10y';
  const start = new Date();
  start.setUTCFullYear(start.getUTCFullYear() - (YEARS_BACK[yrange] || 2));
  const end = new Date(Date.now() - 16 * 60 * 1000);

  const bars = [];
  let token = null;
  for (let page = 0; page < 20; page++) {
    const qs = new URLSearchParams({
      timeframe: tf, start: start.toISOString().slice(0, 10), end: end.toISOString(),
      feed: 'sip', adjustment: 'split', limit: '10000'
    });
    if (token) qs.set('page_token', token);
    const j = await alpacaGet(`https://data.alpaca.markets/v2/stocks/${encodeURIComponent(sym)}/bars?${qs}`, creds);
    for (const b of j.bars || []) {
      bars.push({ t: b.t.slice(0, 10), o: round(b.o), h: round(b.h), l: round(b.l), c: round(b.c), v: b.v || 0 });
    }
    token = j.next_page_token;
    if (!token) break;
  }
  if (!bars.length) throw new Error(`Alpaca returned no bars for ${sym}`);

  const asset = await alpacaAsset(sym, creds);
  return {
    bars,
    meta: {
      name: asset && asset.name ? asset.name.replace(/\s+(Common Stock|Class [A-Z] Common Stock|Ordinary Shares)$/i, '') : sym,
      exchange: asset && asset.exchange ? asset.exchange : '',
      currency: 'USD',
      price: bars[bars.length - 1].c,
      marketTime: end.toISOString(),
      source: 'Alpaca (full market, ≥15 min delayed)'
    },
    fetchKey: `alpaca|${sym}|${yrange}|${tf}`
  };
}

// ---------------------------------------------------------------- dispatcher

/**
 * Loads bars from Alpaca when keys are available (and the spec doesn't force
 * "source": "yahoo"); otherwise, or if Alpaca fails, from Yahoo Finance.
 */
async function fetchBars(symbol, range, interval, { force = false, alpaca = null, prefer = null } = {}) {
  if (alpaca && alpaca.key && alpaca.secret && prefer !== 'yahoo') {
    const key = `A|${alpaca.key.slice(0, 6)}|${symbol}|${range}|${interval}`;
    const hit = cache.get(key);
    if (!force && hit && Date.now() - hit.t < TTL_MS) return hit.v;
    try {
      const v = await fetchBarsAlpaca(symbol, range, interval, alpaca);
      cache.set(key, { t: Date.now(), v });
      return v;
    } catch (e) {
      const v = await fetchBarsYahoo(symbol, range, interval, { force });
      return Object.assign({}, v, { meta: Object.assign({}, v.meta, { source: `Yahoo Finance (Alpaca failed: ${e.message})` }) });
    }
  }
  return fetchBarsYahoo(symbol, range, interval, { force });
}

// ------------------------------------------------------------------ Yahoo

async function fetchBarsYahoo(symbol, range, interval, { force = false } = {}) {
  const ysym = toYahooSymbol(symbol);
  const yint = INTERVALS[interval] || '1d';
  const yrange = yint === '1d' ? (FETCH_RANGE_DAILY[range] || '2y') : (range === 'max' ? 'max' : '10y');
  const key = `${ysym}|${yrange}|${yint}`;
  const hit = cache.get(key);
  if (!force && hit && Date.now() - hit.t < TTL_MS) return hit.v;

  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ysym)}` +
    `?range=${yrange}&interval=${yint}&includePrePost=false&events=div%2Csplit`;
  const res = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0 (Macintosh) StockView/0.1' } });
  if (!res.ok) throw new Error(`Price data request failed (HTTP ${res.status}) for ${ysym}`);
  const json = await res.json();
  const r = json && json.chart && json.chart.result && json.chart.result[0];
  if (!r) {
    const desc = json && json.chart && json.chart.error && json.chart.error.description;
    throw new Error(desc || `No price data found for ${ysym}`);
  }
  const q = (r.indicators && r.indicators.quote && r.indicators.quote[0]) || {};
  const ts = r.timestamp || [];
  const off = (r.meta && r.meta.gmtoffset) || 0;
  const byDate = new Map();
  for (let i = 0; i < ts.length; i++) {
    const o = q.open && q.open[i], h = q.high && q.high[i], l = q.low && q.low[i], c = q.close && q.close[i];
    if (o == null || h == null || l == null || c == null) continue;
    const t = new Date((ts[i] + off) * 1000).toISOString().slice(0, 10);
    byDate.set(t, { t, o: round(o), h: round(h), l: round(l), c: round(c), v: (q.volume && q.volume[i]) || 0 });
  }
  const bars = [...byDate.values()].sort((a, b) => (a.t < b.t ? -1 : 1));
  const m = r.meta || {};
  const value = {
    bars,
    meta: {
      name: m.longName || m.shortName || ysym,
      exchange: m.fullExchangeName || m.exchangeName || '',
      currency: m.currency || 'USD',
      price: m.regularMarketPrice,
      high52: m.fiftyTwoWeekHigh,
      low52: m.fiftyTwoWeekLow,
      marketTime: m.regularMarketTime ? new Date(m.regularMarketTime * 1000).toISOString() : null,
      source: 'Yahoo Finance'
    },
    fetchKey: key
  };
  cache.set(key, { t: Date.now(), v: value });
  return value;
}

function round(x) {
  return Math.round(x * 10000) / 10000;
}

/** Minimal .env reader: KEY=VALUE lines, optional quotes, # comments. */
function readEnvFile(file) {
  const out = {};
  let text;
  try { text = require('fs').readFileSync(file, 'utf8'); } catch { return out; }
  for (const line of text.split(/\r?\n/)) {
    const m = line.match(/^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
    if (!m || line.trim().startsWith('#')) continue;
    out[m[1]] = m[2].replace(/^['"]|['"]$/g, '').trim();
  }
  return out;
}

module.exports = { fetchBars, readEnvFile };
