#!/usr/bin/env python3
"""SignalDeck data builder.

Fetches real market data (Yahoo Finance via yfinance), computes transparent
signals, and writes site/data.json for the static dashboard.

    python build_data.py            # uses config.json
Nothing here is fabricated: any value that cannot be computed is written as null
and shown as '—' on the site. Not financial advice.
"""
import json, math, sys, datetime as dt, warnings, traceback
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd, yfinance as yf

warnings.filterwarnings("ignore")
from signals import (ROOT, CFG, NY, num, ema, rsi, macd_hist, atr, adx, adx_label,
                     frame_signal, bias_conf, daily_label, history, levels,
                     SETUP, UNIVERSE, pullback_setup, pullback_ticker_stats, completed_sessions,
                     momentum_ranks, ROWS, ema_state, vwap_state,
                     market_status, calendar_lists, home_sections)

OUT = ROOT / "site" / "data.json"
OHLCV = ["Open", "High", "Low", "Close", "Volume"]


# ---------------- previous good data (fallback for tickers that fail this run) -------------
def load_prev():
    """Newest of: $PREV_DATA (paths separated by ':', e.g. the live site's data.json) and the existing site/data.json."""
    import os
    best = None
    for p in [x for x in os.environ.get("PREV_DATA", "").split(":") if x] + [str(OUT)]:
        try:
            d = json.loads(Path(p).read_text())
            t = dt.datetime.fromisoformat(d["generated_at"])
            if best is None or t > best[0]: best = (t, d)
        except Exception:
            pass
    return best[1] if best else {}


# ---------------- daily bars for the whole scan universe (config scan_universe): one batch call, per-ticker retry -------------
def fetch_universe(syms):
    """Returns ({sym: adjusted daily OHLCV with tz-naive dates, or None}, {sym: how it was fetched})."""
    got, how = {}, {}
    try:
        b = yf.download(syms, period="max", interval="1d", auto_adjust=True, group_by="ticker",
                        threads=True, progress=False, timeout=30)
    except Exception as e:
        print("batch download failed:", e, file=sys.stderr); b = None
    for s in syms:
        d = None
        try:
            if b is not None and s in b.columns.get_level_values(0):
                d = b[s][OHLCV].dropna(subset=["Open", "High", "Low", "Close"])
        except Exception:
            d = None
        how[s] = "batch"
        if d is None or len(d) == 0:
            how[s] = "retry"
            try:
                d = yf.Ticker(s).history(period="max", interval="1d", auto_adjust=True)[OHLCV].dropna(subset=["Close"])
                if d.index.tz is not None: d.index = d.index.tz_localize(None).normalize()
            except Exception as e:
                print("retry failed", s, e, file=sys.stderr); d = None
        if d is None or len(d) == 0:
            d = None; how[s] = "failed"
        got[s] = d
    return got, how



# ---------------- options -------------
def options(tk, last, asof):
    oc = CFG["options"]; res = []
    try:
        exps = tk.options
    except Exception as e:
        return {"error": f"options list failed: {e}", "expiries": []}
    for e in exps:
        dte = (dt.date.fromisoformat(e) - asof).days
        if dte < 0 or dte > oc["max_dte"]: continue
        try:
            ch = tk.option_chain(e)
        except Exception as ex:
            res.append({"expiry": e, "dte": dte, "error": str(ex)}); continue
        res.append({"expiry": e, "dte": dte,
                    "call": best_otm(ch.calls[ch.calls.strike > last].sort_values("strike"), oc),
                    "put": best_otm(ch.puts[ch.puts.strike < last].sort_values("strike", ascending=False), oc)})
    return {"expiries": res}


def best_otm(df, oc):
    """Among the N nearest OTM strikes, keep those with bid>0, ask>0 and (OI>0 or volume>0);
    pick the tightest relative spread (ask-bid)/mid; ties -> nearest strike."""
    cands = []
    for rank, (_, r) in enumerate(df.head(oc["otm_strikes_considered"]).iterrows()):
        bid, ask = num(r.bid, 2), num(r.ask, 2)
        vol, oi = num(r.volume, 0) or 0, num(r.openInterest, 0) or 0
        ok = bool(bid and ask and ask >= bid and (oi > 0 or vol > 0))
        mid = (bid + ask) / 2 if ok else None
        cands.append({"contract": r.contractSymbol, "strike": num(r.strike, 2), "bid": bid, "ask": ask,
                      "last": num(r.lastPrice, 2), "volume": int(vol), "oi": int(oi),
                      "iv": num(r.impliedVolatility, 3), "rel_spread": num((ask - bid) / mid, 4) if ok else None,
                      "otm_rank": rank + 1, "eligible": ok,
                      "last_trade": r.lastTradeDate.isoformat() if pd.notna(r.lastTradeDate) else None})
    el = [c for c in cands if c["eligible"]]
    if not el: return None
    return min(el, key=lambda c: (c["rel_spread"], c["otm_rank"]))


