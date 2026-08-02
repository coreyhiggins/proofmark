"""The live page: a status board, not a trading screen.

Same assay-report world as the report page, with one deliberate difference.
The report is something you read once. This is something you glance at, so it
answers four questions before anything else and shows nothing you could act
on impulsively.

    Is it running?      Is it halted?
    Is anything unprotected?      Has it drifted somewhere impossible?

There are no live prices, no order entry, and no buttons that place a trade.
A rules-based system exists so that nobody overrides it at the worst possible
moment, and a screen full of blinking prices is the most effective device ever
built for causing exactly that.
"""

LIVE_PAGE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>proofmark, live</title>
<style>
  :root {
    color-scheme: light dark;
    --paper:#fbf9f5; --ink:#1c1a17; --soft:#645e55; --rule:#ded7ca;
    --fatal:#8c2015; --warn:#6f4c05; --pass:#1c6339; --field:#fffdfa;
    --serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
    --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
    --sans:ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  }
  @media (prefers-color-scheme: dark) {
    :root { --paper:#14161a; --ink:#e8e6e1; --soft:#a19c93; --rule:#2d3239;
            --fatal:#ff9083; --warn:#e0af52; --pass:#68d391; --field:#1a1d22; }
  }
  *,*::before,*::after { box-sizing:border-box; }
  body { margin:0; background:var(--paper); color:var(--ink); font:17px/1.65 var(--serif);
         -webkit-font-smoothing:antialiased; }
  .sheet { max-width:41rem; margin:0 auto; padding:3.5rem 1.75rem 6rem; }

  .masthead { display:flex; justify-content:space-between; align-items:baseline;
              gap:1rem; flex-wrap:wrap; border-bottom:2px solid var(--ink); padding-bottom:.8rem; }
  .masthead h1 { margin:0; font:600 1.35rem/1.1 var(--sans); letter-spacing:.15em; text-transform:uppercase; }
  .pulse { font:11px/1 var(--sans); letter-spacing:.12em; text-transform:uppercase; color:var(--soft);
           display:flex; align-items:center; gap:.5rem; }
  .dot { width:7px; height:7px; border-radius:50%; background:var(--pass); }
  .dot.stale { background:var(--fatal); }
  @media (prefers-reduced-motion:no-preference) {
    .dot { animation:breathe 2.4s ease-in-out infinite; }
    @keyframes breathe { 50% { opacity:.35 } }
  }

  .mode { font:11px/1 var(--sans); letter-spacing:.12em; text-transform:uppercase;
          color:var(--soft); padding:.7rem 0 1.3rem; border-bottom:1px solid var(--rule); }
  .mode b { color:var(--fatal); }

  h2 { font:11px/1.4 var(--sans); letter-spacing:.13em; text-transform:uppercase; color:var(--soft);
       border-bottom:1px solid var(--ink); padding-bottom:.7rem; margin:3rem 0 0; }

  ol.alerts { list-style:none; margin:1.6rem 0 0; padding:0; counter-reset:n; }
  ol.alerts li { counter-increment:n; position:relative; padding:0 0 1.3rem 2.7rem;
                 margin-bottom:1.3rem; border-bottom:1px solid var(--rule); }
  ol.alerts li:last-child { border-bottom:0; margin-bottom:0; }
  ol.alerts li::before { content:counter(n); position:absolute; left:0; top:.2rem;
                         font:11px/1 var(--mono); color:var(--soft); }
  ol.alerts .tag { display:block; font:600 10px/1 var(--sans); letter-spacing:.14em;
                   text-transform:uppercase; margin-bottom:.4rem; color:var(--fatal); }
  ol.alerts p { margin:0; font-size:.99rem; }
  .allclear { margin:1.6rem 0 0; color:var(--soft); }

  table { width:100%; border-collapse:collapse; margin-top:1.2rem; }
  th { text-align:left; font:10px/1 var(--sans); letter-spacing:.12em; text-transform:uppercase;
       color:var(--soft); padding:0 0 .5rem; font-weight:600; }
  th:not(:first-child), td:not(:first-child) { text-align:right; }
  td { padding:.55rem 0; border-bottom:1px solid var(--rule); font-size:.95rem;
       font-family:var(--mono); font-variant-numeric:tabular-nums; }
  td:first-child { font-family:var(--serif); }
  td.up { color:var(--pass); } td.down { color:var(--fatal); }
  td.nostop { color:var(--fatal); }
  .empty { color:var(--soft); font-style:italic; padding:1rem 0; }

  ul.log { list-style:none; margin:1.2rem 0 0; padding:0; }
  ul.log li { display:flex; gap:.8rem; padding:.5rem 0; border-bottom:1px solid var(--rule);
              font-size:.93rem; align-items:baseline; }
  ul.log time { font:11px/1.6 var(--mono); color:var(--soft); flex:0 0 4.2rem; }
  ul.log .sym { font:600 11px/1.6 var(--sans); letter-spacing:.06em; flex:0 0 4.5rem; }
  ul.log .why { color:var(--soft); }
  ul.log .act-reject .sym { color:var(--soft); }

  svg.chart { display:block; width:100%; margin-top:1.2rem; overflow:visible; }
  svg.chart .subject { fill:none; stroke:var(--ink); stroke-width:1.6; vector-effect:non-scaling-stroke; }
  svg.chart .bench { fill:none; stroke:var(--soft); stroke-width:1.2; stroke-dasharray:4 3; }
  svg.chart .zero { stroke:var(--rule); stroke-width:1; }
  svg.chart .underwater { fill:var(--fatal); fill-opacity:.16; stroke:var(--fatal); stroke-width:1.2; }
  .chart-caption { margin:.5rem 0 0; font:11px/1.5 var(--sans); color:var(--soft);
                   font-variant-numeric:tabular-nums; }

  .seal { margin-top:4rem; padding-top:1.3rem; border-top:1px solid var(--rule);
          font-size:.88rem; color:var(--soft); }
  .seal a { color:inherit; }
  @media (max-width:34rem) { .sheet { padding:2.5rem 1.25rem 4rem; } body { font-size:16px; } }
</style>
<div class="sheet">
  <header class="masthead">
    <h1>Proofmark, live</h1>
    <span class="pulse"><span class="dot" id="dot"></span><span id="age">connecting</span></span>
  </header>
  <p class="mode" id="mode"></p>

  <div id="body"><p class="empty">Waiting for the first update.</p></div>

  <p class="seal">Reads a state file your bot writes. It holds no keys, places no
  orders, and shows no prices you could trade on. If something here needs acting
  on, act on it in your bot, not on this page.</p>
</div>
<script>
const esc = s => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const money = n => (n >= 0 ? '+' : '') + n.toFixed(2);

function ago(seconds) {
  if (seconds < 60) return Math.round(seconds) + 's ago';
  if (seconds < 3600) return Math.round(seconds / 60) + 'm ago';
  return Math.round(seconds / 3600) + 'h ago';
}

async function tick() {
  let d;
  try {
    d = await (await fetch('/state')).json();
  } catch {
    document.getElementById('age').textContent = 'server unreachable';
    document.getElementById('dot').className = 'dot stale';
    return;
  }

  const dot = document.getElementById('dot');
  const age = document.getElementById('age');

  if (!d.present) {
    dot.className = 'dot stale';
    age.textContent = 'no state file';
    document.getElementById('mode').textContent = '';
    document.getElementById('body').innerHTML =
      '<p class="empty">' + esc(d.hint || 'Nothing is writing a state file yet.') + '</p>';
    return;
  }

  dot.className = d.stale ? 'dot stale' : 'dot';
  age.textContent = ago(d.age);
  document.getElementById('mode').innerHTML = d.mode === 'live'
    ? 'Trading <b>real money</b>'
    : 'Paper trading';

  let html = '';

  html += '<h2>Attention</h2>';
  html += d.alerts.length
    ? '<ol class="alerts">' + d.alerts.map(a =>
        '<li><span class="tag">' + esc(a[0]) + '</span><p>' + esc(a[1]) + '</p></li>').join('') + '</ol>'
    : '<p class="allclear">Nothing needs you. Running, writing, and every open position has a stop.</p>';

  if (d.verdict && d.verdict.length) {
    html += '<h2>The live results look wrong</h2><ol class="alerts">'
      + d.verdict.map(f => '<li><span class="tag">' + esc(f.severity)
        + '</span><p><b>' + esc(f.detail) + '</b><br>' + esc(f.why) + '</p></li>').join('')
      + '</ol>';
  }

  html += '<h2>Open positions</h2>';
  html += d.positions.length
    ? '<table><tr><th>Symbol</th><th>Qty</th><th>Entry</th><th>Now</th><th>Open P/L</th><th>Stop</th></tr>'
      + d.positions.map(p =>
        '<tr><td>' + esc(p.symbol) + '</td><td>' + p.quantity + '</td><td>' + p.entry.toFixed(2)
        + '</td><td>' + p.current.toFixed(2) + '</td><td class="' + (p.unrealised >= 0 ? 'up' : 'down')
        + '">' + money(p.unrealised) + '</td><td class="' + (p.stop === null ? 'nostop' : '') + '">'
        + (p.stop === null ? 'none' : p.stop.toFixed(2)) + '</td></tr>').join('')
      + '</table>'
    : '<p class="empty">Flat. No open positions.</p>';

  if (d.chart) html += '<h2>Account value</h2>' + d.chart;

  html += '<h2>What the rules decided</h2>';
  html += d.decisions.length
    ? '<ul class="log">' + d.decisions.map(x =>
        '<li class="act-' + esc(x.action) + '"><time>' + esc(x.clock) + '</time>'
        + '<span class="sym">' + esc(x.symbol) + '</span>'
        + '<span class="why">' + esc(x.action) + ', ' + esc(x.reason) + '</span></li>').join('') + '</ul>'
    : '<p class="empty">Nothing recorded yet. A bot that records why it declined is the only kind you can tell apart from a broken one.</p>';

  document.getElementById('body').innerHTML = html;
}

tick();
setInterval(tick, 5000);
</script>
"""
