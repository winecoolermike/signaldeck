// SignalDeck front-end: renders data.json. No data is computed or invented here.
const D = "—";
const f = (x, d = 2) => (x === null || x === undefined || Number.isNaN(x)) ? D : Number(x).toFixed(d);
const big = n => n == null ? D : n >= 1e12 ? (n / 1e12).toFixed(2) + "T" : n >= 1e9 ? (n / 1e9).toFixed(1) + "B" : (n / 1e6).toFixed(0) + "M";
const cls = b => b === "CALL" ? "call" : b === "PUT" ? "put" : "neut";
const TABS = [
  ["0", x => true, "nearest"], ["1W", x => x.dte >= 4 && x.dte <= 10], ["3D", x => x.dte <= 3],
  ["7D", x => x.dte <= 7], ["21D", x => x.dte >= 8 && x.dte <= 21], ["30D", x => x.dte >= 22 && x.dte <= 35]];
const fmtTs = iso => { if (!iso) return D; const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) + " ET"; };
const pct = (v, c) => (v == null || !c) ? "" : ` (${((v / c - 1) * 100).toFixed(1)}%)`;

const etTime = (iso, ref) => { if (!iso) return D; const d = new Date(iso), o = { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: false };
  const day = x => new Date(x).toLocaleDateString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric" });
  return (ref && day(ref) === day(iso) ? "" : day(iso) + " ") + d.toLocaleTimeString("en-US", o) + " ET"; };
// Round-3 rows (15m EMA9/21 state, 5m/1m close vs session VWAP): +1/-1 states, no CALL/PUT, no buy/sell meaning.
function stateCell(k, s) {
  if (s.status === "waiting") return [`<td class="neut">waiting for first bar</td>`, ""];
  if (s.status !== "ok") return [`<td class="neut">${D}</td>`, ""];
  const c = s.score > 0 ? "call" : s.score < 0 ? "put" : "neut", sc = s.score > 0 ? "+1" : s.score < 0 ? "−1" : "0";
  if (s.kind === "ema9_21") {
    const txt = s.state === "Flat" ? "Flat (EMA9 = EMA21)" : `${s.state} (EMA9 ${s.score > 0 ? "&gt;" : "&lt;"} EMA21)`;
    return [`<td class="${c} st2">${txt}<div class="since">since ${s.since_is_lower_bound ? "≤ " : ""}${etTime(s.since, new Date().toISOString())}</div></td>`, sc];
  }
  const txt = s.state === "At" ? "At VWAP" : `${s.state} VWAP`;
  const sub = (k === "5m" ? `${s.dist_pct >= 0 ? "+" : ""}${f(s.dist_pct)}% vs VWAP ${f(s.vwap)}` : `VWAP ${f(s.vwap)}`) +
    (s.live_session ? "" : ` · ${new Date(s.session + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })} session`);
  return [`<td class="${c} st2">${txt}<div class="since">${sub}</div></td>`, sc];
}
function sigRows(t) {
  const keys = t.config_tfs.map(x => [x.key, x.label]).concat([["Total", "Total"]]);
  return keys.map(([k, lab]) => { const s = t.signals[k] || {};
    const tr = c => `<tr class="${k === "Total" ? "total" : k === "Main" ? "main" : ""}"><td>${lab}:</td>${c}</tr>`;
    if (s.kind) { const [cell, sc] = stateCell(k, s); return tr(`${cell}<td class="adx" title="state score used in Total">${sc}</td>`); }
    return tr(`<td class="${cls(s.bias)}">${s.bias || D} (${s.confidence == null ? D : s.confidence + "%"})</td>
      <td class="adx" title="ADX(14)=${f(s.adx, 1)}">${k === "Total" ? "" : (s.adx_label || D)}</td>`); }).join("");
}

function optBox(o, side, exp, isBest) {
  if (!o) return `<div class="opt ${side}"><div class="ty ${side === "c" ? "call" : "put"}">${side === "c" ? "CALL" : "PUT"} · ${exp.expiry} · ${exp.dte}DTE</div><div class="x">No eligible OTM quote (bid/ask/OI) — ${D}</div></div>`;
  return `<div class="opt ${side}">${isBest ? '<span class="best">TIGHTEST</span>' : ""}
    <div class="ty ${side === "c" ? "call" : "put"}">${side === "c" ? "CALL" : "PUT"} STRK · OTM #${o.otm_rank}</div>
    <div class="s ${side === "c" ? "call" : "put"}">$${f(o.strike, o.strike % 1 ? 1 : 0)}</div>
    <div class="x">${new Date(exp.expiry + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })} · ${exp.dte}DTE</div>
    <div class="q">BID ${f(o.bid)} · ASK ${f(o.ask)} · LAST ${f(o.last)}</div>
    <div class="x">Vol ${o.volume ?? D} · OI ${o.oi ?? D} · Spread ${o.rel_spread == null ? D : (o.rel_spread * 100).toFixed(1) + "%"} · IV ${o.iv == null ? D : (o.iv * 100).toFixed(0) + "%"}</div></div>`;
}

