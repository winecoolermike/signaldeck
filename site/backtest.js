// SignalDeck backtest page: renders backtest.json. No numbers are computed beyond formatting.
const D = "—";
const P = (x, d = 0) => x == null ? D : (x * 100).toFixed(d) + "%";
const R = x => x == null ? D : (x >= 0 ? "+" : "") + (x * 100).toFixed(2) + "%";
const few = f => f ? ' <span class="few">too few to trust</span>' : "";
function pv(p, worse) {
  if (p != null && p < 0.05) return `<span class="sig-good">p=${p < 0.001 ? "<0.001" : p.toFixed(3)}</span>`;
  if (worse != null && worse < 0.05) return `<span class="sig-bad">worse, p=${worse < 0.001 ? "<0.001" : worse.toFixed(3)}</span>`;
  return `<span class="muted">p=${p == null ? D : p.toFixed(2)}</span>`;
}
const cmp = (hit, base) => hit == null || base == null ? "" : hit > base ? "up" : hit < base ? "dn" : "";
function tabs(id, keys, labels, onpick, start) {
  const el = document.getElementById(id);
  el.innerHTML = keys.map((k, i) => `<button data-k="${k}">${labels[i]}</button>`).join("");
  const pick = k => { el.querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.k === k)); onpick(k); };
  el.querySelectorAll("button").forEach(b => b.onclick = () => pick(b.dataset.k)); pick(start);
}
const tkCell = t => `<td class="tkc">${t.ticker}${t.small_sample ? '<div class="few">small sample</div>' : ""}</td>`;

