// SignalDeck backtest page, "Setups" section: renders setups.json (frozen research stats). Formatting only.
(() => {
  const D = "—", pc = (x, d = 1) => x == null ? D : (x * 100).toFixed(d) + "%";
  const sg = (x, d = 2) => x == null ? D : (x >= 0 ? "+" : "") + Number(x).toFixed(d) + "%";
  const pv = p => p == null ? D : p < 0.0001 ? p.toExponential(0) : p.toFixed(4);
  const few = n => n < 30 ? ' <span class="few">too few to trust</span>' : "";
  const $ = id => document.getElementById(id);
  fetch("setups.json", { cache: "no-store" }).then(r => r.json()).then(S => {
    const R = S.research, [a, b] = R.test, N = R.tickers.all23.length;
    $("su-intro").innerHTML = `Rules were tuned on ${R.train[0]} → ${R.train[1]} and scored only on <b>${a} → ${b}</b> (out of sample) across ${N} stocks: the 7 dashboard tickers plus ${R.tickers.broad16.join(", ")}. Real Yahoo daily bars (split- and dividend-adjusted), entry at the signal day's close, one position per ticker, ${(R.cost_per_side * 100).toFixed(2)}% cost per side. ${R.variants_tested} candidate rules were tested, so significance uses a Bonferroni threshold of p &lt; ${R.bonferroni_alpha.toFixed(4)}. These numbers are frozen; the daily job does not re-tune them.`;
    $("su-warn").innerHTML = `<b>Read this first.</b> Not evidence for buying options: these are stock moves after costs; option premium, spreads and time decay are ignored and can easily erase a ~0.3–0.5% average move. Losses ran bigger than wins (the high hit rate comes partly from an exit that takes small bounces and holds losers up to 10 days). Out-of-sample years were mostly a rising market. Past results don't predict future ones.`;
    const V = S.versions, sets = [["all23", `All ${N}`], ["broad16", "Broad 16"], ["core7", "Dashboard 7"]];
    $("su-versions").innerHTML = `<tr><th>Version</th><th>Set</th><th>Trades<br><span>per ticker/yr</span></th><th>Right<br><span>vs random, same exit</span></th><th>p</th><th>Net / trade<br><span>vs random</span></th><th>Avg win / loss</th><th>Profit factor</th><th>Hold</th><th>Portfolio max DD</th></tr>` +
      [["grade_a", "Grade A: close &gt; SMA200, RSI(2) &lt; 10, ADX(14) &gt; 25"], ["all", "All: close &gt; SMA200, RSI(2) &lt; 10"]].map(([k, lab]) => sets.map(([s, sl], i) => {
        const m = V[k].test[s];
        return `<tr>${i === 0 ? `<td rowspan="3" class="tkc" style="white-space:normal;max-width:220px">${lab}</td>` : ""}<td>${sl}</td><td>${m.n}${few(m.n)}<div class="n">${m.trades_per_ticker_year}</div></td>
        <td><b class="${m.hit > m.same_exit_random_hit ? "up" : "dn"}">${pc(m.hit)}</b> <span class="muted">vs ${pc(m.same_exit_random_hit)}</span></td><td>${pv(m.p_hit_vs_same_exit)}</td>
        <td><b class="${m.exp_net_pct > 0 ? "up" : "dn"}">${sg(m.exp_net_pct)}</b> <span class="muted">vs ${sg(m.same_exit_random_exp_net_pct)}</span></td>
        <td>${sg(m.avg_win_net)} / ${sg(m.avg_loss_net)}</td><td>${m.profit_factor_net ?? D}</td><td>${m.avg_hold_days}d</td><td>${m.port_maxdd_pct}%</td></tr>`; }).join("")).join("");
    const y = k => Object.entries(V[k].test_by_year).map(([yr, v]) => `${yr} ${pc(v.hit)} (${sg(v.exp_net_pct)}, n=${v.n})`).join(" · ");
    const bh = R.buy_hold.all23.test, cl = V.all.date_clustered.all23 || {};
    $("su-years").innerHTML = `By year (all ${N}) — All: ${y("all")}. Grade A: ${y("grade_a")}. Next-day-open entry instead of close: ${pc(V.all.next_open_entry.hit)}, ${sg(V.all.next_open_entry.exp_net_pct)}/trade. Grouping same-day trades: t = ${cl.t_dates_ret}; monthly block bootstrap p = ${cl.boot_p_excess_le0} (not below the Bonferroni threshold, so treat the edge as likely but not proven). For scale, buying and holding all ${N} returned ${bh.cagr_pct}%/yr (max DD ${bh.maxdd_pct}%) vs ${V.all.test.all23.port_cagr_net_pct}%/yr for the setup, which is in the market only a small fraction of the time.`;
    $("su-rule").innerHTML = `Survived = ${R.survival_rule}. "Baseline" is random entries with the same exit (or the same holding period for fixed-hold rules).`;
    const vr = S.variants.slice().sort((x, y) => (y.survived - x.survived) || (y.exp_net_pct - x.exp_net_pct));
    $("su-variants").innerHTML = `<tr><th>Rule</th><th>Verdict</th><th>Trades</th><th>Right vs baseline</th><th>p</th><th>Net / trade</th><th>Dashboard 7<br><span>right · net · n</span></th></tr>` +
      vr.concat(S.variants_60m).map(v => `<tr><td class="tkc">${v.name}<div class="n">${v.family}</div></td><td class="${v.survived ? "ok" : "no"}">${v.survived ? "✓ survived" : "✗ " + v.verdict}</td>
        <td>${v.n}</td><td>${pc(v.hit)}${v.baseline_hit != null ? ` <span class="muted">vs ${pc(v.baseline_hit)}</span>` : ""}</td><td>${pv(v.p)}</td>
        <td class="${v.exp_net_pct > 0 ? "up" : "dn"}">${sg(v.exp_net_pct)}</td><td>${pc(v.core7_hit)} · ${sg(v.core7_exp_net_pct)} · ${v.core7_n}${few(v.core7_n)}</td></tr>`).join("");
    const pb = S.ladder.filter(l => !l.level.startsWith("current")), mx = pb.reduce((m, l) => l.hit > m.hit ? l : m, pb[0]);
    $("su-ladder-note").innerHTML = `Pre-declared selectivity ladder (fixed before testing). Out-of-sample hit rate stayed between ${pc(Math.min(...pb.map(l => l.hit)))} and ${pc(mx.hit)} at every level, while net per trade rose from ${sg(pb[0].exp_net_pct)} to ${sg(pb[pb.length - 1].exp_net_pct)}: being pickier raised profit per trade, not the hit rate. Best level: ${mx.level} (${mx.n} trades).`;
    $("su-ladder").innerHTML = `<tr><th>Level</th><th>Train hit<br><span>${R.train[0].slice(0, 4)}–${R.train[1].slice(2, 4)}</span></th><th>OOS trades<br><span>per ticker/yr</span></th><th>OOS right</th><th>OOS net / trade</th><th>Dashboard 7 OOS right</th></tr>` +
      S.ladder.map(l => `<tr><td class="tkc">${l.level}<div class="n">${l.kind}</div></td><td>${pc(l.train_hit)} <span class="muted">n=${l.train_n}</span></td><td>${l.n}<div class="n">${l.trades_per_ticker_year}</div></td>
        <td><b>${pc(l.hit)}</b></td><td class="${l.exp_net_pct > 0 ? "up" : "dn"}">${sg(l.exp_net_pct)}</td><td>${pc(l.core7_hit)} <span class="muted">n=${l.core7_n}</span>${few(l.core7_n)}</td></tr>`).join("");
  }).catch(e => { $("su-intro").textContent = "Could not load setups.json (" + e + ")."; });
})();
