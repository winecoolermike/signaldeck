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
  const R = SU && SU.risk; if (!R) return "";
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
  const V = SU && SU.versions, T = s.ticker_stats || {};
  const row = (lab, v, me) => { if (!v) return ""; const a = v.test.all23;
    return `<tr${me ? ' class="me"' : ""}><td>${lab}</td><td>${a.n}</td><td><b>${pc(a.hit, 1)}</b> <span class="muted">vs ${pc(a.same_exit_random_hit, 1)}</span></td><td>${sg(a.exp_net_pct)}</td><td>${sg(a.avg_win_net)} / ${sg(a.avg_loss_net)}</td></tr>`; };
  const own = (lab, x) => !x || !x.n ? `<div>${lab}: no trades yet${tooFew(0)}</div>` :
    `<div>${lab}: ${x.n} trades, right ${pc(x.hit)} vs ${pc(T.random_same_exit && T.random_same_exit.hit)} random same-exit, ${sg(x.exp_net_pct)}/trade${tooFew(x.n)}</div>`;
  const c7 = V && V.all.test.core7, a7 = V && V.grade_a && V.grade_a.test.core7;
  return `<div class="setup on">
    <div class="sh"><span class="sbadge">SETUP: Pullback${s.grade === "A" ? " · Grade A" : " · Grade B"}</span><span class="muted">long only · close ${s.bar_date}</span>${stale}</div>
    <div class="why">Close ${f(s.close)} &gt; SMA200 ${f(s.sma200)} · RSI(2) ${f(s.rsi2, 1)} &lt; 10 · ADX(14) ${f(s.adx, 1)} <span class="muted">(info only)</span></div>
    <div class="why"><b>Rank:</b> ${rankLine(s)} among the ${SU && SU.research ? SU.research.tickers.all23.length : 23}-stock universe → ${s.grade === "A" ? "top 10 → <b>Grade A</b>" : "not top 10 → Grade B"}. <a href="scanner.html">Scanner →</a></div>
    <div class="why"><b>Exit rule:</b> first daily close above SMA(5) (now ${f(s.sma5)}), or after 10 trading days.</div>
    ${riskLines(s, SU)}
    ${V ? `<div class="tablewrap"><table class="st"><tr><th>Out-of-sample ${SU.research.test[0].slice(0, 4)}–${SU.research.test[1].slice(2, 4)}, ${SU.research.tickers.all23.length} stocks</th><th>Trades</th><th>Right vs random same exit</th><th>Net/trade</th><th>Avg win / avg loss</th></tr>
      ${row("Grade A (top-10 momentum)", V.grade_a, s.grade === "A")}${row("All pullbacks", V.all, s.grade !== "A")}</table></div>` : `<div class="muted">Research stats unavailable (setups.json not loaded).</div>`}
    <div class="own"><b>${t.ticker} itself</b> (${T.window ? T.window[0] + " → " + T.window[1] : D}):${own("All", T.all)}${own("Grade A", T.grade_a)}</div>
    ${c7 ? `<div class="warnline">On the 7 dashboard tickers combined there was no reliable edge out of sample: all pullbacks right ${pc(c7.hit)} vs ${pc(c7.same_exit_random_hit)} random, ${sg(c7.exp_net_pct)}/trade (n=${c7.n})${a7 ? `; Grade A ${pc(a7.hit)} vs ${pc(a7.same_exit_random_hit)}, ${sg(a7.exp_net_pct)}/trade (n=${a7.n}, not significant)` : ""}.</div>` : ""}
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
  el.innerHTML = `
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

const getJSON = u => fetch(u, { cache: "no-store" }).then(r => { if (!r.ok) throw new Error(u + " " + r.status); return r.json(); });
Promise.all([getJSON("data.json"), getJSON("setups.json").catch(() => null)]).then(([d, SU]) => {
  document.getElementById("meta").innerHTML = `<span>Built ${new Date(d.generated_at).toLocaleString("en-US", { timeZone: "America/Los_Angeles", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} PT</span><span class="sep"> · </span><span>DTE counted from ${d.dte_reference_date}</span>`;
  document.getElementById("src").textContent = d.source;
  const root = document.getElementById("cards");
  d.tickers.forEach(t => root.appendChild(card(t, d.config, SU)));
  rowsEvidence(SU);
  if (location.hash.startsWith("#card-")) { const c = document.getElementById(location.hash.slice(1)); if (c) c.scrollIntoView(); }
}).catch(e => { document.getElementById("cards").innerHTML = `<div class="nodata">Could not load data.json (${e}). Run <code>python build_data.py</code> and serve this folder over HTTP.</div>`; });
