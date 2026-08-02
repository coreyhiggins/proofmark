"""The page, kept apart from the server so each file does one thing.

The visual world is an assay report: a document from a testing house, not a
dashboard. That choice is load-bearing rather than decorative. A dashboard
implies monitoring, and monitoring implies the numbers are real. A report
implies a finding, which is what this actually produces, and a finding can be
negative.

So: a masthead rule, roman-numeraled sections, a determination set as a
sentence rather than a status pill, and numbered notes that read like a
surveyor's remarks. Figures are tabular-numeral monospace so columns line up
the way a printed table does. Undefined values are set in italic grey, because
an absent measurement should look absent rather than look like zero.
"""

PAGE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>proofmark</title>
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
    :root {
      --paper:#14161a; --ink:#e8e6e1; --soft:#a19c93; --rule:#2d3239;
      --fatal:#ff9083; --warn:#e0af52; --pass:#68d391; --field:#1a1d22;
    }
  }
  *,*::before,*::after { box-sizing:border-box; }
  body {
    margin:0; background:var(--paper); color:var(--ink);
    font:17px/1.65 var(--serif);
    -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility;
  }
  .sheet { max-width:41rem; margin:0 auto; padding:4.5rem 1.75rem 7rem; }

  .masthead { border-bottom:2px solid var(--ink); padding-bottom:.8rem; }
  .masthead h1 {
    margin:0; font:600 1.55rem/1.1 var(--sans);
    letter-spacing:.15em; text-transform:uppercase;
  }
  .colophon {
    display:flex; justify-content:space-between; gap:1rem; flex-wrap:wrap;
    font:11px/1.6 var(--sans); letter-spacing:.11em; text-transform:uppercase;
    color:var(--soft); padding:.7rem 0 1.4rem; border-bottom:1px solid var(--rule);
  }
  .lede { margin:2.6rem 0 3.2rem; font-size:1.14rem; }

  .legend {
    font:11px/1.4 var(--sans); letter-spacing:.13em; text-transform:uppercase;
    color:var(--soft); margin:0 0 .3rem;
  }
  .field { margin-bottom:2.4rem; }
  .field > p.help { margin:0 0 .7rem; font-size:.93rem; color:var(--soft); }
  textarea, input[type=number] {
    width:100%; padding:.7rem .8rem; color:var(--ink); background:var(--field);
    border:1px solid var(--rule); border-radius:2px;
    font:13px/1.6 var(--mono); font-variant-numeric:tabular-nums;
  }
  textarea { min-height:8.5rem; resize:vertical; display:block; }
  textarea:focus, input:focus-visible {
    outline:2px solid var(--ink); outline-offset:1px; border-color:transparent;
  }
  .pair { display:flex; gap:1.6rem; flex-wrap:wrap; }
  .pair > .field { flex:1 1 13rem; }

  .choices { display:flex; gap:1.4rem; flex-wrap:wrap; margin-top:.5rem; }
  .choices label { display:flex; gap:.45rem; align-items:baseline; font-size:.95rem; cursor:pointer; }

  button {
    font:600 12px/1 var(--sans); letter-spacing:.16em; text-transform:uppercase;
    padding:1rem 2.2rem; border:1px solid var(--ink); border-radius:2px;
    background:var(--ink); color:var(--paper); cursor:pointer;
    transition:background .15s, color .15s;
  }
  button:hover:not(:disabled) { background:transparent; color:var(--ink); }
  button:disabled { opacity:.4; cursor:default; }

  #out { margin-top:4.5rem; }
  #out:empty { margin-top:0; }
  .sectionmark {
    font:11px/1 var(--sans); letter-spacing:.13em; text-transform:uppercase;
    color:var(--soft); padding-bottom:.7rem; border-bottom:1px solid var(--rule);
  }
  .determination { margin:1.9rem 0 2.8rem; }
  .determination h2 { margin:0 0 .5rem; font-size:1.6rem; font-weight:600; line-height:1.25; letter-spacing:-.012em; }
  .determination.bad h2 { color:var(--fatal); }
  .determination.good h2 { color:var(--pass); }
  .determination p { margin:0; color:var(--soft); font-size:1.01rem; }

  ol.notes { list-style:none; margin:0; padding:0; counter-reset:n; }
  ol.notes li {
    counter-increment:n; position:relative; padding:0 0 1.5rem 2.7rem;
    margin-bottom:1.5rem; border-bottom:1px solid var(--rule);
  }
  ol.notes li:last-child { border-bottom:0; margin-bottom:0; }
  ol.notes li::before {
    content:counter(n); position:absolute; left:0; top:.2rem;
    font:11px/1 var(--mono); color:var(--soft);
  }
  ol.notes .tag {
    display:block; font:600 10px/1 var(--sans); letter-spacing:.14em;
    text-transform:uppercase; margin-bottom:.45rem;
  }
  ol.notes .fatal .tag { color:var(--fatal); }
  ol.notes .warn .tag { color:var(--warn); }
  ol.notes b { display:block; font-weight:600; margin-bottom:.3rem; }
  ol.notes p { margin:0; color:var(--soft); font-size:.96rem; }

  table { width:100%; border-collapse:collapse; margin-top:3.2rem; }
  caption {
    text-align:left; font:11px/1 var(--sans); letter-spacing:.13em;
    text-transform:uppercase; color:var(--soft);
    padding-bottom:.7rem; border-bottom:1px solid var(--ink);
  }
  td { padding:.62rem 0; border-bottom:1px solid var(--rule); font-size:.97rem; }
  td:last-child { text-align:right; font-family:var(--mono); font-variant-numeric:tabular-nums; }
  td.none { color:var(--soft); font-style:italic; }
  .err { color:var(--fatal); }

  .seal { margin-top:4.5rem; padding-top:1.4rem; border-top:1px solid var(--rule);
          font-size:.9rem; color:var(--soft); }

  @media (max-width:34rem) { .sheet { padding:3rem 1.25rem 5rem; } body { font-size:16px; } }
  @media (prefers-reduced-motion:no-preference) {
    #out > * { animation:rise .45s cubic-bezier(.2,.7,.3,1) both; }
    @keyframes rise { from { opacity:0; transform:translateY(6px); } }
  }
