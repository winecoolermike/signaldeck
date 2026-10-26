"""SignalDeck shared signal logic.

Imported by BOTH build_data.py (live dashboard) and backtest.py so the two can never drift.
Pure functions only: no network access here except history(), which wraps yfinance.
"""
import json, math
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).parent
CFG = json.loads((ROOT / "config.json").read_text())
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


# ---------------- "Pullback" setup (validated out-of-sample, see site/setups.json) -------------
# FROZEN rule definition. The live builder, the unit tests and make_setups.py all read it from here.
# Jobs only recompute statistics with new bars; they never change these parameters.
EPS_REL = 1e-6

SETUP = {
    "name": "Pullback", "side": "long",
    "trend_sma": 200,           # close > SMA(200) of daily closes
    "rsi_len": 2, "rsi_max": 10,  # RSI(2, Wilder) < 10
    "adx_len": 14, "adx_min_grade_a": 25,  # grade A if ADX(14, Wilder) > 25
    "exit_sma": 5, "max_hold": 10,  # exit: first daily close > SMA(5), or after 10 trading days
    "cost_per_side": 0.0005,     # 0.05% per side, applied to "net" numbers
    "oos_start": "2023-01-01",   # out-of-sample window used for all reported stats
    "min_trades": 30,            # fewer trades -> "too few to trust"
    "price_basis": "split- and dividend-adjusted daily bars (as in the research)",
}


def setup_features(daily):
    """Causal features for the Pullback setup: every value at bar t uses bars <= t only."""
    S = SETUP; c = daily.Close
    f = pd.DataFrame(index=daily.index)
    f["c"] = c
    f["sma200"] = c.rolling(S["trend_sma"]).mean()
    f["sma5"] = c.rolling(S["exit_sma"]).mean()
    f["rsi2"] = rsi(c, S["rsi_len"])
    f["adx"] = adx(daily, S["adx_len"])
    f["fired"] = (f.c > f.sma200) & (f.rsi2 < S["rsi_max"])          # NaN comparisons -> False
    f["grade_a"] = f.fired & (f.adx > S["adx_min_grade_a"])
    f["uptrend"] = f.c > f.sma200                                     # same-exit random baseline entries
    return f


def pullback_trades(f, entries):
    """One position at a time. Enter at the signal bar's close; exit at the first later close above
    SMA(5) or after max_hold bars. A trade still open at the last bar is not counted."""
    # EPS_REL: Yahoo adjusted prices jitter ~1e-7 between downloads; an exact close==SMA5 tie must not flip the exit.
    c, sma5 = f.c.values, f.sma5.values; sig = np.asarray(entries, dtype=bool); n = len(f)
    H = SETUP["max_hold"]; out = []; i = 0
    while i < n - 1:
        if not sig[i]: i += 1; continue
        k = None
        for j in range(i + 1, n):
            if c[j] > sma5[j] * (1 + EPS_REL) or j - i >= H: k = j; break
        if k is None: break
        out.append({"entry": f.index[i], "exit": f.index[k], "ret": c[k] / c[i] - 1, "hold": k - i})
        i = k                      # a new signal may fire on the exit bar itself
    return out


def trade_stats(trades):
    n = len(trades)
    if n == 0: return {"n": 0, "few": True}
    r = np.array([t["ret"] for t in trades]); net = r - 2 * SETUP["cost_per_side"]
    w, l = net[net > 0], net[net <= 0]
    return {"n": n, "hit": num((r > 0).mean(), 4), "exp_net_pct": num(net.mean() * 100, 3),
            "avg_win_net_pct": num(w.mean() * 100, 3) if len(w) else None,
            "avg_loss_net_pct": num(l.mean() * 100, 3) if len(l) else None,
            "avg_hold_days": num(np.mean([t["hold"] for t in trades]), 1), "few": n < SETUP["min_trades"]}


def pullback_ticker_stats(daily, start=None):
    """This ticker's own out-of-sample stats (entries from SETUP['oos_start'] on) for both grades plus
    the same-exit random baseline (enter on every uptrend close, same exit)."""
    start = pd.Timestamp(start or SETUP["oos_start"])
    if len(daily) and daily.index.tz is not None: start = start.tz_localize(daily.index.tz)
    f = setup_features(daily)
    res = {k: trade_stats([t for t in pullback_trades(f, f[col]) if t["entry"] >= start])
           for k, col in (("all", "fired"), ("grade_a", "grade_a"), ("random_same_exit", "uptrend"))}
    res["window"] = [str(start.date()), str(daily.index[-1].date())] if len(daily) else None
    return res


def pullback_setup(daily):
    """State of the setup on the LAST bar of `daily` (pass completed sessions only)."""
    S = SETUP; n = len(daily)
    if n == 0: return {"status": "no_data"}
    f = setup_features(daily); x = f.iloc[-1]
    last_fire = f.index[f.fired.values]
    out = {"bar_date": str(f.index[-1].date()), "bars": n, "close": num(x.c, 2), "sma200": num(x.sma200, 2),
           "sma5": num(x.sma5, 2), "rsi2": num(x.rsi2, 1), "adx": num(x.adx, 1),
           "last_fired": str(last_fire[-1].date()) if len(last_fire) else None}
    if n < S["trend_sma"] or pd.isna(x.sma200):
        out.update(status="insufficient_history", fired=False,
                   reason=f"only {n} daily bars; SMA({S['trend_sma']}) needs {S['trend_sma']}")
        return out
    out.update(status="ok", above_sma200=bool(x.c > x.sma200), fired=bool(x.fired),
               grade=("A" if bool(x.grade_a) else "B") if bool(x.fired) else None)
    return out


def completed_sessions(daily, now_ny):
    """Drop today's still-forming daily bar during the US session (before 16:00 ET)."""
    if len(daily) and daily.index[-1].date() == now_ny.date() and (now_ny.hour, now_ny.minute) < (16, 0):
        return daily.iloc[:-1]
    return daily
