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
                     SETUP, pullback_setup, pullback_ticker_stats, completed_sessions)

OUT = ROOT / "site" / "data.json"



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
def build_ticker(sym, asof):
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
    out["setup"] = setup_block(tk)
    return out


def setup_block(tk):
    """Pullback setup on the latest COMPLETED daily close (adjusted bars, full history, as in the research).
    Rule parameters come from signals.SETUP and are never changed here; only the stats are recomputed."""
    try:
        d = tk.history(period="max", interval="1d", auto_adjust=True)[["Open", "High", "Low", "Close", "Volume"]].dropna()
    except Exception as e:
        return {"status": "error", "fired": False, "reason": f"adjusted history fetch failed: {e}"}
    now_ny = dt.datetime.now(ZoneInfo(NY))
    d = completed_sessions(d, now_ny.replace(tzinfo=None) if d.index.tz is None else now_ny)
    st = pullback_setup(d)
    st["ticker_stats"] = pullback_ticker_stats(d) if st.get("status") == "ok" else None
    return st


def quality(frames, total, opts, daily):
    """Trade quality 0-100 = 40% timeframe agreement + 30% daily ADX trend strength + 30% options liquidity."""
    keys = [tf for tf in CFG["timeframes"] if frames[tf["key"]].get("bias")]
    W = sum(tf["weight"] for tf in keys)
    sgn = {"CALL": 1, "PUT": -1, "NEUT": 0}
    agree = abs(sum(tf["weight"] * sgn[frames[tf["key"]]["bias"]] for tf in keys)) / W if W else 0
    a = frames["Main"].get("adx")
    trend = min(a / 40, 1) if a is not None else 0
    spreads = [x[side]["rel_spread"] for x in opts.get("expiries", [])[:3] for side in ("call", "put") if x.get(side)]
    liq = max(0.0, 1 - (sum(spreads) / len(spreads)) / 0.20) if spreads else 0.0
    q = round(100 * (0.4 * agree + 0.3 * trend + 0.3 * liq))
    lab = "Excellent" if q >= 75 else "Good" if q >= 55 else "Fair" if q >= 30 else "Poor"
    return {"score": q, "label": lab, "agreement": num(agree, 3), "trend_strength": num(trend, 3),
            "options_liquidity": num(liq, 3), "avg_rel_spread": num(sum(spreads) / len(spreads), 4) if spreads else None}


def main():
    asof = dt.datetime.now(ZoneInfo("America/New_York")).date()  # US market date, independent of runner TZ (UTC on GitHub)
    out = {"generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
           "dte_reference_date": str(asof), "source": f"Yahoo Finance via yfinance {yf.__version__} (unofficial, may be delayed)",
           "config": CFG, "tickers": []}
    for sym in CFG["tickers"]:
        print("building", sym, file=sys.stderr)
        try:
            out["tickers"].append(build_ticker(sym, asof))
        except Exception as e:
            traceback.print_exc()
            out["tickers"].append({"ticker": sym, "status": "no_data", "notes": [f"build error: {e}"]})
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1))
    print("wrote", OUT, file=sys.stderr)


if __name__ == "__main__":
    main()