function renderOpts(t, tab, el) {
  const all = (t.options && t.options.expiries) || [];
  const [name, fn] = TABS.find(x => x[0] === tab);
  let ex = name === "0" ? all.slice(0, 1) : all.filter(fn);
  ex = ex.slice(0, 3);
  if (!ex.length) { el.innerHTML = `<div class="empty">No listed expiries in this window (≤35 DTE scanned).</div>`; return; }
  const sp = side => ex.map(e => e[side]).filter(Boolean).sort((a, b) => a.rel_spread - b.rel_spread)[0];
  const bc = sp("call"), bp = sp("put");
  el.innerHTML = ex.map(e => `<div class="ogrid">${optBox(e.call, "c", e, e.call && e.call === bc)}${optBox(e.put, "p", e, e.put && e.put === bp)}</div>`).join("");
}


// ---- Pullback setup (rule frozen in signals.py; OOS stats from setups.json, derived from the research files) ----
const pc = (x, d = 0) => x == null ? D : (x * 100).toFixed(d) + "%";
const sg = (x, d = 2) => x == null ? D : (x >= 0 ? "+" : "") + Number(x).toFixed(d) + "%";
const tooFew = n => n < 30 ? ' <span class="few">too few to trust</span>' : "";
function currentRuleLine(SU) {
  const c = SU && SU.current_rule_oos && SU.current_rule_oos.all23;
  if (!c) return `<div class="sig-oos">Describes the trend so far. <a href="backtest.html">Backtest →</a></div>`;
  const [a, b] = SU.research.test;
  return `<div class="sig-oos">Describes the trend so far; does not predict the rest of the day. Main row out of sample ${a.slice(0, 4)}–${b.slice(2, 4)}: right ${pc(c.hit)} vs ${pc(c.chance, 1)} chance (5-day, ${SU.research.tickers.all23.length} stocks, n=${c.n.toLocaleString()}). <a href="index.html#how-rows">Why these indicators</a> · <a href="backtest.html">Backtest →</a></div>`;
}
const rankTxt = s => s.mom_rank == null ? `unranked <span class="muted">(needs 12 months of history)</span>`
  : `#${s.mom_rank} of ${s.mom_rank_of}`;