fetch("backtest.json", { cache: "no-store" }).then(r => r.json()).then(B => {
  const T = B.tickers.filter(t => t.status === "ok");
  document.getElementById("meta").innerHTML = `<span>Backtest run ${new Date(B.generated_at).toLocaleString("en-US", { timeZone: "America/Los_Angeles", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} PT</span><span class="sep"> · </span><span>signals ${T.find(t => !t.small_sample)?.daily.from || D} → ${T[0]?.daily.to || D}</span>`;
  document.getElementById("src").textContent = B.source;
  const S = B.summary;
  document.getElementById("summary").innerHTML = `<h2>Backtest: were the signals right?</h2>
    ${S.headline ? `<p class="lead">${S.headline}</p>` : ""}
    <ul>${S.per_ticker.map(l => `<li>${l}</li>`).join("")}</ul>
    ${(S.extra || []).map(l => `<p>${l}</p>`).join("")}
    <p class="warn">Past results don't predict future ones. One year, one market regime, a handful of related stocks.</p>`;

  tabs("tabs-daily", ["1", "5", "10"], ["1 day", "5 days", "10 days"], h => {
    document.getElementById("t-daily").innerHTML = `<tr><th>Ticker</th><th>CALL right<br><span>vs price rose</span></th><th>PUT right<br><span>vs price fell</span></th><th>All CALL/PUT<br><span>vs chance</span></th><th>Signif.<br><span>overlap-adj.</span></th><th>NEUT<br><span>days</span></th></tr>` +
      T.map(t => { const r = t.daily.horizons[h] || {}, c = r.CALL || {}, p = r.PUT || {}, d = r.directional || {};
        return `<tr>${tkCell(t)}
        <td><b class="${cmp(c.hit_rate, c.baseline)}">${P(c.hit_rate)}</b> <span class="muted">vs ${P(c.baseline)}</span><div class="n">n=${c.n ?? 0}${few(c.few)}</div></td>
        <td><b class="${cmp(p.hit_rate, p.baseline)}">${P(p.hit_rate)}</b> <span class="muted">vs ${P(p.baseline)}</span><div class="n">n=${p.n ?? 0}${few(p.few)}</div></td>
        <td><b class="${cmp(d.hit_rate, d.chance_same_mix)}">${P(d.hit_rate)}</b> <span class="muted">vs ${P(d.chance_same_mix)}</span><div class="n">n=${d.n ?? 0} · always-CALL ${P(d.always_call)}${few(d.few)}</div></td>
        <td>${pv(d.p_value, d.p_value_worse)}</td>
        <td>${(r.NEUT || {}).n ?? 0}</td></tr>`; }).join("");
    document.getElementById("t-ret").innerHTML = `<tr><th>Ticker</th><th>After CALL</th><th>After PUT</th><th>After NEUT</th><th>All days</th></tr>` +
      T.map(t => { const r = t.daily.horizons[h] || {};
        const c = b => `<td><b class="${(r[b]?.avg_ret ?? 0) >= 0 ? "up" : "dn"}">${R(r[b]?.avg_ret)}</b><div class="n">n=${r[b]?.n ?? 0}</div></td>`;
        return `<tr>${tkCell(t)}${c("CALL")}${c("PUT")}${c("NEUT")}<td>${R(r.avg_ret_all)}<div class="n">n=${r.n ?? 0}</div></td></tr>`; }).join("");
  }, "5");

  tabs("tabs-conf", ["1", "5", "10"], ["1 day", "5 days", "10 days"], h => {
    const names = B.params.buckets;
    document.getElementById("t-conf").innerHTML = `<tr><th>Ticker</th>${names.map(n => `<th>Conf ${n}</th>`).join("")}</tr>` +
      T.map(t => `<tr>${tkCell(t)}${(t.daily.horizons[h]?.conf_buckets || []).map(b => b.n ? `<td><b class="${cmp(b.hit_rate, b.chance_same_mix)}">${P(b.hit_rate)}</b> <span class="muted">vs ${P(b.chance_same_mix)}</span><div class="n">n=${b.n}${few(b.few)}</div></td>` : `<td class="muted">none</td>`).join("")}</tr>`).join("");
  }, "5");

  tabs("tabs-60", ["1", "4", "7"], ["1 bar", "4 bars", "7 bars"], h => {
    document.getElementById("t-60").innerHTML = `<tr><th>Ticker</th><th>CALL right<br><span>vs rose</span></th><th>PUT right<br><span>vs fell</span></th><th>All CALL/PUT<br><span>vs chance</span></th><th>Signif.<br><span>overlap-adj.</span></th></tr>` +
      T.map(t => { const H = t.h60; if (!H) return `<tr>${tkCell(t)}<td colspan="4" class="muted">no 60m data</td></tr>`;
        const r = H.horizons[h] || {}, c = r.CALL || {}, p = r.PUT || {}, d = r.directional || {};
        return `<tr><td class="tkc">${t.ticker}<div class="n">${H.from} →</div></td>
        <td><b class="${cmp(c.hit_rate, c.baseline)}">${P(c.hit_rate, 1)}</b> <span class="muted">vs ${P(c.baseline, 1)}</span><div class="n">n=${c.n ?? 0}</div></td>
        <td><b class="${cmp(p.hit_rate, p.baseline)}">${P(p.hit_rate, 1)}</b> <span class="muted">vs ${P(p.baseline, 1)}</span><div class="n">n=${p.n ?? 0}</div></td>
        <td><b class="${cmp(d.hit_rate, d.chance_same_mix)}">${P(d.hit_rate, 1)}</b> <span class="muted">vs ${P(d.chance_same_mix, 1)}</span><div class="n">n=${d.n ?? 0}${few(d.few)}</div></td>
        <td>${pv(d.p_value, d.p_value_worse)}</td></tr>`; }).join("");
  }, "4");
  document.getElementById("skipped").innerHTML = "<h3>Not backtested</h3><ul>" + Object.entries(B.skipped_timeframes).map(([k, v]) => `<li><b>${k}:</b> ${v}</li>`).join("") + "</ul>";

  const lv = x => !x || !x.n ? `<td class="muted">none</td>` :
    `<td><span class="up">${P(x.target_first_pct)}</span> / <span class="dn">${P(x.stop_first_pct)}</span> / <span class="muted">${P(x.neither_pct)}${x.same_day_both ? " · both " + P(x.same_day_both_pct) : ""}</span><div class="n">n=${x.n}${few(x.few)}</div></td>`;
  document.getElementById("t-lv").innerHTML = `<tr><th>Ticker</th><th>CALL days (long)<br><span>target / stop / neither</span></th><th>Long every day<br><span>baseline</span></th><th>PUT days (short)<br><span>target / stop / neither</span></th><th>Short every day<br><span>baseline</span></th></tr>` +
    T.map(t => { const L = t.daily.levels; return `<tr>${tkCell(t)}${lv(L.call_long)}${lv(L.baseline_long_every_day)}${lv(L.put_short)}${lv(L.baseline_short_every_day)}</tr>`; }).join("");

  const pr = B.params;
  document.getElementById("method").innerHTML = [
    `Signals come from the <b>same code</b> as the live dashboard (<code>signals.py</code>: EMA20/EMA50 cross, close vs SMA200, RSI(14), MACD(12,26,9) histogram, weights ${Object.entries(pr.indicator_weights).map(([k, v]) => k + " " + v).join(", ")}, bias threshold ±${pr.bias_threshold}).`,
    `<b>No lookahead:</b> for each day we recompute the signal using only bars up to that day's close — the same trailing window the live page fetches (2 years of daily bars; 730 days of 60m bars). Forward returns use later closes only.`,
    `Daily: the last ${pr.signal_days} trading days of signals; forward returns at ${pr.daily_horizons.join(" / ")} trading days (close to close). The most recent days have no 10-day outcome yet, so n shrinks with horizon.`,
    `60m: signals over the last ~${pr.h60_span_days} days; forward ${pr.h60_horizons.join(" / ")} bars. Regular session only.`,
    `<b>Baselines:</b> "price rose" = share of all scored days with a positive forward return (= always-CALL hit rate); "chance" = expected hit rate of random guessing with the same CALL/PUT mix. A useful signal should beat these.`,
    `<b>Significance:</b> one-sided exact binomial test of hits vs chance. Because 5- and 10-day windows overlap, we conservatively treat n/horizon trades as independent. Results with n &lt; ${pr.min_n} are marked "too few to trust". Many tests are shown, so an occasional p &lt; 0.05 is expected by luck alone.`,
    `Levels: the dashboard's MAIN Potential Exit (target) and Extended Entry (stop) from daily ATR(14) and 10/20-day swings, using the daily signal's direction (live uses the Total blend's direction). Requires a full 10-day window.`,
    `Prices are Yahoo Finance closes, split-adjusted but <b>not dividend-adjusted</b> (VZ and T pay sizable dividends, so ex-dividend drops count as down moves). No trading costs, spreads or option pricing are modelled — this measures direction only.`,
    `SPCX has only a few months of history: fewer than 200 daily bars, so its SMA200 vote never exists and its sample is small. Treat its numbers as anecdotes.`
  ].map(x => `<li>${x}</li>`).join("");
}).catch(e => { document.getElementById("summary").innerHTML = `<div class="nodata">Could not load backtest.json (${e}).</div>`; });