# ---------------- per ticker -------------
def build_ticker(sym, asof, U):
    tk = yf.Ticker(sym)
    out = {"ticker": sym, "status": "ok", "notes": []}
    try:
        info = tk.info or {}
    except Exception:
        info = {}
    out["name"] = info.get("longName") or info.get("shortName")
    out["exchange"] = info.get("fullExchangeName") or info.get("exchange")
    out["market_cap"] = info.get("marketCap")
    frames, data = {}, {}
    for tf in CFG["timeframes"]:
        try:
            d = history(tk, tf["interval"], tf["period"])
        except Exception as e:
            d = pd.DataFrame(); out["notes"].append(f"{tf['key']}: fetch error {e}")
        data[tf["key"]] = d
        if tf["key"] in ROWS:   # round-3 rows: completed bars only, scored +1/-1 (None while waiting)
            r = ROWS[tf["key"]]
            fn = ema_state if r["kind"] == "ema9_21" else vwap_state
            frames[tf["key"]] = fn(d, r["minutes"], U["now_ny"]) if len(d) else {"kind": r["kind"], "status": "no_data", "score": None}
            continue
        frames[tf["key"]] = frame_signal(d) if len(d) else {"bars": 0, "bias": None, "confidence": None, "score": None}
        miss = frames[tf["key"]].get("missing")
        if miss: out["notes"].append(f"{tf['key']}: only {len(d)} bars, skipped {', '.join(miss)} (weights renormalised)")
    daily, m1 = data["Main"], data["1m"]
    if daily.empty:
        return {"ticker": sym, "status": "no_data", "name": out["name"], "notes": ["No price history returned by Yahoo Finance."]}
    # price & change: last regular-session close vs prior session close (daily bars)
    last, prev = float(daily.Close.iloc[-1]), float(daily.Close.iloc[-2]) if len(daily) > 1 else None
    out["price"] = {"last": num(last, 2), "prev_close": num(prev, 2),
                    "change": num(last - prev, 2) if prev else None,
                    "change_pct": num((last / prev - 1) * 100, 2) if prev else None,
                    "session_date": str(daily.index[-1].date()),
                    "as_of": (m1.index[-1] + pd.Timedelta(minutes=1)).isoformat() if len(m1) else str(daily.index[-1].date()),
                    "post_market": num(info.get("postMarketPrice"), 4),
                    "post_market_time": dt.datetime.fromtimestamp(info["postMarketTime"], dt.timezone.utc).astimezone().isoformat()
                    if info.get("postMarketTime") else None}
    # total = weighted blend of available timeframe scores
    tw = [(tf["weight"], frames[tf["key"]]["score"]) for tf in CFG["timeframes"] if frames[tf["key"]].get("score") is not None]
    W = sum(w for w, _ in tw)
    total = sum(w * s for w, s in tw) / W if W else None
    frames["Total"] = {"score": num(total, 3), **(bias_conf(total) if total is not None else {"bias": None, "confidence": None})}
    out["signals"] = frames
    ds = frames["Main"].get("score")
    out["daily_score"] = round(50 + 50 * ds) if ds is not None else None
    out["daily_label"] = daily_label(out["daily_score"])
    if total is not None:
        word = "Bullish" if total >= CFG["bias_threshold"] else "Bearish" if total <= -CFG["bias_threshold"] else "Neutral"
        out["trend"] = {"label": word, "strength_pct": round(abs(total) * 100), "text": f"{word} (Trend ~{round(abs(total)*100)}%)"}
    out["levels"] = levels(daily, 1 if (total or 0) >= 0 else -1)
    out["options"] = options(tk, last, asof)
    out["quality"] = quality(frames, total, out["options"], daily)
    out["setup"] = setup_block(sym, U)
    return out


