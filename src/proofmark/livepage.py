"""The live page: a status board for a running strategy.

Rebuilt twice. The first version was a light cream document that predated the
report page's redesign, so opening the live view from the app was a jarring
change of world. The second version is this one, on the same tokens as
:mod:`proofmark.page`.

It answers, in this order:

    Is it running?   What has it done?   Is it beating doing nothing?
    Is anything unprotected?   Has it drifted somewhere impossible?

WHAT CHANGED ABOUT SHOWING PRICES.

The original refused to draw a price chart at all, reasoning that a chart is
what tempts a person to intervene. In practice that made the page unable to
answer its own first question: a bot correctly sitting out a flat market and a
bot whose feed died look identical when the only thing on screen is a flat
equity line.

So the price is drawn, with the entries and exits marked, up to the last closed
bar. It is a record of what the rules did. There is no order entry, no manual
close, no override, and nothing on this page places a trade.

NOTHING ANIMATES ON A TIMER.

The charts redraw every few seconds. A draw-on animation that restarts each
poll is a strobe. The report page animates because it is read once; this one
does not, because it is left open.
"""

LIVE_PAGE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>proofmark, live</title>
<style>
  :root {
    color-scheme: dark light;
    --bg:#12100E; --panel:#1A1714; --raised:#221E19;
    --ink:#F4EFE7; --soft:#A79C8C; --faint:#6E655A;
    --line:#2E2822; --brass:#D9A93C; --brass-dim:#7A5F1E;
    --pass:#5FD08A; --fail:#FF8A75; --warn:#E7B85C;
    --serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
    --sans:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Inter,sans-serif;
    --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
  }
  @media (prefers-color-scheme: light) {
    :root {
      --bg:#F3F1ED; --panel:#FFFFFF; --raised:#F7F5F1;
      --ink:#14120F; --soft:#55504A; --faint:#837D74;
      --line:#E4E0D8; --brass:#7A5310; --brass-dim:#CBBFA6;
      --pass:#116639; --fail:#992010; --warn:#6B4C06;
    }
    .card { box-shadow:0 1px 2px rgba(20,18,15,.05); }
  }

  *,*::before,*::after { box-sizing:border-box; }
  body {
    margin:0; background:var(--bg); color:var(--ink);
    font:17px/1.65 var(--sans); -webkit-font-smoothing:antialiased;
  }
  /* Wide on purpose. Every chart here is an SVG at width:100%, so the column
     width IS the chart's font size: at 47rem the axis labels rendered around
     11px and were genuinely hard to read on a large monitor. Prose gets its
     own narrower cap below, so it does not become unreadable the other way. */
  .wrap {
    max-width:68rem; margin:0 auto; padding:2.4rem 1.5rem 5rem;
    display:flex; flex-direction:column;
  }
  /* A bot that stopped reporting two days ago is history, and the thing a
     person needs is the way to start another one. Hoisting by order rather
     than moving nodes, so nothing re-renders and no scroll position jumps. */
  /* The masthead and heartbeat stay pinned above everything, or hoisting the
     controls pushes them above the product's own name. */
  .wrap > .top { order:-3; }
  .wrap > .pulse { order:-2; }
  .wrap.needs-start #control { order:-1; }
  .wrap.needs-start #control.tucked { opacity:1; }
  .card p.cap, .card .empty, .foot, .hint { max-width:56ch; }

  .top { display:flex; align-items:center; gap:.8rem; margin-bottom:1.6rem; }
  .stamp { width:32px; height:32px; flex:none; }
  .top h1 { margin:0; font:600 1.05rem/1 var(--sans); letter-spacing:.2em; text-transform:uppercase; }
  .top p { margin:.25rem 0 0; font-size:.85rem; color:var(--soft); }

  .nav { margin-left:auto; display:flex; gap:.35rem; flex-wrap:wrap; }
  .nav a, .nav .here {
    font:600 .78rem/1 var(--sans); padding:.5rem .75rem; border-radius:8px;
    text-decoration:none; white-space:nowrap;
    transition:background .18s ease, color .18s ease;
  }
  .nav .here { color:var(--ink); background:var(--raised); }
  .nav a { color:var(--soft); }
  .nav a:hover { color:var(--ink); background:var(--raised); }
  .nav a:focus-visible {
    outline:none; color:var(--ink);
    box-shadow:0 0 0 3px color-mix(in srgb, var(--brass) 32%, transparent);
  }

  /* The heartbeat, on its own line under the header. "Is it still running"
     outranks every number on the page, so it does not compete with the nav
     for the same corner. */
  .pulse {
    display:flex; align-items:center; gap:.55rem; margin:0 0 1.2rem;
    font:600 .7rem/1 var(--sans); letter-spacing:.11em; text-transform:uppercase;
    color:var(--soft); white-space:nowrap;
  }
  .dot { width:8px; height:8px; border-radius:50%; background:var(--pass); flex:none; }
  .dot.stale { background:var(--fail); }
  /* Never started is not the same as stopped writing. A red light on a page
     nobody has used yet reports a fault that has not happened. */
  .dot.idle { background:var(--faint); }
  @media (prefers-reduced-motion:no-preference) {
    .dot:not(.stale) { animation:beat 2.4s ease-in-out infinite; }
    @keyframes beat {
      0%,100% { box-shadow:0 0 0 0 color-mix(in srgb, var(--pass) 60%, transparent); }
      55%     { box-shadow:0 0 0 6px color-mix(in srgb, var(--pass) 0%, transparent); }
    }
  }

  .card {
    background:var(--panel); border:1px solid var(--line); border-radius:12px;
    padding:1.2rem 1.35rem; margin-bottom:1.1rem;
  }
  .card h2 {
    margin:0 0 .2rem; font:600 1rem/1.4 var(--sans);
  }
  .card p.cap { margin:0 0 .2rem; font-size:.92rem; color:var(--soft); }

  .banner { border-radius:12px; padding:1rem 1.2rem; margin-bottom:1.1rem; }
  .banner h2 { margin:0 0 .2rem; font:600 1.05rem/1.35 var(--serif); }
  .banner p { margin:0; font-size:.88rem; }
  .banner.bad { background:color-mix(in srgb, var(--fail) 13%, var(--panel));
                border:1px solid color-mix(in srgb, var(--fail) 34%, transparent); }
  .banner.bad h2 { color:var(--fail); }
  .banner.warn { background:color-mix(in srgb, var(--warn) 13%, var(--panel));
                 border:1px solid color-mix(in srgb, var(--warn) 34%, transparent); }
  .banner.warn h2 { color:var(--warn); }
  .banner p { color:var(--soft); }

  /* The answer to "is this working", in words, before any number. */
  .verdictline {
    margin:.2rem 0 1.5rem; font:1.65rem/1.35 var(--serif); letter-spacing:-.012em;
    color:var(--ink); max-width:52ch; text-wrap:balance;
  }
  .verdictline b { font-weight:inherit; }
  .verdictline b.ahead { color:var(--pass); }
  .verdictline b.behind { color:var(--fail); }
  /* Stale means these numbers are a photograph, so the whole line steps back. */
  .verdictline.old { color:var(--soft); }
  @media (max-width:36rem) { .verdictline { font-size:1.25rem; } }

  .figures { display:grid; grid-template-columns:repeat(auto-fit,minmax(9rem,1fr)); gap:.8rem; }
  .fig { background:var(--raised); border-radius:10px; padding:.85rem .95rem; }
  .fig dt { font:.82rem/1.3 var(--sans); color:var(--soft); margin-bottom:.3rem; }
  .fig dd { margin:0; font:600 1.35rem/1.2 var(--mono); font-variant-numeric:tabular-nums; }
  .fig dd.up { color:var(--pass); }
  .fig dd.down { color:var(--fail); }

    /* height:auto is doing real work here. The SVG carries height="260" as a
     presentation attribute, and with the default preserveAspectRatio a 720x260
     viewBox inside a 995px box scaled to min(1.38, 1.00) = 1.00 and centred
     itself, leaving blank margins and drawing the chart at a third of the
     available width. Letting the height come from the viewBox makes the chart
     fill the card, and every label inside it grows with it. */
  svg.chart { display:block; width:100%; height:auto; margin-top:.9rem; overflow:visible; }
  svg.chart .grid { stroke:var(--line); stroke-width:1; }
  svg.chart .base { stroke:var(--soft); stroke-width:1; stroke-dasharray:2 3; opacity:.7; }
  svg.chart .tick { fill:var(--faint); font:13px var(--mono); font-variant-numeric:tabular-nums; }
  svg.chart .tick-base { fill:var(--soft); }
  svg.chart .tag { font:600 13px var(--sans); letter-spacing:.03em; }
  svg.chart .bench-tag { fill:var(--soft); }
  svg.chart .subject-tag { fill:var(--brass); }
  svg.chart .subject { fill:none; stroke:var(--brass); stroke-width:2.2; stroke-linejoin:round; stroke-linecap:round; }
  svg.chart .bench { fill:none; stroke:var(--soft); stroke-width:1.3; stroke-dasharray:5 4; opacity:.8; }
  svg.chart .underwater { fill:var(--fail); fill-opacity:.16; stroke:none; }
  svg.chart .underwater-line { fill:none; stroke:var(--fail); stroke-width:1.6; stroke-linejoin:round; }

  /* The price line is quieter than the equity line on purpose. It is context
     for the marks, and the marks are the thing worth looking at. */
  svg.chart .price { fill:none; stroke:var(--soft); stroke-width:1.5; stroke-linejoin:round; }
  svg.chart .mark { stroke:var(--panel); stroke-width:1; }
  svg.chart .mark.buy { fill:var(--pass); }
  svg.chart .mark.sell { fill:var(--fail); }

  .chart-caption { margin:.7rem 0 0; font:.92rem/1.5 var(--sans); color:var(--soft);
                   font-variant-numeric:tabular-nums; }

  ol.notes { list-style:none; margin:0; padding:0; }
  ol.notes li { padding:.9rem 0; border-bottom:1px solid var(--line); }
  ol.notes li:last-child { border-bottom:0; padding-bottom:0; }
  ol.notes b { display:block; font-weight:600; margin-bottom:.2rem; font-size:.95rem; }
  ol.notes p { margin:0; color:var(--soft); font-size:.88rem; }

  table.rows { width:100%; border-collapse:collapse; font:500 .94rem/1.55 var(--sans);
               font-variant-numeric:tabular-nums; }
  table.rows th { text-align:left; font:600 .74rem/1.4 var(--sans); letter-spacing:.09em;
                  text-transform:uppercase; color:var(--faint); padding:0 .55rem .5rem;
                  border-bottom:1px solid var(--line); }
  table.rows td { padding:.62rem .6rem; border-bottom:1px solid var(--line); }
  table.rows tr:last-child td { border-bottom:0; }
  table.rows .n { text-align:right; }
  table.rows .up { color:var(--pass); }
  table.rows .down { color:var(--fail); }
  table.rows .flag { color:var(--warn); font-weight:600; }
  .clock { color:var(--faint); font-family:var(--mono); font-size:.86rem; white-space:nowrap; }
  .act { font-weight:600; }
  .act.buy { color:var(--pass); }
  .act.sell { color:var(--fail); }

  /* The start form. This is the only way most people will ever begin a run:
     the packaged app is windowed, so it has no console to type a command in. */
  .fields { display:grid; grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));
            gap:.8rem; margin:.9rem 0 0; }
  label.lbl { display:block; font:600 .78rem/1.4 var(--sans); margin-bottom:.3rem; }
  input, select {
    width:100%; font:500 .88rem var(--mono); color:var(--ink); background:var(--raised);
    border:1px solid var(--line); border-radius:8px; padding:.55rem .65rem;
    transition:border-color .18s ease, box-shadow .18s ease;
  }
  input:focus-visible, select:focus-visible {
    outline:none; border-color:var(--brass);
    box-shadow:0 0 0 3px color-mix(in srgb, var(--brass) 22%, transparent);
  }
  .actions { display:flex; gap:.6rem; margin-top:1.1rem; flex-wrap:wrap; }
  button {
    font:600 .88rem var(--sans); border-radius:9px; padding:.62rem 1.15rem;
    border:1px solid transparent; cursor:pointer;
    transition:transform .12s cubic-bezier(.3,.8,.4,1), filter .18s ease, background .18s ease;
  }
  button:active { transform:translateY(1px) scale(.99); }
  button:focus-visible { outline:none; box-shadow:0 0 0 3px color-mix(in srgb, var(--brass) 32%, transparent); }
  button:disabled { opacity:.45; cursor:default; transform:none; }
  button.go { background:var(--brass); color:#12100E; }
  button.go:hover:not(:disabled) { filter:brightness(1.08); }
  button.ghost { background:transparent; color:var(--ink); border-color:var(--line); }
  button.ghost:hover:not(:disabled) { border-color:var(--soft); }
  .hint { margin:.35rem 0 0; font-size:.78rem; color:var(--faint); line-height:1.5; }
  .err { color:var(--fail); font-size:.85rem; margin:.8rem 0 0; }

  /* Systems. Each is a card that states what it trades, what it risks, and
     whether it has been checked. The check state is the loudest thing on it. */
  .systems { display:grid; gap:.9rem; }
  /* Once something is running, choosing what to run is a thing you do rarely.
     It stays reachable and stops competing with the status board. */
  #control.tucked { opacity:.72; transition:opacity .2s ease; }
  #control.tucked:hover, #control.tucked:focus-within { opacity:1; }
  #control.tucked .card > h2::after {
    content:" (already running one)"; color:var(--faint); font-weight:400;
  }
  .system {
    background:var(--raised); border:1px solid var(--line); border-radius:11px;
    padding:1rem 1.1rem;
  }
  .system.on { border-color:var(--brass); }
  .system h3 { margin:0; font:600 .98rem/1.3 var(--sans); display:flex;
               align-items:center; gap:.6rem; flex-wrap:wrap; }
  .system p { margin:.3rem 0 0; font-size:.88rem; color:var(--soft); max-width:60ch; }
  .chip {
    font:600 .64rem/1 var(--sans); letter-spacing:.09em; text-transform:uppercase;
    padding:.32rem .5rem; border-radius:5px; white-space:nowrap;
  }
  .chip.ok   { color:var(--pass); background:color-mix(in srgb, var(--pass) 16%, transparent); }
  .chip.no   { color:var(--warn); background:color-mix(in srgb, var(--warn) 16%, transparent); }
  .chip.bad  { color:var(--fail); background:color-mix(in srgb, var(--fail) 16%, transparent); }
  .legs { display:flex; flex-wrap:wrap; gap:.4rem; margin-top:.7rem; }
  .leg {
    font:500 .78rem/1 var(--mono); background:var(--panel); border:1px solid var(--line);
    border-radius:6px; padding:.4rem .55rem; color:var(--soft);
  }
  .leg b { color:var(--ink); font-weight:600; }
  .rule { margin-top:.6rem; font:.8rem/1.6 var(--mono); color:var(--faint); }
  .needs { margin:.7rem 0 0; padding:0; list-style:none; }
  .needs li { font-size:.82rem; color:var(--warn); margin-top:.3rem; }
  .verdict-line { margin-top:.7rem; font-size:.86rem; }
  .verdict-line.pass { color:var(--pass); }
  .verdict-line.fail { color:var(--fail); }

  .empty { color:var(--soft); font-size:.94rem; margin:0; }
  .empty code { font:500 .82em/1 var(--mono); background:var(--raised);
                padding:.15em .4em; border-radius:4px; }
  .foot { margin-top:2.4rem; font-size:.88rem; color:var(--faint); line-height:1.7; }
  .mode { display:inline-block; font:600 .66rem/1 var(--sans); letter-spacing:.1em;
          text-transform:uppercase; padding:.32rem .55rem; border-radius:6px;
          color:var(--brass); background:color-mix(in srgb, var(--brass) 15%, transparent); }

  @media (max-width:36rem) { .wrap { padding:1.8rem 1.1rem 3.5rem; } }
