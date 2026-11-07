'use strict';

const vscode = require('vscode');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { fetchBars, readEnvFile } = require('./data');

const VIEW_TYPE = 'stockView.chart';
const CHARTS_DIR = 'charts';
const STATE_DIR = '.stockview';

/** uri.toString() -> { panel, document, post, render, ready } */
const panels = new Map();
const processedIds = new Set();
let lastSelection = null;
let lastResults = [];
let statusItem;
let output;

// ---------------------------------------------------------------- helpers

function workspaceRoot() {
  const f = vscode.workspace.workspaceFolders;
  return f && f.length ? f[0].uri.fsPath : null;
}

function rel(fsPath) {
  const root = workspaceRoot();
  return root ? path.relative(root, fsPath) : fsPath;
}

function stateDir() {
  const root = workspaceRoot();
  if (!root) return null;
  const d = path.join(root, STATE_DIR);
  fs.mkdirSync(d, { recursive: true });
  return d;
}

function log(msg) {
  if (output) output.appendLine(`[${new Date().toLocaleTimeString()}] ${msg}`);
}

function defaultSpec(symbol) {
  return {
    symbol: symbol.toUpperCase(),
    range: '6mo',
    interval: '1d',
    indicators: ['sma50', 'sma200'],
    note: '',
    highlights: [],
    markers: [],
    lines: []
  };
}

function parseSpec(text) {
  let spec;
  try {
    spec = JSON.parse(text);
  } catch (e) {
    throw new Error(`This .stock file is not valid JSON: ${e.message}`);
  }
  if (!spec || typeof spec !== 'object' || !spec.symbol) {
    throw new Error('This .stock file needs at least a "symbol" field, e.g. { "symbol": "INTC" }');
  }
  return Object.assign(defaultSpec(String(spec.symbol)), spec, { symbol: String(spec.symbol).toUpperCase() });
}

function chartUriFor(cmd) {
  const root = workspaceRoot();
  if (!root) throw new Error('Open a folder in VS Code first.');
  if (cmd.file) return vscode.Uri.file(path.isAbsolute(cmd.file) ? cmd.file : path.join(root, cmd.file));
  if (!cmd.symbol) throw new Error('Command needs "symbol" or "file".');
  return vscode.Uri.file(path.join(root, CHARTS_DIR, `${String(cmd.symbol).toUpperCase()}.stock`));
}

async function writeSpec(uri, mutate) {
  const open = vscode.workspace.textDocuments.find(d => d.uri.toString() === uri.toString());
  if (open) {
    let spec;
    try { spec = JSON.parse(open.getText()); } catch { throw new Error(`${rel(uri.fsPath)} has invalid JSON; fix it first.`); }
    mutate(spec);
    const text = JSON.stringify(spec, null, 2) + '\n';
    const edit = new vscode.WorkspaceEdit();
    edit.replace(uri, new vscode.Range(open.positionAt(0), open.positionAt(open.getText().length)), text);
    await vscode.workspace.applyEdit(edit);
    await open.save();
    return;
  }
  let spec = {};
  if (fs.existsSync(uri.fsPath)) spec = JSON.parse(fs.readFileSync(uri.fsPath, 'utf8'));
  mutate(spec);
  fs.mkdirSync(path.dirname(uri.fsPath), { recursive: true });
  fs.writeFileSync(uri.fsPath, JSON.stringify(spec, null, 2) + '\n');
}

async function ensureChartFile(cmd) {
  const uri = chartUriFor(cmd);
  const exists = fs.existsSync(uri.fsPath);
  if (!exists || cmd.spec) {
    await writeSpec(uri, spec => {
      if (!exists) Object.assign(spec, defaultSpec(cmd.symbol || path.basename(uri.fsPath, '.stock')));
      if (cmd.spec) Object.assign(spec, cmd.spec);
    });
  }
  return uri;
}

function chartTabs(pred = () => true) {
  const tabs = [];
  for (const g of vscode.window.tabGroups.all) {
    for (const t of g.tabs) {
      if (t.input instanceof vscode.TabInputCustom && t.input.viewType === VIEW_TYPE && pred(t.input.uri, t, g)) tabs.push(t);
    }
  }
  return tabs;
}