def setup_block(sym, U):
    """Pullback setup on the latest COMPLETED daily close (adjusted bars, full history, as in the research), graded by
    this ticker's 12-1 momentum rank in the scan universe. Rule parameters come from signals.SETUP and are never
    changed here; only the stats are recomputed with new bars. If this ticker's bars could not be fetched, the previous
    good block is reused and marked stale."""
    d = U["daily"].get(sym)
    if d is None:
        prev = U["prev_setup"].get(sym)
        if prev: return {**prev, "stale": True, "stale_reason": "daily bars could not be refreshed this run"}
        return {"status": "error", "fired": False, "reason": "adjusted daily history fetch failed"}
    st = pullback_setup(d, U["rank"].get(sym), U["asof"], U["rank_of"])
    st["ticker_stats"] = pullback_ticker_stats(d, U["rank"].get(sym)) if st.get("status") == "ok" else None
    st["stale"] = U["lagging"].get(sym, False)
    return st


def universe(now_ny, prev):
    """Batch-fetch the scan universe, compute momentum ranks (as in research2.py) and one scanner row per ticker."""
    raw, how = fetch_universe(UNIVERSE)
    daily = {s: completed_sessions(d, now_ny.replace(tzinfo=None)) if d is not None else None for s, d in raw.items()}
    daily = {s: (d if d is not None and len(d) else None) for s, d in daily.items()}
    last = max((d.index[-1] for d in daily.values() if d is not None), default=None)
    lagging = {s: bool(d is not None and d.index[-1] < last) for s, d in daily.items()}
    prev_rows = {r["ticker"]: r for r in (prev.get("scanner") or {}).get("rows", [])}
    closes = {s: d.Close for s, d in daily.items() if d is not None}
    rank, asof, M = momentum_ranks(closes) if closes else (pd.DataFrame(), pd.Series(dtype="datetime64[ns]"), pd.DataFrame())
    me = asof.iloc[-1] if len(asof) and pd.notna(asof.iloc[-1]) else None
    ov = {s: r.get("mom_12_1") / 100 for s, r in prev_rows.items() if daily.get(s) is None and r.get("mom_12_1") is not None
          and me is not None and r.get("mom_asof") == str(me.date())}
    if ov: rank, asof, M = momentum_ranks(closes, overrides=ov)
    rank_of = int(M.iloc[-1].notna().sum()) if len(M) else None
    U = {"daily": daily, "rank": {s: rank[s] for s in rank.columns}, "asof": asof, "rank_of": rank_of,
         "lagging": lagging, "now_ny": now_ny, "prev_setup": {t["ticker"]: t["setup"] for t in prev.get("tickers", [])
                                                              if t.get("setup", {}).get("status") == "ok"}}
    rows = []
    for s in UNIVERSE:
        d, r0 = daily.get(s), raw.get(s)
        if d is None:
            p = prev_rows.get(s)
            if p:
                rr = rank[s].iloc[-1] if s in ov and s in rank.columns else None
                rows.append({**p, "stale": True, "fetch": how[s],
                             **({"mom_rank": int(round(rr)), "rank_of": rank_of, "mom_asof": str(me.date())} if rr is not None and pd.notna(rr) else {})})
            else:
                rows.append({"ticker": s, "dashboard": s in CFG["tickers"], "status": "no_data", "stale": True, "fetch": how[s]})
            continue
        st = pullback_setup(d, rank.get(s), asof, rank_of)
        mom = M[s].iloc[-1] if len(M) and s in M.columns else np.nan
        px, pv = float(r0.Close.iloc[-1]), float(r0.Close.iloc[-2]) if len(r0) > 1 else None
        rows.append({"ticker": s, "dashboard": s in CFG["tickers"], "status": st["status"], "fetch": how[s],
                     "stale": lagging[s], "price": num(px, 2), "price_date": str(r0.index[-1].date()),
                     "change_pct": num((px / pv - 1) * 100, 2) if pv else None,
                     "bar_date": st["bar_date"], "close": st["close"], "sma200": st["sma200"],
                     "above_sma200": st.get("above_sma200"), "rsi2": st["rsi2"], "adx": st["adx"],
                     "mom_12_1": num(mom * 100, 2), "mom_asof": st["mom_asof"], "mom_rank": st["mom_rank"],
                     "rank_of": rank_of, "in_top": st["in_top"], "fired": st.get("fired", False), "grade": st.get("grade"),
                     "last_fired": st["last_fired"], "reason": st.get("reason"),
                     "leader": bool(st["mom_rank"] is not None and st["mom_rank"] <= CFG.get("home", {}).get("leaders_top", 10))})
    order = {"A": 0, "B": 1, None: 2}
    rows.sort(key=lambda r: (order.get(r.get("grade"), 2), r.get("mom_rank") or 99, r["ticker"]))
    U["scanner"] = {"bar_date": str(last.date()) if last is not None else None,
                    "rank_asof": str(me.date()) if me is not None else None, "rank_of": rank_of,
                    "top_n": SETUP["mom_top"], "universe": UNIVERSE, "universe_key": (CFG.get("scan_universe") or {}).get("key", "23"),
                    "universe_label": (CFG.get("scan_universe") or {}).get("label", "the 23 research tickers"), "rows": rows,
                    "fetch": {k: sum(v == k for v in how.values()) for k in ("batch", "retry", "failed")}}
    return U