const rankLine = s => `momentum rank ${rankTxt(s)}${s.mom_asof ? ` <span class="muted">(12-1 mo, ${s.mom_asof} close)</span>` : ""}`;
function riskLines(s, SU) {
  const R = SU && (SU.live ? SU.live.risk : SU.risk); if (!R) return "";
  const ap = R.stop.all_pullbacks, ga = R.stop.grade_a, z = R.sizing;
  const g = s.grade === "A" ? ga : null;
  return `<div class="why"><b>Optional disaster stop</b> (not part of the rule): 3×ATR(14) below the close = <b>${f(s.stop_3atr)}</b>. Out of sample it cut the worst trade from ${sg(ap.no_stop.test.worst_trade_pct, 1)} to ${sg(ap.stop.test.worst_trade_pct, 1)} (train ${sg(ap.no_stop.train.worst_trade_pct, 1)} → ${sg(ap.stop.train.worst_trade_pct, 1)}) but lowered net/trade from ${sg(ap.no_stop.test.exp_net_pct)} to ${sg(ap.stop.test.exp_net_pct)}${g ? `. For Grade A trades: net ${sg(g.no_stop.test.exp_net_pct)} → ${sg(g.stop.test.exp_net_pct)}, worst ${sg(g.no_stop.test.worst_trade_pct, 1)} → ${sg(g.stop.test.worst_trade_pct, 1)} out of sample (train ${sg(g.no_stop.train.worst_trade_pct, 1)} → ${sg(g.stop.train.worst_trade_pct, 1)})` : ""}.</div>
    <div class="why"><b>Size hint:</b> losing trades averaged ${sg((g ? g.no_stop : ap.no_stop).test.avg_loss_pct, 1)}, the worst ${sg((g ? g.no_stop : ap.no_stop).test.worst_trade_pct, 1)} out of sample (${sg(ap.no_stop.train.worst_trade_pct, 1)} in training): size so a loss that size is affordable. ATR-scaled weight ${z.label.replace("weight = ", "")} = <b>${f(s.size_mult)}×</b> here (ATR ${f(s.atr_pct)}% of price); in research it changed net/trade ${sg(z.no_sizing.test.exp_net_pct)} → ${sg(z.atr_sizing.test.exp_net_pct)} and the worst trade ${sg(z.no_sizing.test.worst_trade_pct, 1)} → ${sg(z.atr_sizing.test.worst_trade_pct, 1)}.</div>`;
}
function setupBlock(t, SU) {
  const s = t.setup;
  const stale = s && s.stale ? ` <span class="few">stale: ${s.stale_reason || "data not refreshed"}</span>` : "";
  if (!s || s.status === "error" || s.status === "no_data") return `<div class="setup off">No pullback setup · status unavailable${s && s.reason ? " (" + s.reason + ")" : ""}</div>`;
  if (s.status === "insufficient_history")
    return `<div class="setup off">No pullback setup · not enough history for SMA200 (${s.bars} of 200 daily bars) · RSI(2) ${f(s.rsi2, 1)} · ${rankLine(s)}${stale}</div>`;
  if (!s.fired)
    return `<div class="setup off">No pullback setup · RSI(2) ${f(s.rsi2, 1)} <span class="muted">(needs &lt; 10)</span> · close ${f(s.close)} ${s.above_sma200 ? "above" : "below"} SMA200 ${f(s.sma200)} ${s.above_sma200 ? "✓" : "✗"} · ${rankLine(s)} ${s.in_top ? "✓ top 10 → would be Grade A" : "→ would be Grade B"}${s.last_fired ? ` · last fired ${s.last_fired}` : ""} · <span class="muted">close ${s.bar_date}</span>${stale}</div>`;
  const L = SU && SU.live, T = s.ticker_stats || {};
  const row = (lab, v, me) => { if (!v) return ""; const a = v.test;
    return `<tr${me ? ' class="me"' : ""}><td>${lab}</td><td>${a.n}</td><td><b>${pc(a.hit, 1)}</b> <span class="muted">vs ${pc(a.same_exit_random_hit, 1)}</span></td><td>${sg(a.exp_net_pct)}</td><td>${sg(a.avg_win_net)} / ${sg(a.avg_loss_net)}</td><td>${sg(a.worst_trade_pct, 1)}</td></tr>`; };
  const own = (lab, x) => !x || !x.n ? `<div>${lab}: no trades yet${tooFew(0)}</div>` :
    `<div>${lab}: ${x.n} trades, right ${pc(x.hit)} vs ${pc(T.random_same_exit && T.random_same_exit.hit)} random same-exit, ${sg(x.exp_net_pct)}/trade${tooFew(x.n)}</div>`;
  const c7 = L && L.all.core7, a7 = L && L.grade_a.core7;
  return `<div class="setup on">
    <div class="sh"><span class="sbadge">SETUP: Pullback${s.grade === "A" ? " · Grade A" : " · Grade B"}</span><span class="muted">long only · close ${s.bar_date}</span>${stale}</div>
    <div class="why">Close ${f(s.close)} &gt; SMA200 ${f(s.sma200)} · RSI(2) ${f(s.rsi2, 1)} &lt; 10 · ADX(14) ${f(s.adx, 1)} <span class="muted">(info only)</span></div>
    <div class="why"><b>Rank:</b> ${rankLine(s)} in the scan universe → ${s.grade === "A" ? "top 10 → <b>Grade A</b>" : "not top 10 → Grade B"}. <a href="scanner.html">Scanner →</a></div>
    <div class="why"><b>Exit rule:</b> first daily close above SMA(5) (now ${f(s.sma5)}), or after 10 trading days.</div>
    ${riskLines(s, SU)}
    ${L ? `<div class="tablewrap"><table class="st"><tr><th>Out-of-sample ${L.test[0].slice(0, 4)}–${L.test[1].slice(2, 4)}, ${L.n_universe} stocks</th><th>Trades</th><th>Right vs random same exit</th><th>Net/trade</th><th>Avg win / avg loss</th><th>Worst</th></tr>
      ${row("Grade A (top-10 momentum)", L.grade_a, s.grade === "A")}${row("All pullbacks", L.all, s.grade !== "A")}</table></div>` : `<div class="muted">Research stats unavailable (setups.json not loaded).</div>`}
    <div class="own"><b>${t.ticker} itself</b> (${T.window ? T.window[0] + " → " + T.window[1] : D}):${own("All", T.all)}${own("Grade A", T.grade_a)}</div>
    ${c7 ? `<div class="warnline">On the 7 This Week tickers combined there was no reliable edge out of sample: all pullbacks right ${pc(c7.hit)} vs ${pc(c7.same_exit_random_hit)} random, ${sg(c7.exp_net_pct)}/trade (n=${c7.n})${a7 ? `; Grade A ${pc(a7.hit)} vs ${pc(a7.same_exit_random_hit)}, ${sg(a7.exp_net_pct)}/trade (n=${a7.n}, not significant)` : ""}.</div>` : ""}
    <div class="warnline">Losses ran bigger than wins. Stock moves after 0.05%/side costs — not evidence for buying options. Past results don't predict. <a href="backtest.html#setups">Details →</a></div>
  </div>`;
}

