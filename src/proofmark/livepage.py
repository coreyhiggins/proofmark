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
    font:16px/1.6 var(--sans); -webkit-font-smoothing:antialiased;
  }
  .wrap { max-width:47rem; margin:0 auto; padding:2.4rem 1.5rem 5rem; }

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
    margin:0 0 .15rem; font:600 .82rem/1.4 var(--sans);
  }
  .card p.cap { margin:0 0 .2rem; font-size:.82rem; color:var(--soft); }

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

  .figures { display:grid; grid-template-columns:repeat(auto-fit,minmax(7.5rem,1fr)); gap:.7rem; }
  .fig { background:var(--raised); border-radius:10px; padding:.85rem .95rem; }
  .fig dt { font:.75rem/1.3 var(--sans); color:var(--soft); margin-bottom:.25rem; }
  .fig dd { margin:0; font:600 1.12rem/1.2 var(--mono); font-variant-numeric:tabular-nums; }
  .fig dd.up { color:var(--pass); }
  .fig dd.down { color:var(--fail); }

  svg.chart { display:block; width:100%; margin-top:.9rem; overflow:visible; }
  svg.chart .grid { stroke:var(--line); stroke-width:1; }
  svg.chart .base { stroke:var(--soft); stroke-width:1; stroke-dasharray:2 3; opacity:.7; }
  svg.chart .tick { fill:var(--faint); font:11px var(--mono); font-variant-numeric:tabular-nums; }
  svg.chart .tick-base { fill:var(--soft); }
  svg.chart .tag { font:600 11px var(--sans); letter-spacing:.03em; }
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

  .chart-caption { margin:.6rem 0 0; font:.82rem/1.5 var(--sans); color:var(--soft);
                   font-variant-numeric:tabular-nums; }

  ol.notes { list-style:none; margin:0; padding:0; }
  ol.notes li { padding:.9rem 0; border-bottom:1px solid var(--line); }
  ol.notes li:last-child { border-bottom:0; padding-bottom:0; }
  ol.notes b { display:block; font-weight:600; margin-bottom:.2rem; font-size:.95rem; }
  ol.notes p { margin:0; color:var(--soft); font-size:.88rem; }

  table.rows { width:100%; border-collapse:collapse; font:500 .84rem/1.5 var(--sans);
               font-variant-numeric:tabular-nums; }
  table.rows th { text-align:left; font:600 .68rem/1.4 var(--sans); letter-spacing:.09em;
                  text-transform:uppercase; color:var(--faint); padding:0 .55rem .5rem;
                  border-bottom:1px solid var(--line); }
  table.rows td { padding:.5rem .55rem; border-bottom:1px solid var(--line); }
  table.rows tr:last-child td { border-bottom:0; }
  table.rows .n { text-align:right; }
  table.rows .up { color:var(--pass); }
  table.rows .down { color:var(--fail); }
  table.rows .flag { color:var(--warn); font-weight:600; }
  .clock { color:var(--faint); font-family:var(--mono); font-size:.78rem; }
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

  .empty { color:var(--soft); font-size:.88rem; margin:0; }
  .empty code { font:500 .82em/1 var(--mono); background:var(--raised);
                padding:.15em .4em; border-radius:4px; }
  .foot { margin-top:2.4rem; font-size:.82rem; color:var(--faint); line-height:1.7; }
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
      <h1>Live</h1>
      <p id="what">connecting</p>
    </div>
    <nav class="nav">
      <a href="/">Check a result</a>
      <span class="here">Watch a live run</span>
    </nav>
  </header>
  <div class="pulse"><span class="dot" id="dot"></span><span id="age">&nbsp;</span></div>

  <div id="control"></div>
  <div id="out" aria-live="polite"></div>

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

function renderControl(c, hasRun) {
  const key = JSON.stringify([c.running, c.canStart, c.error, hasRun]);
  if (key === controlKey) return;
  controlKey = key;

  const s = c.settings || {};
  const box = $('control');

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
    return;
  }

  const options = (c.strategies || []).map(x =>
    '<option value="' + esc(x.name) + '"' + (x.name === 'ema-cross' ? ' selected' : '')
    + '>' + esc(x.name) + '</option>').join('');

  box.innerHTML = '<div class="card"><h2>' + (hasRun ? 'Start another run' : 'Start a paper run')
    + '</h2><p class="cap">Real prices, imaginary money. No key that could place '
    + 'an order is ever used, and there is no setting here that changes that.</p>'
    + '<div class="fields">'
    + '<div><label class="lbl" for="symbol">Symbol</label>'
    + '<input id="symbol" value="' + esc(s.symbol || 'BTC/USDT') + '"></div>'
    + '<div><label class="lbl" for="venue">Exchange</label>'
    + '<select id="venue"><option value="okx">okx</option>'
    + '<option value="bitget">bitget</option></select></div>'
    + '<div><label class="lbl" for="timeframe">Bar size</label>'
    + '<select id="timeframe"><option value="15m">15m</option>'
    + '<option value="1h" selected>1h</option><option value="4h">4h</option>'
    + '<option value="1d">1d</option></select></div>'
    + '<div><label class="lbl" for="strategy">Rules</label>'
    + '<select id="strategy">' + options + '</select></div>'
    + '<div><label class="lbl" for="cash">Starting balance</label>'
    + '<input id="cash" value="10000"></div>'
    + '</div>'
    + '<p class="hint">Fees of 0.1% and slippage of 0.05% come off both sides of '
    + 'every fill. Decisions are made on a closed bar and filled at the next bar\\'s '
    + 'open, so nothing trades on a price it has already seen.</p>'
    + '<div class="actions"><button class="go" id="start">Start</button></div>'
    + '<p class="err" id="startErr" hidden></p></div>';

  $('start').onclick = async () => {
    const btn = $('start'), err = $('startErr');
    btn.disabled = true; err.hidden = true;
    try {
      const res = await fetch('/run', {method: 'POST', body: JSON.stringify({
        symbol: $('symbol').value, venue: $('venue').value,
        timeframe: $('timeframe').value, strategy: $('strategy').value,
        cash: Number($('cash').value)
      })});
      const out = await res.json();
      if (out.error) { err.textContent = out.error; err.hidden = false; btn.disabled = false; return; }
      controlKey = null;
      setTimeout(tick, 400);
    } catch (e) {
      err.textContent = 'Could not reach the local server.'; err.hidden = false;
      btn.disabled = false;
    }
  };
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

  // Anything wrong goes above everything else. A person who opens this page
  // and scrolls past the problem to reach a chart has been failed by it.
  (d.alerts || []).forEach(a => {
    html += '<div class="banner warn"><h2>' + esc(a[0]) + '</h2><p>' + esc(a[1]) + '</p></div>';
  });
  (d.verdict || []).forEach(f => {
    html += '<div class="banner bad"><h2>' + esc(f.detail) + '</h2><p>' + esc(f.why) + '</p></div>';
  });

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
