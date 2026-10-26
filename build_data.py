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
import numpy as np, pandas as pd, yfinance as yf

warnings.filterwarnings("ignore")
ROOT = Path(__file__).parent
CFG = json.loads((ROOT / "config.json").read_text())
OUT = ROOT / "site" / "data.json"
NY = "America/New_York"


def num(x, nd=4):
    """JSON-safe rounding; NaN/None -> None."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(x) or math.isinf(x)) else round(x, nd)


# ---------------- indicators (all standard, documented in README / site) -------------
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()

def rsi(close, n=14):  # Wilder's RSI
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))

def macd_hist(close, f=12, s=26, sig=9):
    m = ema(close, f) - ema(close, s)
    return m - ema(m, sig)

def atr(df, n=14):  # Wilder's ATR
    pc = df.Close.shift()
    tr = pd.concat([df.High - df.Low, (df.High - pc).abs(), (df.Low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()

def adx(df, n=14):  # Wilder's ADX
    up, dn = df.High.diff(), -df.Low.diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    a = atr(df, n)
    pdi = 100 * pd.Series(pdm, df.index).ewm(alpha=1 / n, adjust=False).mean() / a
    ndi = 100 * pd.Series(ndm, df.index).ewm(alpha=1 / n, adjust=False).mean() / a
    dx = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean()

def adx_label(v):
    if v is None: return "—"
    return "V.H" if v >= 40 else "H" if v >= 25 else "OK" if v >= 20 else "L"


def frame_signal(df):
    """Score one timeframe. Each component votes +1 (bullish), -1 (bearish) or 0."""
    w = CFG["indicator_weights"]; c = df.Close; last = float(c.iloc[-1]); n = len(df)
    comp = {}
    if n >= 50:
        e20, e50 = float(ema(c, 20).iloc[-1]), float(ema(c, 50).iloc[-1])
        comp["ema_cross"] = {"vote": 1 if e20 > e50 else -1, "ema20": num(e20), "ema50": num(e50)}
    if n >= 200:
        s200 = float(c.rolling(200).mean().iloc[-1])
        comp["sma200"] = {"vote": 1 if last > s200 else -1, "sma200": num(s200)}
    if n >= 30:
        r = float(rsi(c).iloc[-1])
        comp["rsi"] = {"vote": 1 if r > 55 else -1 if r < 45 else 0, "rsi": num(r, 1)}
    if n >= 35:
        h = float(macd_hist(c).iloc[-1])
        comp["macd"] = {"vote": 1 if h > 0 else -1 if h < 0 else 0, "hist": num(h)}
    tw = sum(w[k] for k in comp)
    if tw == 0:
        return {"bars": n, "bias": None, "score": None, "confidence": None, "components": comp}
    s = sum(w[k] * comp[k]["vote"] for k in comp) / tw          # in [-1, 1]
    a = adx(df).iloc[-1] if n >= 30 else np.nan
    return {"bars": n, "last_bar": df.index[-1].isoformat(), "score": num(s, 3),
            "components": comp, "missing": [k for k in w if k not in comp],
            "adx": num(a, 1), "adx_label": adx_label(num(a, 1)), **bias_conf(s)}


def bias_conf(s):
    th = CFG["bias_threshold"]
    if s >= th:  return {"bias": "CALL", "confidence": round(50 + 50 * s)}
    if s <= -th: return {"bias": "PUT", "confidence": round(50 + 50 * -s)}
    return {"bias": "NEUT", "confidence": round(50 + 50 * (1 - abs(s) / th))}


def daily_label(score100):
    if score100 is None: return "—"
    return ("Strong CALL" if score100 >= 70 else "Moderate CALL" if score100 >= 58 else
            "Neutral" if score100 > 42 else "Moderate PUT" if score100 > 30 else "Strong PUT")


# ---------------- price data -------------
def history(tk, interval, period):
    d = tk.history(period=period, interval=interval, auto_adjust=False, prepost=False)
    d = d[["Open", "High", "Low", "Close", "Volume"]].dropna()
    if interval != "1d" and len(d):
        d.index = d.index.tz_convert(NY)
    return d


def levels(daily, direction):
    """Entry/exit from daily ATR(14) multiples and 10/20-day swing highs/lows."""
    if len(daily) < 15: return None
    c = float(daily.Close.iloc[-1]); a = float(atr(daily).iloc[-1])
    h10, l10 = float(daily.High.iloc[-10:].max()), float(daily.Low.iloc[-10:].min())
    h20, l20 = float(daily.High.iloc[-20:].max()), float(daily.Low.iloc[-20:].min())
    prev = daily.iloc[-2]
    if direction >= 0:   # long idea: buy pullbacks, take profit above
        lv = {"main_entry": c - 0.5 * a, "ext_entry": min(c - 1.0 * a, l10),
              "main_exit": c + 1.0 * a, "ext_exit": max(c + 2.0 * a, h20)}
    else:                # short / put idea: enter on bounces, targets below
        lv = {"main_entry": c + 0.5 * a, "ext_entry": max(c + 1.0 * a, h10),
              "main_exit": c - 1.0 * a, "ext_exit": min(c - 2.0 * a, l20)}
    out = {k: num(v, 2) for k, v in lv.items()}
    out.update(direction="long" if direction >= 0 else "short", atr14=num(a, 3), ref_close=num(c, 2),
               swing_high_10d=num(h10, 2), swing_low_10d=num(l10, 2), swing_high_20d=num(h20, 2),
               swing_low_20d=num(l20, 2), prior_day={"high": num(prev.High, 2), "low": num(prev.Low, 2),
                                                     "close": num(prev.Close, 2)})
    return out


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
    return out


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
    asof = dt.datetime.now().astimezone().date()
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