async function waitForPanel(uri, timeoutMs = 10000) {
  const key = uri.toString();
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const p = panels.get(key);
    if (p && p.ready && p.rendered) return p;
    await new Promise(r => setTimeout(r, 150));
  }
  throw new Error(`Chart ${rel(uri.fsPath)} did not finish loading in time.`);
}

async function openChart(uri, { beside = false, preserveFocus = false } = {}) {
  await vscode.commands.executeCommand('vscode.openWith', uri, VIEW_TYPE, {
    viewColumn: beside ? vscode.ViewColumn.Beside : vscode.ViewColumn.Active,
    preview: false,
    preserveFocus
  });
}

// ------------------------------------------------------------ state files

function writeState() {
  const dir = stateDir();
  if (!dir) return;
  const open = chartTabs().map(t => {
    const g = vscode.window.tabGroups.all.find(gr => gr.tabs.includes(t));
    return {
      file: rel(t.input.uri.fsPath),
      symbol: path.basename(t.input.uri.fsPath, '.stock').toUpperCase(),
      active: !!(t.isActive && g && g.isActive),
      visible: !!t.isActive,
      column: g ? g.viewColumn : null
    };
  });
  const state = {
    updated: new Date().toISOString(),
    openCharts: open,
    selection: lastSelection ? summaryOnly(lastSelection) : null,
    lastCommands: lastResults.slice(-10)
  };
  try { fs.writeFileSync(path.join(dir, 'state.json'), JSON.stringify(state, null, 2) + '\n'); } catch (e) { log(`state write failed: ${e.message}`); }
}

function summaryOnly(sel) {
  const { bars, ...rest } = sel;
  return rest;
}

function writeSelection(sel) {
  const dir = stateDir();
  if (!dir) return;
  fs.writeFileSync(path.join(dir, 'selection.json'), JSON.stringify(sel || { selection: null }, null, 2) + '\n');
}

// ---------------------------------------------------------- status bar

function pct(x) {
  if (x == null || !isFinite(x)) return '–';
  const s = (x * 100).toFixed(1) + '%';
  return x > 0 ? '+' + s : s.replace('-', '−');
}

function selectionText(sel) {
  const s = sel.stats;
  const lines = [
    `${sel.symbol} selection: ${sel.from} → ${sel.to} (${sel.tradingDays} trading days)`,
    `Change: ${pct(s.changePct)} (${s.baseLabel} ${s.base} → close ${s.lastClose})`,
    `High ${s.high.price} on ${s.high.date} · Low ${s.low.price} on ${s.low.date}`,
    `Max drawdown ${pct(s.maxDrawdown.pct)} (${s.maxDrawdown.from} → ${s.maxDrawdown.to}) · Max rally ${pct(s.maxRally.pct)}`,
    `Best day ${pct(s.bestDay.pct)} on ${s.bestDay.date} · Worst day ${pct(s.worstDay.pct)} on ${s.worstDay.date}`,
    `Up days ${s.upDays} / down days ${s.downDays}`,
    `Avg volume ${Math.round(s.avgVolume).toLocaleString()}` + (s.relVolume ? ` (${s.relVolume.toFixed(1)}× the prior 50-day average)` : '')
  ];
  if (s.biggestGap) lines.push(`Biggest gap ${pct(s.biggestGap.pct)} on ${s.biggestGap.date}`);
  if (s.end) lines.push(`At end: RSI ${s.end.rsi != null ? s.end.rsi.toFixed(0) : '–'}, vs 50-day avg ${pct(s.end.vsSma50)}, vs 200-day avg ${pct(s.end.vsSma200)}`);
  return lines.join('\n');
}

function updateStatus() {
  if (!statusItem) return;
  if (!lastSelection) { statusItem.hide(); return; }
  const s = lastSelection.stats;
  statusItem.text = `$(graph-line) ${lastSelection.symbol} ${lastSelection.from} → ${lastSelection.to}: ${pct(s.changePct)}`;
  statusItem.tooltip = selectionText(lastSelection) + '\n\nClick to copy this summary.';
  statusItem.show();
}

// ------------------------------------------------------------ editor

class ChartEditorProvider {
  constructor(context) {
    this.context = context;
  }