// ---- How section: row-indicator evidence, rendered from setups.json (round 3), never typed by hand ----
function rowsEvidence(SU) {
  const el = document.getElementById("rows-evidence"); const R = SU && SU.round3; if (!el || !R) return;
  const nm = { "S1 score bias (current)": "4-vote score (CALL/PUT)", "S2 close vs VWAP": "Close vs session VWAP", "S4 EMA9 vs EMA21": "EMA9 vs EMA21",
    "S3 VWAP + EMA9 slope": "VWAP + EMA9 slope", "S5 EMA20 vs EMA50": "EMA20 vs EMA50", "S6 close vs session open": "Close vs session open" };
  const rows = Object.entries(R.rows).map(([iv, r]) => { const ch = r.test[r.chosen], cu = r.test[r.current], same = r.chosen === r.current;
    return `<tr><td>${iv}</td><td><b>${nm[r.chosen] || r.chosen}</b></td><td>${pc(ch.agree_session_to_date, 1)}${same ? "" : ` <span class="muted">vs ${pc(cu.agree_session_to_date, 1)}</span>`}</td>
      <td>${ch.flips_per_session}${same ? "" : ` <span class="muted">vs ${cu.flips_per_session}</span>`}</td><td>${pc(ch.rest_hit, 1)} <span class="muted">vs ${pc(ch.rest_base, 1)}</span></td><td>${ch.n_days}</td></tr>`; }).join("");
  const T0 = R.total.T0, T1 = R.total.T1, I = R.intraday_rules;
  el.innerHTML = `<div class="tablewrap"><table class="rules"><tr><th>Row</th><th>Indicator</th><th>Matches day's move so far<br><span class="muted">vs old score</span></th><th>Flips / session<br><span class="muted">vs old score</span></th><th>Rest of day right<br><span class="muted">vs base rate</span></th><th>Test sessions</th></tr>${rows}</table></div>
  <p class="muted">Total of all rows, ${T1.n_days} test sessions: matches the day's move so far ${pc(T0.std_hit, 1)} with the old rows → ${pc(T1.std_hit, 1)} with these (base ${pc(T1.std_base, 1)}); rest-of-day direction ${pc(T1.rest_hit, 1)} vs ${pc(T1.rest_base, 1)} base (t = ${T1.rest_t}) — i.e. <b>no forecast value</b>. ${I.n_rules} intraday buy/sell rules (VWAP, EMA9, opening-range) were also tested: ${I.survivors.length} survived and ${I.n_net_positive} made money after ${I.round_trip_cost_pct}% round-trip costs (best ${sg(I.best_net_pct, 3)}/trade), so the rows carry no buy/sell badges or alerts.</p>`;
}