</style>
<div class="sheet">
  <header class="masthead"><h1>Proofmark</h1></header>
  <div class="colophon">
    <span>Verification of a trading result</span>
    <span id="stamp"></span>
  </div>

  <p class="lede">A proof mark is the stamp struck into metal certifying it
  survived testing. The stamp means something only because the test could fail.
  Enter what your strategy did, and this will tell you whether the numbers are
  safe to believe.</p>

  <div class="field">
    <p class="legend">I &nbsp; Account value over time</p>
    <p class="help">One number per line, or a pasted column. Your balance at every
      step, not only when a trade closed.</p>
    <label class="legend" for="equity" hidden>Account value over time</label>
    <textarea id="equity" placeholder="10000&#10;10120&#10;9980&#10;10240"></textarea>
  </div>

  <div class="field">
    <p class="legend">II &nbsp; Result of each trade <span style="text-transform:none;letter-spacing:0">(optional)</span></p>
    <p class="help">Negative numbers for losers. Used for win rate and profit factor.</p>
    <textarea id="pnls" placeholder="120&#10;-45&#10;260&#10;-30"></textarea>
  </div>

  <div class="pair">
    <div class="field">
      <p class="legend"><label for="trials">III &nbsp; Versions tried</label></p>
      <p class="help">Every parameter tweak counts as one.</p>
      <input id="trials" type="number" min="1" value="1">
    </div>
    <div class="field">
      <p class="legend"><label for="costs">IV &nbsp; Fees and slippage paid</label></p>
      <p class="help">Leave blank if none were modelled.</p>
      <input id="costs" type="number" step="any" placeholder="84.20">
    </div>
  </div>

  <div class="field">
    <p class="legend">V &nbsp; Did the data include assets that no longer exist?</p>
    <div class="choices">
      <label><input type="radio" name="delisted" value="yes"> Yes</label>
      <label><input type="radio" name="delisted" value="no"> No, only what still trades</label>
      <label><input type="radio" name="delisted" value="unknown" checked> Not sure</label>
    </div>
  </div>

  <button id="go">Examine</button>
  <div id="out" aria-live="polite"></div>

  <p class="seal">Runs entirely on this machine. Nothing entered here is uploaded,
  stored, or sent anywhere. Passing every check does not mean a strategy works.
  It means the obvious ways of fooling yourself have been ruled out.</p>
</div>
<script>
document.getElementById('stamp').textContent =
  new Date().toLocaleDateString(undefined, {year:'numeric', month:'long', day:'numeric'});

const nums = s => (s.match(/-?\\d+(?:\\.\\d+)?(?:[eE][-+]?\\d+)?/g) || []).map(Number);
const esc = s => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

document.getElementById('go').onclick = async () => {
  const btn = document.getElementById('go');
  const out = document.getElementById('out');
  btn.disabled = true;
  out.innerHTML = '';

  const body = {
    equity: nums(document.getElementById('equity').value),
    pnls: nums(document.getElementById('pnls').value),
    trials: Number(document.getElementById('trials').value) || 1,
    costs: document.getElementById('costs').value === ''
      ? null : Number(document.getElementById('costs').value),
    delisted: document.querySelector('input[name=delisted]:checked').value
  };

  try {
    const res = await fetch('/check', {method:'POST', body:JSON.stringify(body)});
    render(await res.json());
  } catch (e) {
    out.innerHTML = '<p class="err">Could not reach the local server. Is it still running?</p>';
  }
  btn.disabled = false;
};

function render(d) {
  const out = document.getElementById('out');
  if (d.error) { out.innerHTML = '<p class="err">' + esc(d.error) + '</p>'; return; }

  const bad = !d.reportable;
  let html = '<p class="sectionmark">Determination</p>'
    + '<div class="determination ' + (bad ? 'bad' : 'good') + '">'
    + '<h2>' + (bad ? 'These numbers are not safe to report.'
                    : 'Nothing obviously wrong.') + '</h2><p>'
    + (bad ? 'At least one result below is not possible for a real strategy. Find the cause before reading anything else on this page.'
           : 'The usual ways a backtest misleads you were checked and did not fire. That is not the same as the strategy working.')
    + '</p></div>';

  if (d.findings.length) {
    html += '<ol class="notes">' + d.findings.map(function (f) {
      return '<li class="' + f.severity + '"><span class="tag">'
        + (f.severity === 'fatal' ? 'Disqualifying' : 'Noted')
        + '</span><b>' + esc(f.detail) + '</b><p>' + esc(f.why) + '</p></li>';
    }).join('') + '</ol>';
  }

  html += '<table><caption>Measurements</caption><tbody>' + d.metrics.map(function (row) {
    const undef = row[1] === 'undefined';
    return '<tr><td>' + esc(row[0]) + '</td><td' + (undef ? ' class="none"' : '')
      + '>' + esc(row[1]) + '</td></tr>';
  }).join('') + '</tbody></table>';

  out.innerHTML = html;
  out.scrollIntoView({behavior:'smooth', block:'start'});
}
</script>
"""