</style>
<div class="wrap">
  <header class="top">
    <svg class="stamp" viewBox="0 0 40 40" aria-hidden="true">
      <circle cx="20" cy="20" r="18" fill="none" stroke="var(--brass)" stroke-width="1.4"/>
      <circle cx="20" cy="20" r="13.5" fill="none" stroke="var(--brass)" stroke-width="1" opacity=".45"/>
      <path d="M13 21.5l4.6 4.6L27.5 15" fill="none" stroke="var(--brass)" stroke-width="2.4"
            stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
    <div>
      <h1>Proofmark</h1>
      <p id="what">connecting</p>
    </div>
    <nav class="nav">
      <span class="here">Your bot</span>
      <a href="/check">Check a result</a>
    </nav>
  </header>
  <div class="pulse"><span class="dot" id="dot"></span><span id="age">&nbsp;</span></div>

  <div id="out" aria-live="polite"></div>
  <div id="control"></div>

  <p class="foot">Nothing on this page places, closes or overrides an order. The
  charts show closed bars only, because the bar still forming has a price that
  has not happened yet.</p>
</div>
<script>
const esc = s => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const $ = id => document.getElementById(id);

function ago(seconds) {
  if (seconds < 60) return Math.round(seconds) + 's ago';
  if (seconds < 3600) return Math.round(seconds / 60) + 'm ago';
  return Math.round(seconds / 3600) + 'h ago';
}

