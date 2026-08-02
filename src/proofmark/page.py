"""The page.

REWRITTEN after the first real look at it. The previous version was an assay
report in the literal sense: cream paper, hairline rules, small-caps labels,
six numbered sections stacked before anything could happen. Elegant to read
about, a wall to actually use, and the owner's word for it was "bland".

What changed, and why:

- **One thing to do.** A single large box asks for the account balance. Every
  other input moved behind a disclosure, because a person who has never seen
  this should not have to answer six questions before finding out whether it
  is useful.
- **A sample button.** "How do I test this" should be answerable inside the
  product, not in a README. One click fills a real losing strategy and runs.
- **Warmth.** Brass on warm charcoal, which is what a proof mark struck into
  metal actually looks like. The old palette had colour only on failure, so
  the resting state was grey text on cream.
- **The result leads with the picture.** Charts moved above the findings. The
  equity line against buy-and-hold is the most immediately legible thing this
  produces and it was at the bottom.

What deliberately did not change: the verdict still says "not safe to report"
in plain words, findings still explain themselves, and undefined values are
still shown as undefined rather than dressed up as zero.
"""

PAGE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>proofmark</title>
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
      --bg:#FAF7F1; --panel:#FFFFFF; --raised:#F2ECE1;
      --ink:#191512; --soft:#5D5449; --faint:#8B8172;
      --line:#E2D9C9; --brass:#96701A; --brass-dim:#D9C68F;
      --pass:#1B7A46; --fail:#A32A18; --warn:#7A5A08;
    }
  }
  *,*::before,*::after { box-sizing:border-box; }
  body {
    margin:0; background:var(--bg); color:var(--ink);
    font:16px/1.6 var(--sans); -webkit-font-smoothing:antialiased;
  }
  .wrap { max-width:52rem; margin:0 auto; padding:3rem 1.5rem 6rem; }

  /* ---------------------------------------------------------- masthead -- */
  .top { display:flex; align-items:center; gap:.85rem; margin-bottom:2.6rem; }
  .stamp { width:38px; height:38px; flex:0 0 38px; }
  .top h1 { margin:0; font:600 1.05rem/1 var(--sans); letter-spacing:.2em; text-transform:uppercase; }
  .top p { margin:.25rem 0 0; font-size:.86rem; color:var(--soft); }

  /* ------------------------------------------------------------- hero -- */
  .hero { font:1.55rem/1.35 var(--serif); letter-spacing:-.01em; margin:0 0 .7rem; }
  .hero b { color:var(--brass); font-weight:inherit; }
  .sub { margin:0 0 2.2rem; color:var(--soft); font-size:1rem; max-width:34rem; }

  .card { background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:1.5rem; }
  .card + .card { margin-top:1rem; }

  label.lbl { display:block; font:600 .82rem/1.4 var(--sans); margin-bottom:.15rem; }
  .hint { margin:0 0 .8rem; font-size:.84rem; color:var(--soft); }

  textarea, input[type=number] {
    width:100%; padding:.85rem .9rem; color:var(--ink); background:var(--bg);
    border:1px solid var(--line); border-radius:9px;
    font:13px/1.7 var(--mono); font-variant-numeric:tabular-nums;
  }
  textarea { min-height:9.5rem; resize:vertical; display:block; }
  textarea::placeholder, input::placeholder { color:var(--faint); }
  textarea:focus, input:focus-visible { outline:2px solid var(--brass); outline-offset:2px; border-color:transparent; }

  details.more { margin-top:1rem; }
  details.more > summary {
    cursor:pointer; list-style:none; font:600 .84rem/1 var(--sans); color:var(--brass);
    padding:.85rem 0; display:flex; align-items:center; gap:.5rem;
  }
  details.more > summary::-webkit-details-marker { display:none; }
  details.more > summary::before {
    content:"+"; font:400 1.05rem/1 var(--mono); color:var(--brass);
  }
  details.more[open] > summary::before { content:"\\2212"; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(12rem,1fr)); gap:1.1rem; }

  .choices { display:flex; gap:.5rem; flex-wrap:wrap; margin-top:.5rem; }
  .choices label {
    cursor:pointer; font-size:.88rem; padding:.5rem .85rem; border-radius:999px;
    border:1px solid var(--line); background:var(--bg); color:var(--soft);
    display:flex; align-items:center; gap:.4rem;
  }
  .choices input { accent-color:var(--brass); margin:0; }
  .choices label:has(input:checked) { border-color:var(--brass); color:var(--ink); }

  .actions { display:flex; gap:.8rem; align-items:center; flex-wrap:wrap; margin-top:1.6rem; }
  button.go {
    font:600 .92rem/1 var(--sans); padding:.95rem 1.9rem; border:0; border-radius:10px;
    background:var(--brass); color:#17130B; cursor:pointer;
    transition:transform .12s ease, filter .12s ease;
  }
  button.go:hover:not(:disabled) { filter:brightness(1.08); }
  button.go:active:not(:disabled) { transform:translateY(1px); }
  button.go:disabled { opacity:.45; cursor:default; }
  button.ghost {
    font:.88rem/1 var(--sans); padding:.9rem 1.1rem; border:1px solid var(--line);
    border-radius:10px; background:transparent; color:var(--soft); cursor:pointer;
  }
  button.ghost:hover { color:var(--ink); border-color:var(--brass-dim); }

  /* ----------------------------------------------------------- result -- */
  #out { margin-top:2.8rem; }
  #out:empty { margin-top:0; }

  .verdict { border-radius:14px; padding:1.7rem 1.6rem; border:1px solid var(--line); background:var(--panel); }
  .verdict.bad { border-color:var(--fail); background:color-mix(in srgb, var(--fail) 9%, var(--panel)); }
  .verdict.good { border-color:var(--pass); background:color-mix(in srgb, var(--pass) 9%, var(--panel)); }
  .verdict h2 { margin:0 0 .4rem; font:600 1.45rem/1.25 var(--serif); letter-spacing:-.01em; }
  .verdict.bad h2 { color:var(--fail); }
  .verdict.good h2 { color:var(--pass); }
  .verdict p { margin:0; color:var(--soft); font-size:.97rem; }

  .plate { margin-top:1rem; }
  .plate h3 { margin:0 0 .1rem; font:600 .82rem/1.4 var(--sans); }
  .plate .cap { margin:0; font-size:.83rem; color:var(--soft); }
  svg.chart { display:block; width:100%; margin-top:.9rem; overflow:visible; }
  svg.chart .subject { fill:none; stroke:var(--brass); stroke-width:2; vector-effect:non-scaling-stroke; stroke-linejoin:round; }
  svg.chart .bench { fill:none; stroke:var(--soft); stroke-width:1.3; stroke-dasharray:4 4; vector-effect:non-scaling-stroke; }
  svg.chart .zero { stroke:var(--line); stroke-width:1; vector-effect:non-scaling-stroke; }
  svg.chart .underwater { fill:var(--fail); fill-opacity:.18; stroke:var(--fail); stroke-width:1.4; vector-effect:non-scaling-stroke; }
  svg.chart .oos { fill:var(--brass); opacity:.07; }
  .chart-caption { margin:.6rem 0 0; font:.82rem/1.5 var(--sans); color:var(--soft); font-variant-numeric:tabular-nums; }

  ol.notes { list-style:none; margin:0; padding:0; }
  ol.notes li { padding:1.05rem 0; border-bottom:1px solid var(--line); }
  ol.notes li:last-child { border-bottom:0; padding-bottom:0; }
  ol.notes .tag {
    display:inline-block; font:600 .68rem/1 var(--sans); letter-spacing:.1em; text-transform:uppercase;
    padding:.34rem .6rem; border-radius:6px; margin-bottom:.55rem;
  }
  ol.notes .fatal .tag { color:var(--fail); background:color-mix(in srgb, var(--fail) 15%, transparent); }
  ol.notes .warn .tag { color:var(--warn); background:color-mix(in srgb, var(--warn) 15%, transparent); }
  ol.notes b { display:block; font-weight:600; margin-bottom:.25rem; font-size:.98rem; }
  ol.notes p { margin:0; color:var(--soft); font-size:.92rem; }

  .figures { display:grid; grid-template-columns:repeat(auto-fit,minmax(8.5rem,1fr)); gap:.7rem; margin-top:1rem; }
  .fig { background:var(--raised); border-radius:10px; padding:.85rem .95rem; }
  .fig dt { font:.75rem/1.3 var(--sans); color:var(--soft); margin-bottom:.25rem; }
  .fig dd { margin:0; font:600 1.15rem/1.2 var(--mono); font-variant-numeric:tabular-nums; }
  .fig dd.none { color:var(--faint); font:italic 400 .95rem/1.4 var(--sans); }

  .err { color:var(--fail); }
  .foot { margin-top:3rem; font-size:.85rem; color:var(--faint); line-height:1.7; }
  @media (max-width:36rem) { .wrap { padding:2rem 1.1rem 4rem; } .hero { font-size:1.32rem; } }
  @media (prefers-reduced-motion:no-preference) {
    #out > * { animation:rise .4s cubic-bezier(.2,.7,.3,1) both; }
    #out > *:nth-child(2) { animation-delay:.05s; }
    #out > *:nth-child(3) { animation-delay:.1s; }
    @keyframes rise { from { opacity:0; transform:translateY(8px); } }
  }
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
      <p>Checks whether a trading result is safe to believe</p>
    </div>
  </header>

  <p class="hero">Most backtests look better than the strategy. <b>This tells you when yours does.</b></p>
  <p class="sub">Paste what your account was worth over time. Everything runs on this
  machine, and nothing you enter is uploaded or stored.</p>

  <div class="card">
    <label class="lbl" for="equity">Account value over time</label>
    <p class="hint">One number per line, or a pasted column. Your balance at every
      step, not only when a trade closed.</p>
    <textarea id="equity" placeholder="10000&#10;10120&#10;9980&#10;10240&#10;10190"></textarea>

    <details class="more">
      <summary>Add trades, a benchmark and how many versions you tried</summary>
      <div style="padding-top:.4rem">
        <div class="grid">
          <div>
            <label class="lbl" for="pnls">Result of each trade</label>
            <p class="hint">Negative for losers.</p>
            <textarea id="pnls" style="min-height:7rem" placeholder="120&#10;-45&#10;260"></textarea>
          </div>
          <div>
            <label class="lbl" for="benchmark">What holding would have done</label>
            <p class="hint">Same account, buy once, do nothing.</p>
            <textarea id="benchmark" style="min-height:7rem" placeholder="10000&#10;10080&#10;10210"></textarea>
          </div>
        </div>

        <div class="grid" style="margin-top:1.1rem">
          <div>
            <label class="lbl" for="trials">Versions tried</label>
            <p class="hint">Every parameter tweak counts as one.</p>
            <input id="trials" type="number" min="1" value="1">
          </div>
          <div>
            <label class="lbl" for="costs">Fees and slippage paid</label>
            <p class="hint">Blank if none were modelled.</p>
            <input id="costs" type="number" step="any" placeholder="84.20">
          </div>
        </div>

        <div style="margin-top:1.2rem">
          <label class="lbl">Did the data include assets that no longer exist?</label>
          <div class="choices">
            <label><input type="radio" name="delisted" value="yes"> Yes</label>
            <label><input type="radio" name="delisted" value="no"> Only what still trades</label>
            <label><input type="radio" name="delisted" value="unknown" checked> Not sure</label>
          </div>
        </div>
      </div>
    </details>

    <div class="actions">
      <button class="go" id="go">Examine</button>
      <button class="ghost" id="sample">Try it with a sample</button>
    </div>
  </div>

  <div id="out" aria-live="polite"></div>

  <p class="foot">Passing every check does not mean a strategy works. It means the
  obvious ways of fooling yourself have been ruled out. This is not investment advice.</p>