  async resolveCustomTextEditor(document, panel) {
    const key = document.uri.toString();
    const mediaRoot = vscode.Uri.joinPath(this.context.extensionUri, 'media');
    panel.webview.options = { enableScripts: true, localResourceRoots: [mediaRoot] };
    panel.webview.html = buildHtml(panel.webview, this.context.extensionUri);

    const entry = { panel, document, ready: false, rendered: false, queue: [] };
    entry.post = msg => {
      if (entry.ready) panel.webview.postMessage(msg);
      else entry.queue.push(msg);
    };
    panels.set(key, entry);

    let renderSeq = 0;
    entry.render = async ({ force = false } = {}) => {
      const seq = ++renderSeq;
      let spec;
      try {
        spec = parseSpec(document.getText());
      } catch (e) {
        entry.post({ type: 'error', message: e.message });
        entry.rendered = true;
        return;
      }
      try {
        let data;
        if (Array.isArray(spec.bars) && spec.bars.length) {
          data = {
            bars: spec.bars.map(b => ({ t: b.t || b.date, o: +b.o, h: +b.h, l: +b.l, c: +b.c, v: +(b.v || 0) })),
            meta: { name: spec.name || spec.symbol, source: spec.source || 'file', currency: 'USD' },
            fetchKey: `file|${spec.symbol}`
          };
        } else {
          entry.post({ type: 'loading', symbol: spec.symbol });
          const env = workspaceRoot() ? readEnvFile(path.join(workspaceRoot(), '.env')) : {};
          const alpaca = env.ALPACA_KEY_ID && env.ALPACA_SECRET_KEY ? { key: env.ALPACA_KEY_ID, secret: env.ALPACA_SECRET_KEY } : null;
          data = await fetchBars(spec.symbol, spec.range, spec.interval, { force, alpaca, prefer: spec.source === 'yahoo' ? 'yahoo' : null });
        }
        if (seq !== renderSeq) return;
        const { bars: _ignored, ...specNoBars } = spec;
        entry.post({ type: 'render', spec: specNoBars, bars: data.bars, meta: data.meta, fetchKey: data.fetchKey, file: rel(document.uri.fsPath) });
      } catch (e) {
        entry.post({ type: 'error', message: e.message });
      } finally {
        entry.rendered = true;
      }
    };

    let debounce;
    const docSub = vscode.workspace.onDidChangeTextDocument(e => {
      if (e.document.uri.toString() !== key) return;
      clearTimeout(debounce);
      debounce = setTimeout(() => entry.render(), 250);
    });

    // Refresh prices every 60s while the chart is visible.
    const timer = setInterval(() => { if (panel.visible) entry.render(); }, 60 * 1000);

    panel.webview.onDidReceiveMessage(msg => this.onMessage(entry, msg));
    panel.onDidChangeViewState(() => writeState());
    panel.onDidDispose(() => {
      docSub.dispose();
      clearInterval(timer);
      clearTimeout(debounce);
      panels.delete(key);
      setTimeout(writeState, 50);
    });
    writeState();
  }

  async onMessage(entry, msg) {
    const { document } = entry;
    try {
      switch (msg.type) {
        case 'ready':
          entry.ready = true;
          entry.queue.splice(0).forEach(m => entry.panel.webview.postMessage(m));
          await entry.render();
          break;
        case 'refresh':
          await entry.render({ force: true });
          break;
        case 'selection':
          lastSelection = Object.assign({ file: rel(document.uri.fsPath) }, msg.selection);
          writeSelection(lastSelection);
          updateStatus();
          writeState();
          break;
        case 'clearSelection':
          lastSelection = null;
          writeSelection(null);
          updateStatus();
          writeState();
          break;
        case 'setRange':
          await writeSpec(document.uri, s => { s.range = msg.range; });
          break;
        case 'toggleIndicator':
          await writeSpec(document.uri, s => {
            const set = new Set(s.indicators || []);
            if (set.has(msg.id)) set.delete(msg.id); else set.add(msg.id);
            s.indicators = [...set];
          });
          break;
        case 'pinHighlight':
          await writeSpec(document.uri, s => {
            s.highlights = s.highlights || [];
            s.highlights.push({ from: msg.from, to: msg.to, label: msg.label || '', color: msg.color || '#3b82f6' });
          });
          break;
        case 'removeHighlight':
          await writeSpec(document.uri, s => {
            s.highlights = (s.highlights || []).filter((_, i) => i !== msg.index);
          });
          break;
        case 'copy':
          await vscode.env.clipboard.writeText(msg.text);
          vscode.window.setStatusBarMessage('Stock View: selection summary copied', 2500);
          break;
      }
    } catch (e) {
      vscode.window.showErrorMessage(`Stock View: ${e.message}`);
    }
  }
}