function card(t, cfg, SU) {
  const el = document.createElement("article"); el.className = "card"; el.id = "card-" + t.ticker;
  if (t.status !== "ok") { el.innerHTML = `<div class="nodata"><div class="tk">${t.ticker}</div><p>No data available</p><div class="sub">${(t.notes || []).join("<br>")}</div></div>`; return el; }
  t.config_tfs = cfg.timeframes;
  const p = t.price, L = t.levels || {}, q = t.quality || {}, c = L.ref_close;
  const chCls = (p.change || 0) >= 0 ? "up" : "dn", sign = (p.change || 0) >= 0 ? "+" : "";
  const qColor = q.score >= 75 ? "var(--green)" : q.score >= 55 ? "#84cc16" : q.score >= 30 ? "var(--amber)" : "var(--red)";
  const dl = t.daily_label || D, dCls = dl.includes("CALL") ? "call" : dl.includes("PUT") ? "put" : "neut";
  el.innerHTML = `${t.stale ? `<div class="stalebar">Stale: this card could not be refreshed this run; showing the previous build's values.</div>` : ""}
  <div class="l">
    <div class="hdr"><div class="badge">${t.ticker.slice(0, 2)}</div>
      <div><div class="tk">${t.ticker}</div><div class="nm">${t.name || D}</div><div class="nm">${t.exchange || ""}</div></div>
      <div class="px"><div class="p">$${f(p.last)}</div>
        <div class="chg ${chCls}">${sign}${f(p.change)} (${sign}${f(p.change_pct)}%)</div>
        <div class="ts">Close ${fmtTs(p.as_of)} · post ${f(p.post_market)}</div></div></div>
    <div class="stats">
      <div class="stat"><b>MKT CAP</b><span>${big(t.market_cap)}</span></div>
      <div class="stat"><b>ATR14</b><span>${f(L.atr14)}</span></div>
      <div class="stat"><b>PREV H</b><span>${f(L.prior_day && L.prior_day.high)}</span></div>
      <div class="stat"><b>PREV L</b><span>${f(L.prior_day && L.prior_day.low)}</span></div>
      <div class="stat"><b>PREV C</b><span>${f(p.prev_close)}</span></div></div>
    ${setupBlock(t, SU)}
    <div class="mid">
      <div class="sig"><h4>TREND STATE, NOT A FORECAST</h4><div class="sub">bias · conf · ADX / state · score</div><table>${sigRows(t)}</table>${currentRuleLine(SU)}</div>
      <div class="lv ${L.direction === "short" ? "short" : ""}">
        <h4>${L.direction === "short" ? "PUT / SHORT IDEA" : "CALL / LONG IDEA"}</h4>
        <div class="k">Extended Entry:</div><div class="v entry">${f(L.ext_entry)}${pct(L.ext_entry, c)}</div>
        <div class="k">MAIN Potential Entry:</div><div class="v big entry">${f(L.main_entry)}</div>
        <div class="k">MAIN Potential Exit:</div><div class="v big exit">${f(L.main_exit)}</div>
        <div class="k">Extended Exit:</div><div class="v exit">${f(L.ext_exit)}${pct(L.ext_exit, c)}</div>
        <div class="ref">10d swing ${f(L.swing_low_10d)}–${f(L.swing_high_10d)} · 20d ${f(L.swing_low_20d)}–${f(L.swing_high_20d)}</div></div></div>
    <div class="trend"><div class="t ${cls(t.signals.Total.bias)}">${t.trend ? t.trend.text : D}</div>
      <div class="row">
        <div><div class="lbl">MAIN DAILY SIGNAL</div><div class="${dCls}">${dl} · Score ${t.daily_score ?? D}/100</div>
          <div class="meter"><i style="width:${t.daily_score ?? 0}%;background:${t.daily_score >= 58 ? "var(--green)" : t.daily_score > 42 ? "var(--neut)" : "var(--red)"}"></i></div></div>
        <div><div class="qrow"><span class="lbl">TRADE QUALITY</span><b>${q.score ?? D}%</b></div>
          <div class="sub">${q.label || D} · agree ${f(q.agreement * 100, 0)}% · ADX ${f(q.trend_strength * 100, 0)}% · liq ${f(q.options_liquidity * 100, 0)}%</div>
          <div class="meter"><i style="width:${q.score ?? 0}%;background:${qColor}"></i></div></div></div></div>
    ${(t.notes && t.notes.length) ? `<div class="notes">Data notes: ${t.notes.join("; ")}</div>` : ""}
  </div>
  <div class="r"><h4>OTM OPTIONS · BEST = 3 NEAREST OTM, TIGHTEST SPREAD, OI/VOL &gt; 0</h4>
    <div class="tabs">${TABS.map(x => `<button data-t="${x[0]}">${x[0]}</button>`).join("")}</div>
    <div class="olist"></div></div>`;
  const list = el.querySelector(".olist"), btns = el.querySelectorAll(".tabs button");
  const pick = tab => { btns.forEach(b => b.classList.toggle("on", b.dataset.t === tab)); renderOpts(t, tab, list); };
  btns.forEach(b => b.onclick = () => pick(b.dataset.t));
  pick("0");
  return el;
}

// ---- "Why these lists" evidence (How section), rendered from setups.json; nothing typed by hand ----
function listEvidence(SU, d) {
  const el = document.getElementById("list-evidence"); if (!el) return;
  const L = SU && SU.live, R4 = SU && SU.round4;
  if (!L || !R4) { el.innerHTML = `<p class="muted">Research figures unavailable (setups.json not loaded).</p>`; return; }
  const g = L.grade_a.test, nn = L.grade_a.new_names, a7 = L.all.core7, C = R4.concentration, no = L.grade_a.next_open_entry;
  const st = L.risk.stop.grade_a, B8 = SU.home_evidence && SU.home_evidence.b8;
  document.querySelectorAll(".uv-n").forEach(x => x.textContent = L.n_universe);
  el.innerHTML = `<p>The home page has three sections, chosen on the research results:</p><ol>
    <li><b>Setups firing now</b>: every stock in the ${L.n_universe}-name scan universe where the Pullback setup fires on the last completed close. This is the only rule that held up out of sample. Grade A, out of sample ${L.test[0].slice(0, 4)}–${L.test[1].slice(2, 4)}: right <b>${pc(g.hit, 1)}</b> vs ${pc(g.same_exit_random_hit, 1)} for random entries with the same exit (p = ${g.p_hit_vs_same_exit.toExponential(1)}, under the cumulative multiple-testing bar ${L.alpha.toFixed(6)} for ${L.tests_cumulative} tests), ${sg(g.exp_net_pct)}/trade after costs vs ${sg(g.same_exit_random_exp_net_pct)} random, n = ${g.n}. Same direction in training (2005–22: ${pc(L.grade_a.train.hit, 1)} vs ${pc(L.grade_a.train.same_exit_random_hit, 1)}), in every test year, with next-open entry (${sg(no.exp_net_pct)}/trade), and on the stocks that were <i>not</i> in the original research set (${pc(nn.hit, 1)} vs ${pc(nn.same_exit_random_hit, 1)}, n = ${nn.n}).</li>
    <li><b>Momentum leaders</b>: the current top ${d.home.leaders_top} by 12-1 momentum, the only names that can produce a Grade A setup. This is a <b>watchlist, not a buy list</b>: in round 2, simply holding the top momentum names did ${B8 ? `<b>not</b> beat equal-weight buy &amp; hold out of sample (Sharpe ${B8.sharpe} vs ${B8.bench_sharpe})` : "not beat buy &amp; hold out of sample"}.</li>
    <li><b>This Week</b>: your own 7 picks, kept as their own section because you chose them. On these 7 combined no rule had a reliable edge out of sample (all pullbacks ${pc(a7.hit, 1)} vs ${pc(a7.same_exit_random_hit, 1)} random, ${sg(a7.exp_net_pct)}/trade, n = ${a7.n}); with ${L.n_universe} names ranked they will rarely be in the momentum top 10.</li></ol>
    <p><b>Why ${L.n_universe} stocks, not 23:</b> round 4 (protocol and adoption rule written down before any result was seen: same train/test split, 0.05%/side costs, random same-exit baseline, Bonferroni bar) re-tested the unchanged rules on the S&amp;P 100 + 15 ETFs + the This Week tickers. All three counted tests passed, and the pre-set adoption checks passed: the exact live rule, gains outside the original 23, next-open entry, and download/runtime reliability. Details: <a href="backtest.html#round4">Backtest → Round 4</a>.</p>
    <p class="warnline"><b>Read with care.</b> (1) Survivorship: the universe is <i>today's</i> S&amp;P 100, so the backtest only contains companies that ended up large; this flatters any long rule, momentum most, and the absolute net per trade is likely overstated (the random baseline shares the bias, so the hit-rate comparison is fairer). (2) Concentration: ${C.top5_by_net.join(", ")} produced ${pc(C.top5_share_of_net)} of the net; without them ${pc(C.without_top5.hit, 1)} right, ${sg(C.without_top5.exp_net_pct)}/trade (n = ${C.without_top5.n}). (3) Bigger losses: avg loss ${sg(g.avg_loss_net)} vs avg win ${sg(g.avg_win_net)}, worst trade ${sg(C.worst.net_pct, 1)} (${C.worst.ticker}, entry ${C.worst.entry}); the optional 3×ATR stop cut the worst to ${sg(st.stop.test.worst_trade_pct, 1)} but lowered net to ${sg(st.stop.test.exp_net_pct)}/trade. (4) Overlapping trades: clustered by entry date the t-statistic is ${g.t_clustered}, much weaker than the binomial p suggests.</p>`;
}