</div>
<script>
const nums = s => (s.match(/-?\\d+(?:\\.\\d+)?(?:[eE][-+]?\\d+)?/g) || []).map(Number);
const esc = s => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const $ = id => document.getElementById(id);

$('sample').onclick = () => {
  // A real losing crossover against a rising market. Chosen because the honest
  // shape is more useful than a flattering one: this is what most strategies
  // look like once a benchmark is drawn next to them.
  const eq = [10000], bh = [10000];
  for (let i = 0; i < 260; i++) {
    eq.push(eq[eq.length - 1] * ((Math.floor(i / 22) % 3) ? 1.0031 : 0.9885));
    bh.push(bh[bh.length - 1] * 1.0022);
  }
  $('equity').value = eq.map(v => v.toFixed(2)).join('\\n');
  $('benchmark').value = bh.map(v => v.toFixed(2)).join('\\n');
  $('pnls').value = Array.from({length: 44}, (_, i) => (i % 3 ? '58' : '-41')).join('\\n');
  $('trials').value = '60';
  $('costs').value = '0';
  document.querySelector('input[value=no]').checked = true;
  document.querySelector('details.more').open = true;
  $('go').click();
};

$('go').onclick = async () => {
  const btn = $('go'), out = $('out');
  btn.disabled = true; out.innerHTML = '';
  const body = {
    equity: nums($('equity').value),
    pnls: nums($('pnls').value),
    benchmark: nums($('benchmark').value),
    trials: Number($('trials').value) || 1,
    costs: $('costs').value === '' ? null : Number($('costs').value),
    delisted: document.querySelector('input[name=delisted]:checked').value
  };
  try {
    const res = await fetch('/check', {method: 'POST', body: JSON.stringify(body)});
    render(await res.json());
  } catch (e) {
    out.innerHTML = '<p class="err">Could not reach the local server. Is it still running?</p>';
  }
  btn.disabled = false;
};

