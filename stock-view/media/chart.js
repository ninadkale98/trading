/* global LightweightCharts, acquireVsCodeApi */
(function () {
  'use strict';

  const vscode = acquireVsCodeApi();
  const LWC = LightweightCharts;

  const RANGES = [['1mo', '1M'], ['3mo', '3M'], ['6mo', '6M'], ['ytd', 'YTD'], ['1y', '1Y'], ['2y', '2Y'], ['5y', '5Y'], ['max', 'Max']];
  const SMAS = [['sma20', 20, '#f59e0b'], ['sma50', 50, '#3b82f6'], ['sma200', 200, '#a855f7']];
  const MONTHS = { '1mo': 1, '3mo': 3, '6mo': 6, '1y': 12, '2y': 24, '5y': 60, '10y': 120 };

  // ------------------------------------------------------------ DOM
  const root = document.getElementById('root');
  root.innerHTML = `
    <header class="hdr">
      <div class="ident">
        <span class="sym" id="sym">…</span>
        <span class="name" id="name"></span>
      </div>
      <div class="quote">
        <span class="last" id="last"></span>
        <span class="chg" id="chg"></span>
      </div>
      <div class="spacer"></div>
      <div class="group" id="ranges"></div>
      <div class="group" id="smas"></div>
      <button class="btn" id="selmode" title="Select mode (S). Or hold Shift and drag on the chart.">⬚ Select</button>
      <button class="btn icon" id="fit" title="Fit all data (F)">⤢</button>
      <button class="btn icon" id="refresh" title="Refresh prices">⟳</button>
    </header>
    <div class="note" id="note" hidden></div>
    <div class="error" id="error" hidden></div>
    <div class="wrap" id="wrap">
      <div class="chart" id="chart"></div>
      <div class="overlay" id="overlay"></div>
      <div class="legend" id="legend"></div>
      <div class="hint" id="hint">Shift + drag to select a range · S select mode · Esc clear · F fit</div>
      <div class="loading" id="loading" hidden>Loading…</div>
    </div>
    <section class="stats" id="stats" hidden></section>
    <footer class="foot" id="foot"></footer>`;
  const $ = id => document.getElementById(id);

  // ------------------------------------------------------------ state
  let chart, candle, volume;
  const smaSeries = {};
  let priceLines = [];
  let bars = [];
  let idx = new Map();
  let spec = null;
  let meta = null;
  let lastFetchKey = null;
  let lastRange = null;
  let sel = null;        // { i0, i1 }
  let drag = null;       // { a, b }
  let selectMode = false;
  let shiftDown = false;
  let rsi = [];
  let smaCache = {};

  // ------------------------------------------------------------ format
  const nf2 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const money = x => (x == null || !isFinite(x) ? '–' : '$' + nf2.format(x));
  const signed = (x, d = 2) => (x == null || !isFinite(x) ? '–' : (x > 0 ? '+' : x < 0 ? '−' : '') + Math.abs(x).toFixed(d));
  const pct = x => (x == null || !isFinite(x) ? '–' : signed(x * 100, 1) + '%');
  const vol = v => {
    if (v == null || !isFinite(v)) return '–';
    if (v >= 1e9) return (v / 1e9).toFixed(2) + 'B';
    if (v >= 1e6) return (v / 1e6).toFixed(1) + 'M';
    if (v >= 1e3) return (v / 1e3).toFixed(0) + 'K';
    return String(Math.round(v));
  };
  const dateLabel = t => {
    const d = new Date(t + 'T00:00:00Z');
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' });
  };
  const cls = x => (x > 0 ? 'up' : x < 0 ? 'down' : '');

  // ------------------------------------------------------------ theme
  function cssVar(n, fb) {
    const v = getComputedStyle(document.body).getPropertyValue(n).trim();
    return v || fb;
  }
  function theme() {
    const b = document.body.classList;
    const dark = b.contains('vscode-dark') || b.contains('vscode-high-contrast') ||
      (!b.contains('vscode-light') && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    return {
      dark,
      bg: cssVar('--vscode-editor-background', dark ? '#1e1e1e' : '#ffffff'),
      fg: cssVar('--vscode-editor-foreground', dark ? '#cccccc' : '#333333'),
      grid: dark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)',
      border: dark ? 'rgba(255,255,255,0.18)' : 'rgba(0,0,0,0.18)',
      up: dark ? '#26a69a' : '#089981',
      down: dark ? '#ef5350' : '#f23645',
      volUp: dark ? 'rgba(38,166,154,0.45)' : 'rgba(8,153,129,0.40)',
      volDown: dark ? 'rgba(239,83,80,0.45)' : 'rgba(242,54,69,0.40)'
    };
  }
  function applyTheme() {
    if (!chart) return;
    const c = theme();
    chart.applyOptions({
      layout: { background: { type: 'solid', color: c.bg }, textColor: c.fg },
      grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
      rightPriceScale: { borderColor: c.border },
      timeScale: { borderColor: c.border }
    });
    candle.applyOptions({ upColor: c.up, downColor: c.down, wickUpColor: c.up, wickDownColor: c.down });
    if (bars.length) volume.setData(volumeData());
  }

  // ------------------------------------------------------------ chart
  function initChart() {
    const c = theme();
    chart = LWC.createChart($('chart'), {
      autoSize: true,
      layout: { background: { type: 'solid', color: c.bg }, textColor: c.fg, fontFamily: cssVar('--vscode-font-family', 'system-ui, sans-serif'), fontSize: 11 },
      grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
      rightPriceScale: { borderColor: c.border, scaleMargins: { top: 0.06, bottom: 0.26 } },
      timeScale: { borderColor: c.border, rightOffset: 4, minBarSpacing: 0.5 },
      crosshair: { mode: LWC.CrosshairMode.Normal }
    });
    candle = chart.addCandlestickSeries({ upColor: c.up, downColor: c.down, wickUpColor: c.up, wickDownColor: c.down, borderVisible: false });
    volume = chart.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: 'vol', lastValueVisible: false, priceLineVisible: false });
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    chart.timeScale().subscribeVisibleLogicalRangeChange(() => drawOverlay());
    chart.subscribeCrosshairMove(onCrosshair);
    new ResizeObserver(() => drawOverlay()).observe($('wrap'));
    new MutationObserver(applyTheme).observe(document.body, { attributes: true, attributeFilter: ['class'] });
  }

  function volumeData() {
    const c = theme();
    return bars.map(b => ({ time: b.t, value: b.v, color: b.c >= b.o ? c.volUp : c.volDown }));
  }

  function computeSma(n) {
    const out = new Array(bars.length).fill(null);
    let sum = 0;
    for (let i = 0; i < bars.length; i++) {
      sum += bars[i].c;
      if (i >= n) sum -= bars[i - n].c;
      if (i >= n - 1) out[i] = sum / n;
    }
    return out;
  }

  function computeRsi(n = 14) {
    const out = new Array(bars.length).fill(null);
    if (bars.length <= n) return out;
    let gain = 0, loss = 0;
    for (let i = 1; i <= n; i++) {
      const d = bars[i].c - bars[i - 1].c;
      if (d >= 0) gain += d; else loss -= d;
    }
    gain /= n; loss /= n;
    out[n] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
    for (let i = n + 1; i < bars.length; i++) {
      const d = bars[i].c - bars[i - 1].c;
      gain = (gain * (n - 1) + Math.max(d, 0)) / n;
      loss = (loss * (n - 1) + Math.max(-d, 0)) / n;
      out[i] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
    }
    return out;
  }

  function idxOnOrAfter(t) {
    if (idx.has(t)) return idx.get(t);
    for (let i = 0; i < bars.length; i++) if (bars[i].t >= t) return i;
    return bars.length - 1;
  }
  function idxOnOrBefore(t) {
    if (idx.has(t)) return idx.get(t);
    for (let i = bars.length - 1; i >= 0; i--) if (bars[i].t <= t) return i;
    return 0;
  }

  function setRangeView(range) {
    if (!bars.length) return;
    const ts = chart.timeScale();
    const last = bars.length - 1;
    if (range === 'max' || (!MONTHS[range] && range !== 'ytd')) { ts.fitContent(); return; }
    const end = new Date(bars[last].t + 'T00:00:00Z');
    let from;
    if (range === 'ytd') from = `${end.getUTCFullYear()}-01-01`;
    else { end.setUTCMonth(end.getUTCMonth() - MONTHS[range]); from = end.toISOString().slice(0, 10); }
    const i0 = idxOnOrAfter(from);
    ts.setVisibleLogicalRange({ from: i0 - 0.5, to: last + 4 });
  }

  // ------------------------------------------------------------ render
  function render(m) {
    hide('error');
    hide('loading');
    const prevSpec = spec;
    spec = m.spec;
    meta = m.meta || {};
    const sameSeries = lastFetchKey === m.fetchKey && bars.length && m.bars.length && m.bars[0].t === bars[0].t;
    const keepView = sameSeries && prevSpec && prevSpec.range === spec.range;
    const view = keepView ? chart.timeScale().getVisibleLogicalRange() : null;
    const selDates = sel ? { from: bars[sel.i0].t, to: bars[sel.i1].t } : null;

    bars = m.bars;
    idx = new Map(bars.map((b, i) => [b.t, i]));
    lastFetchKey = m.fetchKey;

    candle.setData(bars.map(b => ({ time: b.t, open: b.o, high: b.h, low: b.l, close: b.c })));
    volume.setData(volumeData());

    // Moving averages
    smaCache = {};
    const on = new Set(spec.indicators || []);
    for (const [id, n, color] of SMAS) {
      smaCache[id] = computeSma(n);
      if (on.has(id)) {
        if (!smaSeries[id]) smaSeries[id] = chart.addLineSeries({ color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
        smaSeries[id].setData(bars.map((b, i) => (smaCache[id][i] == null ? { time: b.t } : { time: b.t, value: smaCache[id][i] })));
      } else if (smaSeries[id]) {
        chart.removeSeries(smaSeries[id]);
        delete smaSeries[id];
      }
    }
    rsi = computeRsi(14);

    // Markers
    const markers = (spec.markers || []).filter(mk => mk && mk.date).map(mk => {
      const i = idxOnOrAfter(mk.date);
      const pos = mk.position === 'below' ? 'belowBar' : 'aboveBar';
      return {
        time: bars[i].t,
        position: pos,
        color: mk.color || '#f59e0b',
        shape: mk.shape || (pos === 'belowBar' ? 'arrowUp' : 'arrowDown'),
        text: mk.text || ''
      };
    }).sort((a, b) => (a.time < b.time ? -1 : 1));
    candle.setMarkers(markers);

    // Horizontal price lines
    priceLines.forEach(pl => candle.removePriceLine(pl));
    priceLines = (spec.lines || []).filter(l => l && isFinite(l.price)).map(l => candle.createPriceLine({
      price: +l.price, color: l.color || '#f59e0b', lineWidth: 1, lineStyle: LWC.LineStyle.Dashed, axisLabelVisible: true, title: l.label || ''
    }));

    // View
    if (view) chart.timeScale().setVisibleLogicalRange(view);
    else setRangeView(spec.range);
    lastRange = spec.range;

    // Selection survives refreshes
    if (selDates) setSelection(idxOnOrAfter(selDates.from), idxOnOrBefore(selDates.to), false);

    renderHeader(m.file);
    showLegend(bars.length - 1);
    drawOverlay();
    setTimeout(drawOverlay, 120);
  }

  function renderHeader(file) {
    const last = bars[bars.length - 1];
    const prev = bars[bars.length - 2];
    $('sym').textContent = spec.symbol;
    $('name').textContent = meta.name && meta.name !== spec.symbol ? meta.name : '';
    if (last) {
      const ch = prev ? last.c - prev.c : 0;
      const chp = prev ? ch / prev.c : 0;
      $('last').textContent = money(last.c);
      const el = $('chg');
      el.textContent = `${signed(ch)} (${pct(chp)})`;
      el.className = 'chg ' + cls(ch);
    }
    $('ranges').innerHTML = RANGES.map(([k, label]) => `<button class="seg${spec.range === k ? ' on' : ''}" data-range="${k}">${label}</button>`).join('');
    const on = new Set(spec.indicators || []);
    $('smas').innerHTML = SMAS.map(([id, n, color]) =>
      `<button class="seg sma${on.has(id) ? ' on' : ''}" data-ind="${id}" title="${n}-day simple moving average"><i style="background:${color}"></i>${n}</button>`).join('');
    const note = $('note');
    if (spec.note) { note.textContent = spec.note; note.hidden = false; } else note.hidden = true;
    const when = meta.marketTime ? new Date(meta.marketTime).toLocaleString() : new Date().toLocaleTimeString();
    const hls = (spec.highlights || []).map((h, i) => `<span class="chip" style="--c:${h.color || '#3b82f6'}">${escapeHtml(h.label || `${h.from} → ${h.to}`)}<button data-rmhl="${i}" title="Remove highlight">×</button></span>`).join('');
    $('foot').innerHTML = `<span>${escapeHtml(file || '')} · ${escapeHtml(meta.source || '')}${meta.exchange ? ' · ' + escapeHtml(meta.exchange) : ''} · updated ${escapeHtml(when)}</span><span class="chips">${hls}</span>`;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
  }

  // ------------------------------------------------------------ legend
  function showLegend(i) {
    const b = bars[i];
    if (!b) { $('legend').innerHTML = ''; return; }
    const p = bars[i - 1];
    const ch = p ? (b.c - p.c) / p.c : null;
    const gap = p ? (b.o - p.c) / p.c : null;
    const smaTxt = SMAS.filter(([id]) => smaSeries[id]).map(([id, n, color]) =>
      `<span><i style="background:${color}"></i>SMA${n} ${smaCache[id][i] != null ? nf2.format(smaCache[id][i]) : '–'}</span>`).join('');
    $('legend').innerHTML =
      `<div><b>${dateLabel(b.t)}</b> <span class="${cls(ch)}">${pct(ch)}</span>${gap != null && Math.abs(gap) >= 0.02 ? ` <span class="tag ${cls(gap)}">gap ${pct(gap)}</span>` : ''}</div>` +
      `<div>O ${nf2.format(b.o)} H ${nf2.format(b.h)} L ${nf2.format(b.l)} C ${nf2.format(b.c)}</div>` +
      `<div>Vol ${vol(b.v)} · RSI ${rsi[i] != null ? rsi[i].toFixed(0) : '–'}</div>` +
      (smaTxt ? `<div class="smas">${smaTxt}</div>` : '');
  }

  function onCrosshair(param) {
    if (!bars.length) return;
    if (!param || param.logical == null || param.logical < 0 || param.logical >= bars.length) { showLegend(bars.length - 1); return; }
    showLegend(Math.round(param.logical));
  }

  // ------------------------------------------------------------ overlay
  // The chart lays itself out asynchronously, so coordinates are read on the
  // next animation frame (coalesced), never synchronously.
  let overlayRaf = 0;
  function drawOverlay() {
    if (overlayRaf) return;
    overlayRaf = requestAnimationFrame(() => {
      overlayRaf = 0;
      drawOverlayNow();
    });
  }

  function drawOverlayNow() {
    const ov = $('overlay');
    ov.innerHTML = '';
    if (!chart || !bars.length) return;
    const ts = chart.timeScale();
    let axisW = 0, axisH = 26;
    try { axisW = chart.priceScale('right').width(); } catch (e) { /* ignore */ }
    try { axisH = ts.height(); } catch (e) { /* ignore */ }
    const W = $('chart').clientWidth - axisW;
    const H = $('chart').clientHeight - axisH;
    ov.style.width = W + 'px';
    ov.style.height = H + 'px';

    // logicalToCoordinate() only accepts whole bar indices, so pad by half a bar.
    const xa = ts.logicalToCoordinate(0), xb = ts.logicalToCoordinate(1);
    const spacing = (xa != null && xb != null && xb - xa > 0) ? xb - xa : (ts.options().barSpacing || 6);
    const band = (i0, i1, className, color, label) => {
      const c0 = ts.logicalToCoordinate(i0), c1 = ts.logicalToCoordinate(i1);
      if (c0 == null || c1 == null) return;
      let x0 = c0 - spacing / 2;
      let x1 = c1 + spacing / 2;
      if (x1 < 0 || x0 > W) return;
      x0 = Math.max(0, x0); x1 = Math.min(W, x1);
      const d = document.createElement('div');
      d.className = 'band ' + className;
      d.style.left = x0 + 'px';
      d.style.width = Math.max(2, x1 - x0) + 'px';
      if (color) d.style.setProperty('--c', color);
      if (label) {
        const l = document.createElement('span');
        l.textContent = label;
        d.appendChild(l);
      }
      ov.appendChild(d);
    };

    (spec && spec.highlights || []).forEach(h => {
      if (!h || !h.from) return;
      band(idxOnOrAfter(h.from), idxOnOrBefore(h.to || h.from), 'hl', h.color || '#3b82f6', h.label || '');
    });
    if (sel) band(sel.i0, sel.i1, 'sel', null, '');
    if (drag) {
      const a = Math.min(drag.a, drag.b), b = Math.max(drag.a, drag.b);
      band(a, b, 'sel live', null, `${dateLabel(bars[a].t)} → ${dateLabel(bars[b].t)}`);
    }
  }

  // ------------------------------------------------------------ selection
  function idxAt(clientX) {
    const r = $('chart').getBoundingClientRect();
    const l = chart.timeScale().coordinateToLogical(clientX - r.left);
    if (l == null) return null;
    return Math.max(0, Math.min(bars.length - 1, Math.round(l)));
  }

  function lockChart(lock) {
    chart.applyOptions({ handleScroll: !lock, handleScale: !lock });
  }

  function selecting(e) {
    return selectMode || shiftDown || (e && e.shiftKey);
  }

  const wrap = $('wrap');
  const swallow = e => { if (selecting(e) && e.button === 0) { e.stopPropagation(); e.preventDefault(); } };
  wrap.addEventListener('mousedown', swallow, true);
  wrap.addEventListener('pointerdown', e => {
    if (e.button !== 0 || !bars.length || !selecting(e)) return;
    if (e.target.closest && e.target.closest('.legend')) return;
    e.stopPropagation();
    e.preventDefault();
    const i = idxAt(e.clientX);
    if (i == null) return;
    lockChart(true);
    drag = { a: i, b: i };
    drawOverlay();
  }, true);
  window.addEventListener('pointermove', e => {
    if (!drag) return;
    const i = idxAt(e.clientX);
    if (i != null && i !== drag.b) { drag.b = i; drawOverlay(); }
  });
  window.addEventListener('pointerup', () => {
    if (!drag) return;
    const a = Math.min(drag.a, drag.b), b = Math.max(drag.a, drag.b);
    drag = null;
    if (!selectMode && !shiftDown) lockChart(false);
    setSelection(a, b, true);
  });

  function setSelection(i0, i1, emit) {
    if (!bars.length) return;
    i0 = Math.max(0, Math.min(i0, bars.length - 1));
    i1 = Math.max(i0, Math.min(i1, bars.length - 1));
    sel = { i0, i1 };
    const stats = computeStats(i0, i1);
    renderStats(stats);
    drawOverlay();
    if (emit) {
      vscode.postMessage({
        type: 'selection',
        selection: {
          symbol: spec.symbol,
          interval: spec.interval,
          from: bars[i0].t,
          to: bars[i1].t,
          tradingDays: i1 - i0 + 1,
          selectedAt: new Date().toISOString(),
          stats,
          bars: bars.slice(Math.max(i0, i1 - 399), i1 + 1)
        }
      });
    }
  }

  function clearSelection(emit) {
    sel = null;
    hide('stats');
    drawOverlay();
    if (emit) vscode.postMessage({ type: 'clearSelection' });
  }

  function revealSelection() {
    if (!sel) return;
    const ts = chart.timeScale();
    const vr = ts.getVisibleLogicalRange();
    if (vr && sel.i0 >= vr.from && sel.i1 <= vr.to) return;
    const pad = Math.max(10, Math.round((sel.i1 - sel.i0) * 0.6));
    ts.setVisibleLogicalRange({ from: sel.i0 - pad, to: Math.min(bars.length + 4, sel.i1 + pad) });
  }

  function computeStats(i0, i1) {
    const s = bars.slice(i0, i1 + 1);
    const base = i0 > 0 ? bars[i0 - 1].c : s[0].o;
    const baseLabel = i0 > 0 ? 'prior close' : 'open';
    const lastClose = s[s.length - 1].c;

    let high = { price: -Infinity, date: null }, low = { price: Infinity, date: null };
    let peak = base, peakDate = i0 > 0 ? bars[i0 - 1].t : s[0].t, trough = base, troughDate = peakDate;
    let mdd = { pct: 0, from: null, to: null }, mr = { pct: 0, from: null, to: null };
    let best = { pct: -Infinity, date: null }, worst = { pct: Infinity, date: null };
    let gapMax = null;
    let up = 0, down = 0, volSum = 0, maxVol = { v: -1, date: null };
    let prev = base;

    for (let k = 0; k < s.length; k++) {
      const b = s[k];
      if (b.h > high.price) high = { price: b.h, date: b.t };
      if (b.l < low.price) low = { price: b.l, date: b.t };
      if (b.c > peak) { peak = b.c; peakDate = b.t; }
      const dd = (b.c - peak) / peak;
      if (dd < mdd.pct) mdd = { pct: dd, from: peakDate, to: b.t };
      if (b.c < trough) { trough = b.c; troughDate = b.t; }
      const ru = (b.c - trough) / trough;
      if (ru > mr.pct) mr = { pct: ru, from: troughDate, to: b.t };
      const r = (b.c - prev) / prev;
      if (r > best.pct) best = { pct: r, date: b.t };
      if (r < worst.pct) worst = { pct: r, date: b.t };
      if (r > 0) up++; else if (r < 0) down++;
      const gi = i0 + k;
      if (gi > 0) {
        const g = (b.o - bars[gi - 1].c) / bars[gi - 1].c;
        if (!gapMax || Math.abs(g) > Math.abs(gapMax.pct)) gapMax = { pct: g, date: b.t };
      }
      volSum += b.v;
      if (b.v > maxVol.v) maxVol = { v: b.v, date: b.t };
      prev = b.c;
    }
    const avgVol = volSum / s.length;
    const pre = bars.slice(Math.max(0, i0 - 50), i0);
    const preAvg = pre.length ? pre.reduce((a, b) => a + b.v, 0) / pre.length : null;
    const sma50 = smaCache.sma50 ? smaCache.sma50[i1] : null;
    const sma200 = smaCache.sma200 ? smaCache.sma200[i1] : null;

    const r4 = x => (x == null || !isFinite(x) ? null : Math.round(x * 10000) / 10000);
    return {
      base: r4(base), baseLabel, lastClose: r4(lastClose),
      change: r4(lastClose - base), changePct: r4((lastClose - base) / base),
      high: { price: r4(high.price), date: high.date },
      low: { price: r4(low.price), date: low.date },
      rangePct: r4((high.price - low.price) / low.price),
      maxDrawdown: { pct: r4(mdd.pct), from: mdd.from, to: mdd.to },
      maxRally: { pct: r4(mr.pct), from: mr.from, to: mr.to },
      bestDay: { pct: r4(best.pct), date: best.date },
      worstDay: { pct: r4(worst.pct), date: worst.date },
      biggestGap: gapMax && Math.abs(gapMax.pct) >= 0.01 ? { pct: r4(gapMax.pct), date: gapMax.date } : null,
      upDays: up, downDays: down,
      avgVolume: Math.round(avgVol), totalVolume: volSum,
      maxVolume: { volume: maxVol.v, date: maxVol.date },
      prior50dAvgVolume: preAvg ? Math.round(preAvg) : null,
      relVolume: preAvg ? r4(avgVol / preAvg) : null,
      end: {
        rsi: rsi[i1] != null ? r4(rsi[i1]) : null,
        sma50: r4(sma50), sma200: r4(sma200),
        vsSma50: sma50 ? r4(lastClose / sma50 - 1) : null,
        vsSma200: sma200 ? r4(lastClose / sma200 - 1) : null
      }
    };
  }

  function renderStats(st) {
    const a = bars[sel.i0], b = bars[sel.i1];
    const days = sel.i1 - sel.i0 + 1;
    const cell = (label, value, sub, c) => `<div class="cell"><div class="lbl">${label}</div><div class="val ${c || ''}">${value}</div>${sub ? `<div class="sub">${sub}</div>` : ''}</div>`;
    $('stats').innerHTML =
      `<div class="stats-head">
         <div><b>${dateLabel(a.t)} → ${dateLabel(b.t)}</b> <span class="muted">· ${days} trading day${days === 1 ? '' : 's'}</span></div>
         <div class="actions">
           <input id="hlLabel" placeholder="Label (optional)" />
           <button class="btn" id="pin" title="Save this range as a highlight in the .stock file">📌 Pin</button>
           <button class="btn" id="copy" title="Copy a text summary">Copy</button>
           <button class="btn" id="clear" title="Clear selection (Esc)">✕</button>
         </div>
       </div>
       <div class="grid">
         ${cell('Change', pct(st.changePct), `${money(st.base)} ${st.baseLabel} → ${money(st.lastClose)}`, cls(st.changePct))}
         ${cell('High / Low', `${money(st.high.price)} / ${money(st.low.price)}`, `${dateLabel(st.high.date)} / ${dateLabel(st.low.date)}`)}
         ${cell('Max drawdown', pct(st.maxDrawdown.pct), st.maxDrawdown.from ? `${dateLabel(st.maxDrawdown.from)} → ${dateLabel(st.maxDrawdown.to)}` : 'none', st.maxDrawdown.pct < 0 ? 'down' : '')}
         ${cell('Max rally', pct(st.maxRally.pct), st.maxRally.from ? `${dateLabel(st.maxRally.from)} → ${dateLabel(st.maxRally.to)}` : 'none', st.maxRally.pct > 0 ? 'up' : '')}
         ${cell('Best / worst day', `<span class="up">${pct(st.bestDay.pct)}</span> / <span class="down">${pct(st.worstDay.pct)}</span>`, `${dateLabel(st.bestDay.date)} / ${dateLabel(st.worstDay.date)}`)}
         ${cell('Up / down days', `${st.upDays} / ${st.downDays}`, '')}
         ${cell('Avg volume', vol(st.avgVolume), st.relVolume ? `${st.relVolume.toFixed(1)}× prior 50-day avg` : '', st.relVolume >= 1.5 ? 'warn' : '')}
         ${st.biggestGap ? cell('Biggest gap', pct(st.biggestGap.pct), dateLabel(st.biggestGap.date), cls(st.biggestGap.pct)) : ''}
         ${cell('At end', `RSI ${st.end.rsi != null ? st.end.rsi.toFixed(0) : '–'}`, `vs 50d ${pct(st.end.vsSma50)} · vs 200d ${pct(st.end.vsSma200)}`)}
       </div>`;
    show('stats');
    $('pin').onclick = () => vscode.postMessage({ type: 'pinHighlight', from: a.t, to: b.t, label: $('hlLabel').value.trim() || `${pct(st.changePct)}`, color: st.changePct < 0 ? '#ef4444' : '#22c55e' });
    $('copy').onclick = () => vscode.postMessage({ type: 'copy', text: summaryText(st) });
    $('clear').onclick = () => clearSelection(true);
  }

  function summaryText(st) {
    const a = bars[sel.i0].t, b = bars[sel.i1].t;
    return [
      `${spec.symbol} ${a} → ${b} (${sel.i1 - sel.i0 + 1} trading days)`,
      `Change ${pct(st.changePct)} (${st.baseLabel} ${money(st.base)} → ${money(st.lastClose)})`,
      `High ${money(st.high.price)} (${st.high.date}) · Low ${money(st.low.price)} (${st.low.date})`,
      `Max drawdown ${pct(st.maxDrawdown.pct)} · Max rally ${pct(st.maxRally.pct)}`,
      `Best day ${pct(st.bestDay.pct)} (${st.bestDay.date}) · Worst day ${pct(st.worstDay.pct)} (${st.worstDay.date})`,
      `Avg volume ${vol(st.avgVolume)}${st.relVolume ? ` (${st.relVolume.toFixed(1)}× prior 50-day avg)` : ''}`,
      st.biggestGap ? `Biggest gap ${pct(st.biggestGap.pct)} (${st.biggestGap.date})` : '',
      `At end: RSI ${st.end.rsi != null ? st.end.rsi.toFixed(0) : '–'}, vs 50d ${pct(st.end.vsSma50)}, vs 200d ${pct(st.end.vsSma200)}`
    ].filter(Boolean).join('\n');
  }

  // ------------------------------------------------------------ UI events
  function show(id) { $(id).hidden = false; }
  function hide(id) { $(id).hidden = true; }

  function setSelectMode(on) {
    selectMode = on;
    $('selmode').classList.toggle('on', on);
    $('wrap').classList.toggle('selecting', on);
    lockChart(on);
  }

  document.addEventListener('click', e => {
    const t = e.target.closest('button');
    if (!t) return;
    if (t.dataset.range) vscode.postMessage({ type: 'setRange', range: t.dataset.range });
    else if (t.dataset.ind) vscode.postMessage({ type: 'toggleIndicator', id: t.dataset.ind });
    else if (t.dataset.rmhl != null) vscode.postMessage({ type: 'removeHighlight', index: +t.dataset.rmhl });
    else if (t.id === 'selmode') setSelectMode(!selectMode);
    else if (t.id === 'fit') chart.timeScale().fitContent();
    else if (t.id === 'refresh') vscode.postMessage({ type: 'refresh' });
  });

  window.addEventListener('keydown', e => {
    if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return;
    if (e.key === 'Shift' && !shiftDown) { shiftDown = true; $('wrap').classList.add('selecting'); lockChart(true); }
    else if (e.key === 'Escape') clearSelection(true);
    else if (e.key === 's' || e.key === 'S') setSelectMode(!selectMode);
    else if (e.key === 'f' || e.key === 'F') chart.timeScale().fitContent();
  });
  window.addEventListener('keyup', e => {
    if (e.key === 'Shift') {
      shiftDown = false;
      if (!selectMode) { $('wrap').classList.remove('selecting'); if (!drag) lockChart(false); }
    }
  });
  window.addEventListener('blur', () => {
    if (shiftDown) { shiftDown = false; if (!selectMode) { $('wrap').classList.remove('selecting'); lockChart(false); } }
  });

  window.addEventListener('message', e => {
    const m = e.data;
    switch (m.type) {
      case 'render': render(m); break;
      case 'loading': if (!bars.length) { $('sym').textContent = m.symbol; show('loading'); } break;
      case 'error':
        hide('loading');
        $('error').textContent = m.message;
        show('error');
        break;
      case 'select':
        if (!bars.length) return;
        setSelection(idxOnOrAfter(m.from), idxOnOrBefore(m.to || m.from), true);
        revealSelection();
        break;
      case 'clearSelection': clearSelection(false); break;
    }
  });

  initChart();
  // Debug handle (inspect with Developer: Open Webview Developer Tools).
  window.__stockView = { get chart() { return chart; }, get bars() { return bars; }, get sel() { return sel; }, idxOnOrAfter, drawOverlay };
  vscode.postMessage({ type: 'ready' });
})();