// ---- Home page: summary strip, sections (firing / leaders / this week), compact rows that expand into the full card ----
const ET = d => { const o = {}; new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false, weekday: "short" })
  .formatToParts(d).forEach(p => o[p.type] = p.value); return { ymd: `${o.year}-${o.month}-${o.day}`, wd: o.weekday, min: (+o.hour % 24) * 60 + +o.minute }; };
const addDays = (ymd, n) => { const x = new Date(ymd + "T12:00:00Z"); x.setUTCDate(x.getUTCDate() + n); return x.toISOString().slice(0, 10); };
const wdOf = ymd => new Date(ymd + "T12:00:00Z").getUTCDay();
function marketNow(cal, now = new Date()) {
  const e = ET(now), H = new Set(cal.holidays || []), EC = new Set(cal.early_closes || []);
  const trading = ymd => wdOf(ymd) % 6 !== 0 && !H.has(ymd), close = ymd => EC.has(ymd) ? 780 : 960;
  const td = trading(e.ymd), cm = close(e.ymd);
  let state = "closed";
  if (td && e.min >= 570 && e.min < cm) state = "open"; else if (td && e.min >= 240 && e.min < 570) state = "pre"; else if (td && e.min >= cm && e.min < 1200) state = "after";
  let last = td && e.min >= cm ? e.ymd : addDays(e.ymd, -1); while (!trading(last)) last = addDays(last, -1);
  let next = td && e.min < 570 ? e.ymd : addDays(e.ymd, 1); while (!trading(next)) next = addDays(next, 1);
  return { state, close: `${Math.floor(cm / 60)}:${String(cm % 60).padStart(2, "0")} ET`, early: td && cm === 780, lastSession: last, nextOpen: next };
}
const md = ymd => ymd ? new Date(ymd + "T12:00:00Z").toLocaleDateString("en-US", { timeZone: "UTC", weekday: "short", month: "short", day: "numeric" }) : D;
const PT = iso => new Date(iso).toLocaleString("en-US", { timeZone: "America/Los_Angeles", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) + " PT";
const ago = iso => { const m = Math.round((Date.now() - new Date(iso)) / 60000); return m < 60 ? `${m} min ago` : m < 2880 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} days ago`; };

function summaryStrip(d) {
  const H = d.home, S = d.scanner, M = marketNow(H.calendar);
  const lab = { open: "Market open", pre: "Pre-market", after: "After hours", closed: "Market closed" }[M.state];
  const mk = M.state === "open" ? `${lab} · closes ${M.close}${M.early ? " (early close)" : ""}` : `${lab} · opens ${md(M.nextOpen)} 9:30 ET`;
  const age = (Date.now() - new Date(d.generated_at)) / 60000;
  const stale = M.state === "open" ? age > H.stale_after_minutes_open : S.bar_date < M.lastSession;
  const why = M.state === "open" ? `older than ${H.stale_after_minutes_open} min during market hours` : `the ${md(M.lastSession)} close is not in this build yet`;
  const fire = S.rows.filter(r => r.fired), nA = fire.filter(r => r.grade === "A").length;
  return `<span class="chip mk ${M.state}"><i></i>${mk}</span>
    <span class="chip${stale ? " warn" : ""}" title="${stale ? "Stale: " + why : ""}">Data: ${md(S.bar_date)} close · built ${PT(d.generated_at)} (${ago(d.generated_at)})${stale ? ` · <b>stale</b> (${why})` : ""}</span>
    <a class="chip fire${fire.length ? " on" : ""}" href="#sec-firing">Setups firing: <b>${fire.length}</b>${fire.length ? ` · Grade A ${nA} · B ${fire.length - nA}` : ""}</a>
    <a class="chip" href="scanner.html">${S.rows.length} stocks scanned · ranks as of ${md(S.rank_asof)}</a>`;
}

const SECT = {
  firing: { title: "Setups firing now", note: (d, L) => `Pullback setup (close &gt; SMA200 and RSI(2) &lt; 10) on the ${md(d.scanner.bar_date)} close, across all ${d.scanner.rows.length} scanned stocks. Grade A = also in the momentum top ${d.scanner.top_n}. Long only; exit at the first close above SMA(5) or after 10 days.${L ? ` Out of sample, Grade A was right ${pc(L.grade_a.test.hit, 1)} vs ${pc(L.grade_a.test.same_exit_random_hit, 1)} random (n = ${L.grade_a.test.n}), but losses ran bigger than wins. <a href="#how-list">Evidence</a>` : ""}`,
            empty: d => `No pullback setup on the ${md(d.scanner.bar_date)} close among ${d.scanner.rows.length} stocks.` },
  leaders: { title: "Momentum leaders", note: d => `Top ${d.home.leaders_top} of ${d.scanner.rank_of} by 12-1 month momentum at the ${md(d.scanner.rank_asof)} month-end close. Grade A setups can only come from this list. A watchlist, <b>not a buy list</b>. <a href="#how-list">Why</a>`,
             empty: () => "No ranked stocks in this build." },
  this_week: { title: "This Week", note: (d, L) => `Your own picks.${L ? ` On these ${d.config.tickers.length} combined, no rule had a reliable edge out of sample (all pullbacks ${pc(L.all.core7.hit, 1)} vs ${pc(L.all.core7.same_exit_random_hit, 1)} random, n = ${L.all.core7.n}).` : ""}`,
               empty: () => "No tickers configured." },
};
const SORTS = {
  default: null, rank: (a, b) => (a.r.mom_rank ?? 1e9) - (b.r.mom_rank ?? 1e9),
  rsi: (a, b) => (a.r.rsi2 ?? 1e9) - (b.r.rsi2 ?? 1e9), chg: (a, b) => (b.r.change_pct ?? -1e9) - (a.r.change_pct ?? -1e9),
  tk: (a, b) => a.r.ticker.localeCompare(b.r.ticker),
};
function rowHTML(r, t, d) {
  const pill = r.status === "insufficient_history" ? `<span class="pill na">no setup · short history</span>` : r.fired ? `<span class="pill ${r.grade === "A" ? "ga" : "gb"}">Grade ${r.grade}</span>`
    : r.status === "ok" ? `<span class="pill none">no setup</span>` : `<span class="pill na">no data</span>`;
  const tr = t && t.status === "ok" && t.trend ? `<span class="${cls(t.signals.Total.bias)}">${t.trend.label}</span>` : D;
  const tw = d.config.tickers.includes(r.ticker) ? `<span class="dash">This Week</span>` : "";
  return `<div class="hl1"><span class="htk">${r.ticker}</span>${tw}${r.stale || (t && t.stale) ? '<span class="few">stale</span>' : ""}<span class="hnm">${t && t.name ? t.name : ""}</span>
      <span class="hpx">$${f(r.price)} <span class="${(r.change_pct || 0) >= 0 ? "up" : "dn"}">${sg(r.change_pct)}</span></span></div>
    <div class="hl2">${pill}<span><span class="lab">Rank</span> ${r.mom_rank == null ? "unranked" : `#${r.mom_rank}<span class="muted">/${r.rank_of}</span>`}</span>
      <span><span class="lab">12-1</span> ${sg(r.mom_12_1, 0)}</span><span><span class="lab">RSI(2)</span> <span class="${r.rsi2 != null && r.rsi2 < 10 ? "up" : ""}">${f(r.rsi2, 1)}</span></span>
      <span><span class="lab">SMA200</span> ${r.above_sma200 == null ? D : r.above_sma200 ? '<span class="up">above</span>' : '<span class="dn">below</span>'}</span>
      <span><span class="lab">Trend state</span> ${tr}</span></div>`;
}
const uniq = c => { if (c.id && document.getElementById(c.id)) c.removeAttribute("id"); return c; };
function renderHome(d, SU) {
  const root = document.getElementById("home"), L = SU && SU.live;
  const rows = Object.fromEntries(d.scanner.rows.map(r => [r.ticker, r])), cards = Object.fromEntries(d.tickers.map(t => [t.ticker, t]));
  const state = { f: "all", sort: "default" };
  const draw = () => {
    root.innerHTML = "";
    d.home.sections.forEach(sec => {
      if (state.f !== "all" && state.f !== sec.key) return;
      const M = SECT[sec.key]; const el = document.createElement("section"); el.className = "hsec"; el.id = "sec-" + sec.key;
      let items = sec.tickers.map((tk, i) => ({ i, r: rows[tk] || { ticker: tk, status: "no_data" }, t: cards[tk] }));
      if (SORTS[state.sort]) items.sort(SORTS[state.sort]);
      el.innerHTML = `<h2>${M.title} <span class="cnt">${sec.tickers.length}</span></h2><p class="secnote">${M.note(d, L)}</p>
        <div class="hlist">${items.length ? "" : `<div class="hempty">${M.empty(d)}</div>`}</div>`;
      const list = el.querySelector(".hlist");
      items.forEach(({ r, t }) => {
        const w = document.createElement("div"); w.className = "hrow" + (r.fired ? " fire" : ""); w.dataset.tk = r.ticker;
        const b = document.createElement("button"); b.className = "hbtn"; b.setAttribute("aria-expanded", "false");
        b.innerHTML = rowHTML(r, t, d) + `<span class="chev" aria-hidden="true">▸</span>`;
        const body = document.createElement("div"); body.className = "hbody"; body.hidden = true;
        b.onclick = () => { const open = body.hidden; body.hidden = !open; b.setAttribute("aria-expanded", String(open)); w.classList.toggle("open", open);
          if (open && !body.firstChild) body.appendChild(t ? uniq(card(t, d.config, SU)) : Object.assign(document.createElement("div"), { className: "nodata", textContent: "No full card for this ticker in this build." })); };
        w.append(b, body); list.appendChild(w);
      });
      if (sec.key === "leaders") list.insertAdjacentHTML("afterend", `<p class="more"><a href="scanner.html">All ${d.scanner.rows.length} stocks on the Scanner →</a></p>`);
      root.appendChild(el);
    });
  };
  document.querySelectorAll(".filters button").forEach(b => b.onclick = () => { state.f = b.dataset.f;
    document.querySelectorAll(".filters button").forEach(x => x.classList.toggle("on", x === b)); draw(); });
  document.getElementById("sort").onchange = e => { state.sort = e.target.value; draw(); };
  d.home.sections.forEach(sec => { const b = document.querySelector(`.filters button[data-f="${sec.key}"]`); if (b) b.insertAdjacentHTML("beforeend", ` <span class="cnt">${sec.tickers.length}</span>`); });
  draw();
  const open = tk => { const w = root.querySelector(`.hrow[data-tk="${tk}"]`); if (!w) return; const b = w.querySelector(".hbtn"); if (b.getAttribute("aria-expanded") === "false") b.click(); w.scrollIntoView(); };
  if (location.hash.startsWith("#card-")) open(location.hash.slice(6));
  else if (location.hash.length > 1) { const x = document.getElementById(location.hash.slice(1)); if (x) x.scrollIntoView(); }
  window.addEventListener("hashchange", () => { if (location.hash.startsWith("#card-")) open(location.hash.slice(6)); });
}

const getJSON = u => fetch(u, { cache: "no-store" }).then(r => { if (!r.ok) throw new Error(u + " " + r.status); return r.json(); });
Promise.all([getJSON("data.json"), getJSON("setups.json").catch(() => null)]).then(([d, SU]) => {
  document.getElementById("meta").innerHTML = `<span>Built ${PT(d.generated_at)}</span><span class="sep"> · </span><span>DTE counted from ${d.dte_reference_date}</span>`;
  document.getElementById("src").textContent = d.source;
  if (!d.home || !d.scanner) throw new Error("this data.json has no home/scanner block; rebuild with build_data.py");
  document.getElementById("strip").innerHTML = summaryStrip(d);
  setInterval(() => { document.getElementById("strip").innerHTML = summaryStrip(d); }, 60000);
  renderHome(d, SU);
  rowsEvidence(SU); listEvidence(SU, d);
}).catch(e => { document.getElementById("home").innerHTML = `<div class="nodata">Could not load data.json (${e}). Run <code>python build_data.py</code> and serve this folder over HTTP.</div>`; });