// Rebuilt only when the run's status changes. Redrawing a form every five
// seconds would wipe whatever the person was in the middle of typing.
let controlKey = null;

// The last check result, kept OUTSIDE the panel it is drawn into. Finishing a
// check changes the gate state, which rebuilds the panel, which used to destroy
// the result a third of a second after it appeared: you clicked Check, saw
// nothing, and the Run button silently enabled itself.
let lastCheck = null;

function renderControl(c, hasRun) {
  const key = JSON.stringify([c.running, c.canStart, c.error, hasRun, c.writer,
                              c.halt, (c.systems || []).map(x => [x.name, x.cleared, x.verified])]);
  if (key === controlKey) return;
  controlKey = key;

  const s = c.settings || {};
  const box = $('control');

  // A halt outranks everything. It is stated first, it says what tripped it,
  // and lifting it is its own button rather than a side effect of starting a
  // run, so nobody clears a drawdown breach by pressing the thing they press
  // every morning.
  let halted = '';
  if (c.halt) {
    halted = '<div class="banner bad"><h2>Halted</h2><p>' + esc(c.halt.reason)
      + (c.halt.manual ? '' : ' No new positions will be opened. Exits still run.')
      + '</p><div class="actions"><button class="ghost" id="resume">Lift the halt</button>'
      + '</div></div>';
  }

  if (c.running) {
    box.innerHTML = '<div class="card"><h2>Paper run in progress</h2>'
      + '<p class="cap">' + esc(s.symbol || '') + ' ' + esc(s.timeframe || '')
      + ' on ' + esc(s.venue || '') + ', using ' + esc(s.strategy || '')
      + '. Checking for a new closed bar every minute.</p>'
      + (c.error ? '<p class="err">Last cycle failed: ' + esc(c.error) + '</p>' : '')
      + '<div class="actions"><button class="ghost" id="stop">Stop</button></div></div>';
    $('stop').onclick = async () => {
      $('stop').disabled = true;
      await fetch('/stop', {method: 'POST'});
      controlKey = null;
      tick();
    };
    wireResume();
    return;
  }

  const systems = c.systems || [];

  box.innerHTML = '<div class="card"><h2>Systems</h2>'
    + '<p class="cap">A system is every market, rule, size and limit written down '
    + 'together. Nothing runs until it has been checked against history.</p>'
    + '<div class="systems">' + systems.map(sys => {
      const v = sys.verified;
      let chip = '<span class="chip no">not checked</span>';
      if (v && v.passed) chip = '<span class="chip ok">checked</span>';
      else if (v && !v.passed) chip = '<span class="chip bad">disqualified</span>';

      return '<div class="system' + (sys.cleared ? ' on' : '') + '">'
        + '<h3>' + esc(sys.name) + chip + '</h3>'
        + '<p>' + esc(sys.description) + '</p>'
        + '<div class="legs">' + sys.markets.map(m =>
            '<span class="leg"><b>' + esc(m.symbol) + '</b> ' + esc(m.timeframe)
            + ' ' + esc(m.strategy) + '</span>').join('') + '</div>'
        + '<p class="rule">' + esc(sys.risk) + (sys.guard ? '  &middot;  ' + esc(sys.guard) : '')
        + '  &middot;  ' + esc(sys.venue) + '</p>'
        + (sys.needs.length
            ? '<ul class="needs">' + sys.needs.map(n => '<li>' + esc(n) + '</li>').join('') + '</ul>'
            : '')
        + (v ? '<p class="verdict-line ' + (v.passed ? 'pass' : 'fail') + '">'
              + esc(v.summary) + '. Returned ' + esc(v.totalReturn) + ' against '
              + esc(v.benchmarkReturn) + ' for holding, over ' + v.trades + ' trades.'
              + (v.stability ? ' ' + esc(v.stability) : '')
              + (v.passed && !v.beatHolding
                  ? ' Passing is not the same as being worth running.' : '')
              + '</p>'
            : '')
        + '<div class="actions">'
        + '<button class="ghost" data-check="' + esc(sys.name) + '">Check against history</button>'
        + '<button class="go" data-start="' + esc(sys.name) + '"'
        + (sys.cleared ? '' : ' disabled title="' + esc(sys.why) + '"') + '>Run on paper</button>'
        + '</div></div>';
    }).join('') + '</div>'
    + '<p class="hint">Fees and slippage come off both sides of every fill. '
    + 'Decisions are made on a closed bar and filled at the next bar\\'s open, so '
    + 'nothing trades on a price it has already seen.</p>'
    + '<div id="checkOut"></div><p class="err" id="startErr" hidden></p></div>'
    + '<div class="card"><h2>Describe your own strategy</h2>'
    + '<p class="cap">Say how you trade, in your own words. It tells you which '
    + 'of the built-in rules is closest, so you know what to edit. It never '
    + 'writes a system by itself, and it never says whether an idea is good.</p>'
    + '<textarea id="describe" style="min-height:6rem" placeholder="I buy when '
    + 'something has dropped hard and looks oversold, then sell once it has '
    + 'recovered. Mostly on the hourly chart."></textarea>'
    + '<div class="actions"><button class="ghost" id="match">Find the closest rules</button></div>'
    + (c.writer
        ? '<p class="hint">Using ' + esc(c.writer) + ', running on this machine.</p>'
        : '<p class="hint">No local model is installed, so this one cannot answer. '
          + 'Install Ollama and run <code>ollama pull llama3.2:3b</code> if you want '
          + 'it. Everything else works without it.</p>')
    + '<div id="matched"></div></div>';

  if (lastCheck) $('checkOut').innerHTML = lastCheck;
  wireResume();
  const match = $('match');
  if (match) match.onclick = async () => {
    const out = $('matched'), text = $('describe').value.trim();
    if (!text) { out.innerHTML = '<p class="err">Describe it first.</p>'; return; }
    match.disabled = true;
    out.innerHTML = '<p class="empty" style="margin-top:.9rem">Reading it.</p>';
    try {
      const d = await (await fetch('/describe', {method: 'POST',
        body: JSON.stringify({text})})).json();
      out.innerHTML = '<p class="lesson" style="white-space:pre-wrap">' + esc(d.text) + '</p>'
        + (d.credit ? '<p class="hint">' + esc(d.credit) + '</p>' : '');
    } catch (e) {
      out.innerHTML = '<p class="err">Could not reach the local server.</p>';
    }
    match.disabled = false;
  };

  box.querySelectorAll('[data-check]').forEach(btn => {
    btn.onclick = () => runCheck(btn, btn.getAttribute('data-check'));
  });
  box.querySelectorAll('[data-start]').forEach(btn => {
    btn.onclick = () => startSystem(btn, btn.getAttribute('data-start'));
  });
}

