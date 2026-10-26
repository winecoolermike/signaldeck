// SignalDeck scanner: renders data.json "scanner" (one row per universe ticker). Formatting only; nothing computed here.
(() => {
  const D = "—", $ = id => document.getElementById(id);
  const f = (x, d = 2) => x == null || Number.isNaN(x) ? D : Number(x).toFixed(d);
  const sg = (x, d = 2) => x == null ? D : (x >= 0 ? "+" : "") + Number(x).toFixed(d) + "%";
  fetch("data.json", { cache: "no-store" }).then(r => { if (!r.ok) throw new Error("data.json " + r.status); return r.json(); }).then(d => {
    const S = d.scanner;
    $("meta").innerHTML = `<span>Built ${new Date(d.generated_at).toLocaleString("en-US", { timeZone: "America/Los_Angeles", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} PT</span>`;
    $("src").textContent = d.source;
    if (!S || !S.rows) { $("sc-intro").textContent = "No scanner data in this build."; return; }
    const fire = S.rows.filter(r => r.fired);
    $("sc-intro").innerHTML = `Pullback setup (close &gt; SMA200 and RSI(2) &lt; 10) on the last completed daily close (${S.bar_date}). <b>Grade A</b> = also top ${S.top_n} of ${S.rank_of} ranked stocks by 12-1 month momentum at the ${S.rank_asof} month-end close; otherwise Grade B. Firing now: <b>${fire.length ? fire.map(r => `${r.ticker} (${r.grade})`).join(", ") : "none"}</b>. Firing setups are listed first, then by momentum rank. Dashboard tickers link to their card. <a href="./#how">How it works</a> · <a href="backtest.html#setups">Out-of-sample stats</a>`;
    const st = r => r.status === "insufficient_history" ? `<span class="pill na">n/a</span>`
      : r.fired ? `<span class="pill ${r.grade === "A" ? "ga" : "gb"}">Grade ${r.grade}</span>` : r.status === "ok" ? `<span class="pill none">none</span>` : `<span class="pill na">no data</span>`;
    const tk = r => r.dashboard ? `<a href="./#card-${r.ticker}">${r.ticker}</a>` : r.ticker;
    const head = `<div class="srow sh"><div>Ticker</div><div>Setup</div><div>Price</div><div>Mom. rank</div><div>vs SMA200</div><div>RSI(2)</div><div>ADX(14)</div></div>`;
    $("sc-list").innerHTML = head + S.rows.map(r => `<div class="srow${r.fired ? " fire" : ""}">
      <div class="c-tk"><b>${tk(r)}</b>${r.dashboard ? ' <span class="dash">dashboard</span>' : ""}${r.stale ? ' <span class="few">stale</span>' : ""}</div>
      <div class="c-st">${st(r)}</div>
      <div class="c-px">$${f(r.price)} <span class="${(r.change_pct || 0) >= 0 ? "up" : "dn"}">${sg(r.change_pct)}</span></div>
      <div class="c-m"><div class="c-rk"><span class="lab">Rank </span>${r.mom_rank == null ? `<span class="muted">unranked</span>` : `#${r.mom_rank}<span class="muted">/${r.rank_of}</span>${r.in_top ? " ✓" : ""}`}</div>
      <div class="c-ma"><span class="lab">SMA200 </span>${r.above_sma200 == null ? D : r.above_sma200 ? '<span class="up">above ✓</span>' : '<span class="dn">below ✗</span>'}</div>
      <div class="c-rsi"><span class="lab">RSI(2) </span><span class="${r.rsi2 != null && r.rsi2 < 10 ? "up" : ""}">${f(r.rsi2, 1)}</span></div>
      <div class="c-adx"><span class="lab">ADX </span>${f(r.adx, 1)}</div></div></div>`).join("");
    const stale = S.rows.filter(r => r.stale);
    $("sc-notes").innerHTML = `Price = latest Yahoo daily bar (may be mid-session, ~15 min delayed); setup columns use completed closes only. 12-1 momentum = close 21 trading days ago ÷ close 252 trading days ago − 1; stocks with under a year of history are unranked. ADX is information only. ${stale.length ? `Stale (kept from the last good build because this run could not refresh them): ${stale.map(r => r.ticker + (r.bar_date ? ` (${r.bar_date})` : "")).join(", ")}.` : "All 23 refreshed this build."} The rule and its research stats are frozen; the scheduled job only refreshes data.`;
  }).catch(e => { $("sc-intro").textContent = "Could not load data.json (" + e + ")."; });
})();