function render(d) {
  const out = $('out');
  if (d.error) { out.innerHTML = '<p class="err">' + esc(d.error) + '</p>'; return; }
  const bad = !d.reportable;

  let html = '<div class="verdict ' + (bad ? 'bad' : 'good') + '"><h2>'
    + (bad ? 'These numbers are not safe to believe.' : 'Nothing obviously wrong.')
    + '</h2><p>'
    + (bad ? 'At least one result here is not possible for a real strategy. Find the cause before reading anything else.'
           : 'The usual ways a backtest misleads you were checked and did not fire. That is not the same as the strategy working.')
    + '</p></div>';

  // Picture first. The line against buy-and-hold is the most legible thing
  // this produces, and it used to be at the bottom of the page.
  if (d.charts && d.charts.equity) {
    html += '<div class="card plate"><h3>Account value</h3>'
      + '<p class="cap">Solid is your strategy. Dashed is buying once and holding.</p>'
      + d.charts.equity + '</div>';
  }
  if (d.charts && d.charts.underwater) {
    html += '<div class="card plate"><h3>Below the previous peak</h3>'
      + '<p class="cap">How far down you were at every moment, not just at the end.</p>'
      + d.charts.underwater + '</div>';
  }

  if (d.findings.length) {
    html += '<div class="card"><h3 style="margin:0 0 .6rem;font:600 .82rem/1.4 var(--sans)">What stood out</h3>'
      + '<ol class="notes">' + d.findings.map(f =>
        '<li class="' + f.severity + '"><span class="tag">'
        + (f.severity === 'fatal' ? 'Disqualifying' : 'Worth knowing') + '</span>'
        + '<b>' + esc(f.detail) + '</b><p>' + esc(f.why) + '</p></li>').join('')
      + '</ol></div>';
  }

  html += '<div class="card"><h3 style="margin:0 0 .2rem;font:600 .82rem/1.4 var(--sans)">The numbers</h3>'
    + '<dl class="figures">' + d.metrics.map(row =>
      '<div class="fig"><dt>' + esc(row[0]) + '</dt><dd'
      + (row[1] === 'undefined' ? ' class="none"' : '') + '>' + esc(row[1]) + '</dd></div>').join('')
    + '</dl></div>';

  out.innerHTML = html;
  out.scrollIntoView({behavior: 'smooth', block: 'start'});
}
</script>
"""