def quality(frames, total, opts, daily):
    """Trade quality 0-100 = 40% timeframe agreement + 30% daily ADX trend strength + 30% options liquidity."""
    sgn = {"CALL": 1, "PUT": -1, "NEUT": 0}
    def d(f):   # direction of a row: bias for the score rows, "dir" (+1/-1/0) for the round-3 state rows
        return f["dir"] if f.get("dir") is not None else sgn.get(f.get("bias"))
    keys = [tf for tf in CFG["timeframes"] if d(frames[tf["key"]]) is not None]
    W = sum(tf["weight"] for tf in keys)
    agree = abs(sum(tf["weight"] * d(frames[tf["key"]]) for tf in keys)) / W if W else 0
    a = frames["Main"].get("adx")
    trend = min(a / 40, 1) if a is not None else 0
    spreads = [x[side]["rel_spread"] for x in opts.get("expiries", [])[:3] for side in ("call", "put") if x.get(side)]
    liq = max(0.0, 1 - (sum(spreads) / len(spreads)) / 0.20) if spreads else 0.0
    q = round(100 * (0.4 * agree + 0.3 * trend + 0.3 * liq))
    lab = "Excellent" if q >= 75 else "Good" if q >= 55 else "Fair" if q >= 30 else "Poor"
    return {"score": q, "label": lab, "agreement": num(agree, 3), "trend_strength": num(trend, 3),
            "options_liquidity": num(liq, 3), "avg_rel_spread": num(sum(spreads) / len(spreads), 4) if spreads else None}


def build_cards(syms, asof, U, prev):
    """Full cards for the home-page tickers, built in parallel (each card = its own yfinance calls). A card that fails
    this run falls back to the previous good card for that ticker, marked stale."""
    from concurrent.futures import ThreadPoolExecutor
    prev_cards = {t["ticker"]: t for t in prev.get("tickers", []) if t.get("status") == "ok"}
    def one(sym):
        try:
            c = build_ticker(sym, asof, U)
        except Exception as e:
            traceback.print_exc(); c = {"ticker": sym, "status": "no_data", "notes": [f"build error: {e}"]}
        if c.get("status") != "ok" and sym in prev_cards:
            c = {**prev_cards[sym], "stale": True, "notes": (prev_cards[sym].get("notes") or []) + ["card kept from the previous build (this run could not refresh it)"]}
        return c
    with ThreadPoolExecutor(max_workers=CFG.get("home", {}).get("card_workers", 4)) as ex:
        return list(ex.map(one, syms))


def main():
    asof = dt.datetime.now(ZoneInfo("America/New_York")).date()  # US market date, independent of runner TZ (UTC on GitHub)
    out = {"generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
           "dte_reference_date": str(asof), "source": f"Yahoo Finance via yfinance {yf.__version__} (unofficial, may be delayed)",
           "config": CFG, "setup_rule": SETUP, "tickers": []}
    now_ny = dt.datetime.now(ZoneInfo(NY))
    prev = load_prev()
    U = universe(now_ny, prev)
    out["scanner"] = U["scanner"]
    print("universe fetch:", U["scanner"]["fetch"], file=sys.stderr)
    H = CFG.get("home", {})
    secs = home_sections(U["scanner"]["rows"], CFG["tickers"], H.get("leaders_top", 10))
    syms = list(dict.fromkeys(t for sec in secs for t in sec["tickers"]))   # one full card per home ticker
    t0 = dt.datetime.now()
    out["tickers"] = build_cards(syms, asof, U, prev)
    print(f"built {len(syms)} cards in {(dt.datetime.now() - t0).total_seconds():.0f}s", file=sys.stderr)
    out["home"] = {"sections": secs, "leaders_top": H.get("leaders_top", 10),
                   "stale_after_minutes_open": H.get("stale_after_minutes_open", 45),
                   "market_at_build": market_status(now_ny), "calendar": calendar_lists([now_ny.year, now_ny.year + 1])}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1))
    print("wrote", OUT, file=sys.stderr)


if __name__ == "__main__":
    main()