function wireResume() {
  const btn = $('resume');
  if (!btn) return;
  btn.onclick = async () => {
    btn.disabled = true;
    await fetch('/resume', {method: 'POST'});
    controlKey = null;
    tick();
  };
}

async function runCheck(btn, name) {
  const out = $('checkOut'), label = btn.textContent;
  btn.disabled = true; btn.textContent = 'Checking';
  out.innerHTML = '<p class="empty" style="margin-top:1rem">Pulling history and '
    + 'running every market. This takes a few seconds.</p>';
  try {
    const res = await fetch('/check-system', {method: 'POST', body: JSON.stringify({name})});
    const d = await res.json();
    if (d.error) {
      out.innerHTML = '<p class="err">' + esc(d.error) + '</p>';
    } else {
      lastCheck = '<div class="banner ' + (d.passed ? 'warn' : 'bad') + '" '
        + 'style="margin-top:1rem">'
        + '<h2>' + (d.passed ? 'Cleared to run' : 'Not cleared to run') + '</h2>'
        + '<p>' + esc(d.summary) + '. Returned ' + esc(d.totalReturn) + ' against '
        + esc(d.benchmarkReturn) + ' for buying and holding, over ' + d.trades
        + ' trades and ' + d.bars + ' steps.'
        + (d.passed && !d.beatHolding
            ? ' It passed the checks and still finished behind doing nothing.' : '')
        + (d.haltedAt !== null && d.haltedAt !== undefined
            ? ' It stopped itself: ' + esc(d.haltReason) : '')
        + '</p></div>'
        + (d.windows && d.windows.length
            ? '<div class="card"><h2>Window by window</h2>'
              + '<p class="cap">The same system run separately on each slice of '
              + 'history. A result carried by one lucky stretch shows up here and '
              + 'nowhere else.</p>'
              + '<table class="rows"><thead><tr><th>window</th><th class="n">return</th>'
              + '<th class="n">holding</th><th class="n">trades</th><th></th></tr></thead>'
              + '<tbody>' + d.windows.map(w =>
                  '<tr><td>' + w.index + '</td>'
                  + '<td class="n ' + (w.won ? 'up' : 'down') + '">' + esc(w.ret) + '</td>'
                  + '<td class="n">' + esc(w.bench) + '</td>'
                  + '<td class="n">' + w.trades + '</td>'
                  + '<td>' + (w.halted ? '<span class="flag">stopped</span>' : '') + '</td>'
                  + '</tr>').join('')
              + '</tbody></table>'
              + (d.stability ? '<p class="rule" style="margin-top:.9rem">'
                  + esc(d.stability) + '</p>' : '')
              + '</div>'
            : '')
        + (d.findings.length
            ? '<ol class="notes">' + d.findings.map(f =>
                '<li><b>' + esc(f) + '</b></li>').join('') + '</ol>'
            : '')
        + (d.chart || '');
      out.innerHTML = lastCheck;
      controlKey = null;
      setTimeout(tick, 300);
    }
  } catch (e) {
    out.innerHTML = '<p class="err">Could not reach the local server.</p>';
  }
  btn.disabled = false; btn.textContent = label;
}