function buildHtml(webview, extUri) {
  const media = f => webview.asWebviewUri(vscode.Uri.joinPath(extUri, 'media', f));
  const nonce = crypto.randomBytes(16).toString('base64');
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${webview.cspSource} data:; style-src ${webview.cspSource} 'unsafe-inline'; font-src ${webview.cspSource}; script-src 'nonce-${nonce}';">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="stylesheet" href="${media('chart.css')}">
<title>Stock Chart</title>
</head>
<body>
<div id="root"></div>
<script nonce="${nonce}" src="${media('lightweight-charts.standalone.production.js')}"></script>
<script nonce="${nonce}" src="${media('chart.js')}"></script>
</body>
</html>`;
}

// ------------------------------------------------------- control channel
// Claude (or any script) writes .stockview/control.json:
//   { "id": "unique", "action": "open", "symbol": "AMD", "beside": true, "spec": {...}, "select": {"from":"2026-10-29","to":"2026-11-05"} }
// or { "commands": [ ...several of the above... ] }
// Results are appended to .stockview/state.json -> lastCommands.

async function runCommand(cmd) {
  switch (cmd.action) {
    case 'open': {
      const uri = await ensureChartFile(cmd);
      await openChart(uri, { beside: !!cmd.beside, preserveFocus: !!cmd.preserveFocus });
      if (cmd.select) {
        const p = await waitForPanel(uri);
        p.post({ type: 'select', from: cmd.select.from, to: cmd.select.to });
      }
      return `opened ${rel(uri.fsPath)}`;
    }
    case 'update': {
      const uri = chartUriFor(cmd);
      if (!fs.existsSync(uri.fsPath)) throw new Error(`${rel(uri.fsPath)} does not exist`);
      await writeSpec(uri, s => Object.assign(s, cmd.spec || {}));
      return `updated ${rel(uri.fsPath)}`;
    }
    case 'select': {
      const uri = await ensureChartFile(cmd);
      if (!panels.has(uri.toString())) await openChart(uri, { beside: !!cmd.beside });
      const p = await waitForPanel(uri);
      p.panel.reveal(undefined, false);
      p.post({ type: 'select', from: cmd.from, to: cmd.to });
      return `selected ${cmd.from} → ${cmd.to} on ${rel(uri.fsPath)}`;
    }
    case 'clearSelection': {
      for (const p of panels.values()) p.post({ type: 'clearSelection' });
      lastSelection = null;
      writeSelection(null);
      updateStatus();
      return 'selection cleared';
    }
    case 'focus': {
      const uri = chartUriFor(cmd);
      await openChart(uri);
      return `focused ${rel(uri.fsPath)}`;
    }
    case 'close': {
      const uri = chartUriFor(cmd);
      const tabs = chartTabs(u => u.toString() === uri.toString());
      if (tabs.length) await vscode.window.tabGroups.close(tabs);
      return `closed ${rel(uri.fsPath)} (${tabs.length} tab${tabs.length === 1 ? '' : 's'})`;
    }
    case 'closeAll': {
      const tabs = chartTabs();
      if (tabs.length) await vscode.window.tabGroups.close(tabs);
      return `closed ${tabs.length} chart tab${tabs.length === 1 ? '' : 's'}`;
    }
    default:
      throw new Error(`Unknown action "${cmd.action}"`);
  }
}

function readControl() {
  const dir = stateDir();
  if (!dir) return [];
  const file = path.join(dir, 'control.json');
  if (!fs.existsSync(file)) return [];
  const raw = fs.readFileSync(file, 'utf8').trim();
  if (!raw) return [];
  const j = JSON.parse(raw);
  const list = Array.isArray(j) ? j : (Array.isArray(j.commands) ? j.commands : [j]);
  return list.map((c, i) => Object.assign({ id: c.id || `${crypto.createHash('sha1').update(JSON.stringify(c)).digest('hex').slice(0, 12)}-${i}` }, c));
}

let controlBusy = Promise.resolve();
function processControl() {
  controlBusy = controlBusy.then(async () => {
    let cmds;
    try { cmds = readControl(); } catch (e) {
      lastResults.push({ id: null, ok: false, error: `control.json: ${e.message}`, at: new Date().toISOString() });
      writeState();
      return;
    }
    for (const cmd of cmds) {
      if (processedIds.has(cmd.id)) continue;
      processedIds.add(cmd.id);
      try {
        const result = await runCommand(cmd);
        lastResults.push({ id: cmd.id, action: cmd.action, ok: true, result, at: new Date().toISOString() });
        log(`${cmd.action}: ${result}`);
      } catch (e) {
        lastResults.push({ id: cmd.id, action: cmd.action, ok: false, error: e.message, at: new Date().toISOString() });
        log(`${cmd.action} failed: ${e.message}`);
      }
    }
    lastResults = lastResults.slice(-20);
    setTimeout(writeState, 300);
  });
  return controlBusy;
}

// ---------------------------------------------------------------- activate

function activate(context) {
  output = vscode.window.createOutputChannel('Stock View');
  context.subscriptions.push(output);

  context.subscriptions.push(
    vscode.window.registerCustomEditorProvider(VIEW_TYPE, new ChartEditorProvider(context), {
      webviewOptions: { retainContextWhenHidden: true },
      supportsMultipleEditorsPerDocument: false
    })
  );

  statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
  statusItem.command = 'stockView.copySelection';
  context.subscriptions.push(statusItem);

  context.subscriptions.push(
    vscode.commands.registerCommand('stockView.openSymbol', async () => {
      const sym = await vscode.window.showInputBox({ prompt: 'Stock symbol (e.g. INTC, AAPL, BRK.B)', placeHolder: 'INTC' });
      if (!sym) return;
      try {
        const uri = await ensureChartFile({ symbol: sym.trim() });
        await openChart(uri);
      } catch (e) { vscode.window.showErrorMessage(`Stock View: ${e.message}`); }
    }),
    vscode.commands.registerCommand('stockView.closeAll', () => runCommand({ action: 'closeAll' })),
    vscode.commands.registerCommand('stockView.copySelection', async () => {
      if (!lastSelection) { vscode.window.showInformationMessage('No chart selection yet. Shift+drag on a chart to select a range.'); return; }
      await vscode.env.clipboard.writeText(selectionText(lastSelection));
      vscode.window.setStatusBarMessage('Stock View: selection summary copied', 2500);
    }),
    vscode.commands.registerCommand('stockView.refresh', async () => {
      for (const p of panels.values()) if (p.panel.active) await p.render({ force: true });
    }),
    vscode.window.tabGroups.onDidChangeTabs(() => writeState()),
    vscode.window.tabGroups.onDidChangeTabGroups(() => writeState())
  );

  const root = workspaceRoot();
  if (root) {
    // Ignore commands that were already in control.json before this window started.
    try { readControl().forEach(c => processedIds.add(c.id)); } catch { /* ignore bad file */ }

    const ctl = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(root, `${STATE_DIR}/control.json`));
    ctl.onDidChange(processControl);
    ctl.onDidCreate(processControl);
    context.subscriptions.push(ctl);

    // Deleting a .stock file closes its chart.
    const charts = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(root, '**/*.stock'));
    charts.onDidDelete(async uri => {
      const tabs = chartTabs(u => u.toString() === uri.toString());
      if (tabs.length) await vscode.window.tabGroups.close(tabs);
    });
    context.subscriptions.push(charts);

    // Restore last selection (if any) so the status bar survives reloads.
    try {
      const s = JSON.parse(fs.readFileSync(path.join(root, STATE_DIR, 'selection.json'), 'utf8'));
      if (s && s.stats) { lastSelection = s; updateStatus(); }
    } catch { /* none yet */ }
    writeState();
  }
  log('Stock View activated');
}

function deactivate() {}

module.exports = { activate, deactivate };
