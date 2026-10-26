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

function sigRows(t) {
  const keys = t.config_tfs.map(x => [x.key, x.label]).concat([["Total", "Total"]]);
  return keys.map(([k, lab]) => { const s = t.signals[k] || {};
    return `<tr class="${k === "Total" ? "total" : k === "Main" ? "main" : ""}"><td>${lab}:</td>
      <td class="${cls(s.bias)}">${s.bias || D} (${s.confidence == null ? D : s.confidence + "%"})</td>
      <td class="adx" title="ADX(14)=${f(s.adx, 1)}">${k === "Total" ? "" : (s.adx_label || D)}</td></tr>`; }).join("");
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

function card(t, cfg) {
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
    <div class="mid">
      <div class="sig"><h4>SIGNAL (bias · conf · ADX)</h4><table>${sigRows(t)}</table></div>
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

fetch("data.json", { cache: "no-store" }).then(r => r.json()).then(d => {
  document.getElementById("meta").innerHTML = `<span>Built ${new Date(d.generated_at).toLocaleString("en-US", { timeZone: "America/Los_Angeles", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} PT</span><span class="sep"> · </span><span>DTE counted from ${d.dte_reference_date}</span>`;
  document.getElementById("src").textContent = d.source;
  const root = document.getElementById("cards");
  d.tickers.forEach(t => root.appendChild(card(t, d.config)));
}).catch(e => { document.getElementById("cards").innerHTML = `<div class="nodata">Could not load data.json (${e}). Run <code>python build_data.py</code> and serve this folder over HTTP.</div>`; });