async function startSystem(btn, name) {
  const err = $('startErr');
  btn.disabled = true; err.hidden = true;
  try {
    const res = await fetch('/start-system', {method: 'POST', body: JSON.stringify({name})});
    const out = await res.json();
    if (out.error) {
      err.textContent = out.error; err.hidden = false; btn.disabled = false; return;
    }
    controlKey = null;
    setTimeout(tick, 400);
  } catch (e) {
    err.textContent = 'Could not reach the local server.'; err.hidden = false;
    btn.disabled = false;
  }
}

function render(d) {
  const out = $('out');
  renderControl(d.control || {}, d.present);

  if (!d.present) {
    const starting = (d.control || {}).running;
    $('what').textContent = starting ? 'starting' : 'nothing running';
    $('dot').className = starting ? 'dot' : 'dot idle';
    $('age').textContent = starting ? 'waiting for the first cycle' : 'idle';
    out.innerHTML = '<div class="card"><h2>No results yet</h2>'
      + '<p class="empty">' + esc(d.hint || '') + ' Start a run above, or point your '
      + 'own bot here by calling <code>proofmark.live.write_state()</code> at the '
      + 'end of each cycle.</p></div>';
    return;
  }

  $('what').innerHTML = '<span class="mode">' + esc(d.mode) + '</span>'
    + (d.label ? ' &nbsp;' + esc(d.label) : '')
    + (d.strategy ? ' &nbsp;&middot;&nbsp; ' + esc(d.strategy) : '');
  $('dot').className = 'dot' + (d.stale ? ' stale' : '');
  $('age').textContent = d.stale ? 'no heartbeat ' + ago(d.age) : 'updated ' + ago(d.age);

  let html = '';
  // Tucked means "you already have one going", so it has to follow whether a
  // run is actually going. Driving it off the presence of output put the label
  // "already running one" directly under a header reading "no heartbeat".
  const live = !!(d.control && d.control.running) && !d.stale;
  $('control').className = live ? 'tucked' : '';

  // Anything wrong goes above everything else. A person who opens this page
  // and scrolls past the problem to reach a chart has been failed by it.
  (d.alerts || []).forEach(a => {
    html += '<div class="banner warn"><h2>' + esc(a[0]) + '</h2><p>' + esc(a[1]) + '</p></div>';
  });
  (d.verdict || []).forEach(f => {
    html += '<div class="banner bad"><h2>' + esc(f.detail) + '</h2><p>' + esc(f.why) + '</p></div>';
  });

  if (d.headline) {
    // The sentence carries the verdict; the tiles are support. The clause
    // about holding is the one people skip, so it is the one in brass.
    const ahead = / ahead\.?$/.test(d.headline.trim());
    document.querySelector('.wrap').classList.toggle('needs-start', !!d.stale);
  const said = esc(d.headline).replace(
      /(so it is [^.]+)\./, '<b class="' + (ahead ? 'ahead' : 'behind') + '">$1.</b>');
    html += '<p class="verdictline' + (d.stale ? ' old' : '') + '">' + said + '</p>';
  }

  if (d.summary && d.summary.length) {
    html += '<div class="card"><dl class="figures">' + d.summary.map(row => {
      let cls = '';
      if (row[0] === 'Return' || row[0] === 'Difference' || row[0] === 'Holding') {
        cls = row[1].startsWith('-') ? ' class="down"' : ' class="up"';
      } else if (row[0] === 'Worst drop' && row[1] !== '0.0%') {
        cls = ' class="down"';
      }
      return '<div class="fig"><dt>' + esc(row[0]) + '</dt><dd' + cls + '>'
        + esc(row[1]) + '</dd></div>';
    }).join('') + '</dl></div>';
  }

  if (d.price) {
    html += '<div class="card"><h2>Price, and where the rules acted</h2>'
      + '<p class="cap">Green points up where it bought, red points down where it sold.</p>'
      + d.price + '</div>';
  }
  if (d.chart) {
    html += '<div class="card"><h2>Account value</h2>'
      + '<p class="cap">Solid is the strategy. Dashed is buying once and holding.</p>'
      + d.chart + '</div>';
  }
  if (d.underwater) {
    html += '<div class="card"><h2>Below the previous peak</h2>'
      + '<p class="cap">How far down it was at every moment, not just at the end.</p>'
      + d.underwater + '</div>';
  }

  if (d.positions && d.positions.length) {
    html += '<div class="card"><h2>Open</h2><table class="rows"><thead><tr>'
      + '<th>symbol</th><th class="n">quantity</th><th class="n">entry</th>'
      + '<th class="n">now</th><th class="n">unrealised</th><th>stop</th>'
      + '</tr></thead><tbody>' + d.positions.map(p =>
        '<tr><td>' + esc(p.symbol) + '</td>'
        + '<td class="n">' + p.quantity.toFixed(6) + '</td>'
        + '<td class="n">' + p.entry.toFixed(2) + '</td>'
        + '<td class="n">' + p.current.toFixed(2) + '</td>'
        + '<td class="n ' + (p.unrealised < 0 ? 'down' : 'up') + '">'
        + p.unrealised.toFixed(2) + '</td>'
        + '<td>' + (p.stop === null ? '<span class="flag">none</span>'
                                    : p.stop.toFixed(2)) + '</td></tr>').join('')
      + '</tbody></table></div>';
  }

  if (d.decisions && d.decisions.length) {
    html += '<div class="card"><h2>What it decided</h2><table class="rows"><thead><tr>'
      + '<th>when</th><th>action</th><th>why</th></tr></thead><tbody>'
      + d.decisions.map(x =>
        '<tr><td class="clock">' + esc(x.clock) + '</td>'
        + '<td class="act ' + esc(x.action) + '">' + esc(x.action) + '</td>'
        + '<td>' + esc(x.reason) + '</td></tr>').join('')
      + '</tbody></table></div>';
  } else {
    html += '<div class="card"><h2>What it decided</h2>'
      + '<p class="empty">No trades yet. A strategy that is sitting out is doing '
      + 'something, and this is where it will say so.</p></div>';
  }

  out.innerHTML = html;
}

async function tick() {
  try {
    render(await (await fetch('/state')).json());
  } catch (e) {
    $('dot').className = 'dot stale';
    $('age').textContent = 'lost the server';
  }
}

tick();
setInterval(tick, 5000);
</script>
"""
