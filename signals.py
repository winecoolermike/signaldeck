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
    # Grade A (round 2, variant C2): ticker is in the top `mom_top` of the 23-ticker universe by 12-1 month
    # momentum = close 21 trading days ago / close 252 trading days ago - 1, ranked at the LAST COMPLETED
    # month-end close and applied from that close until the next month-end. Otherwise grade B.
    "mom_lookback": 252, "mom_skip": 21, "mom_top": 10,
    "adx_len": 14,              # ADX(14) is shown as information only (it no longer sets the grade)
    "exit_sma": 5, "max_hold": 10,  # exit: first daily close > SMA(5), or after 10 trading days
    "atr_len": 14, "stop_atr_mult": 3,   # OPTIONAL disaster stop = signal close - 3 x ATR(14); not part of the rule
    "size_risk_atr": 0.02, "size_cap": 2.0,  # size hint (research A12): weight = min(2, 2% / ATR%)
    "cost_per_side": 0.0005,     # 0.05% per side, applied to "net" numbers
    "oos_start": "2023-01-01",   # out-of-sample window used for all reported stats
    "min_trades": 30,            # fewer trades -> "too few to trust"
    "price_basis": "split- and dividend-adjusted daily bars (as in the research)",
}
def universe_from_config(cfg):
    """Scan universe, config-driven and de-duplicated in order: This Week tickers, the 16 comparison tickers, then the
    scan_universe ETFs and S&P 100 list (research round 4). Without a scan_universe block it is the original 23."""
    su = cfg.get("scan_universe") or {}
    return list(dict.fromkeys(cfg["tickers"] + cfg["comparison_tickers"] + su.get("etfs", []) + su.get("sp100", [])))

UNIVERSE = universe_from_config(CFG)


# ---------------- trading calendar (NYSE full-day holidays; used only to know if the last bar ends a month) ----------
def _easter(y):
    a = y % 19; b, c = divmod(y, 100); d, e = divmod(b, 4); g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30; j, k = divmod(c, 4); m = (a + 11 * h) // 319
    r = (2 * e + 2 * j - k - h + m + 32) % 7; n = (h - m + r + 90) // 25; p = (h - m + r + n + 19) % 32
    return pd.Timestamp(y, n, p)

def nyse_holidays(year):
    from pandas.tseries.holiday import USFederalHolidayCalendar
    hs = USFederalHolidayCalendar().holidays(f"{year - 1}-12-01", f"{year + 1}-01-31")
    drop = {pd.Timestamp(year, 10, d) for d in range(8, 15)} | {pd.Timestamp(year, 11, 10), pd.Timestamp(year, 11, 11), pd.Timestamp(year, 11, 12)}
    out = {h for h in hs if h.year == year and h not in drop
           and not (h.month == 12 and h.day == 31)}        # NYSE does not observe New Year's Day on the prior Friday
    if year < 2022: out = {h for h in out if not (h.month == 6 and 18 <= h.day <= 21)}   # Juneteenth from 2022
    out.add(_easter(year) - pd.Timedelta(days=2))          # Good Friday
    return out

def is_trading_day(d):
    d = pd.Timestamp(d).normalize()
    return d.weekday() < 5 and d not in nyse_holidays(d.year)

def next_trading_day(d):
    d = pd.Timestamp(d).normalize() + pd.Timedelta(days=1)
    while not is_trading_day(d): d += pd.Timedelta(days=1)
    return d


# ---------------- 12-1 momentum rank across the universe (causal) -------------
def momentum(close):
    S = SETUP
    return close.shift(S["mom_skip"]) / close.shift(S["mom_lookback"]) - 1

def momentum_ranks(closes, last_bar_complete_month=None, overrides=None):
    """closes: {symbol: adjusted daily close Series (completed sessions only, tz-naive dates)}.
    Returns (rank, asof, mom_at_me): rank[s] at each date = rank (1 = strongest) of s among the universe by 12-1
    momentum at the latest month-end close <= that date; asof = that month-end date; NaN before the first one.
    Month-end = a bar whose next bar is in another month (as in the research). For the LAST bar, which has no next bar,
    the trading calendar decides (so the last trading day of a month counts from its own close).
    overrides: {symbol: momentum value} used at the latest month-end for symbols whose data could not be refreshed."""
    idx = pd.DatetimeIndex(sorted(set().union(*[set(c.index) for c in closes.values()])))
    MOM = pd.DataFrame({s: momentum(c) for s, c in closes.items()}).reindex(idx)
    per = idx.to_period("M")
    mend = np.r_[per[1:] != per[:-1], False]
    if len(idx):
        mend[-1] = next_trading_day(idx[-1]).month != idx[-1].month if last_bar_complete_month is None else bool(last_bar_complete_month)
    ME = idx[mend]
    M = MOM.loc[ME].copy()
    if overrides and len(ME):
        for s, v in overrides.items():
            if s not in M.columns: M[s] = np.nan
            if pd.isna(M.loc[ME[-1], s]) and v is not None: M.loc[ME[-1], s] = v
    R = M.rank(axis=1, ascending=False)
    rank = R.reindex(idx).ffill()
    asof = pd.Series(pd.NaT, index=idx); asof[ME] = ME; asof = asof.ffill()
    return rank, asof, M


def setup_features(daily, mrank=None):
    """Causal features for the Pullback setup: every value at bar t uses bars <= t only.
    mrank: this ticker's momentum-rank Series (from momentum_ranks), aligned by date; None -> grade B everywhere."""
    S = SETUP; c = daily.Close
    f = pd.DataFrame(index=daily.index)
    f["c"] = c
    f["sma200"] = c.rolling(S["trend_sma"]).mean()
    f["sma5"] = c.rolling(S["exit_sma"]).mean()
    f["rsi2"] = rsi(c, S["rsi_len"])
    f["adx"] = adx(daily, S["adx_len"])
    f["atr"] = atr(daily, S["atr_len"])
    f["mrank"] = (pd.Series(np.asarray(mrank.reindex(_naive(daily.index)), float), daily.index) if mrank is not None
                  else pd.Series(np.nan, daily.index))
    f["fired"] = (f.c > f.sma200) & (f.rsi2 < S["rsi_max"])          # NaN comparisons -> False
    f["grade_a"] = f.fired & (f.mrank <= S["mom_top"])
    f["uptrend"] = f.c > f.sma200                                     # same-exit random baseline entries
    return f


def _naive(idx):
    return idx.tz_localize(None).normalize() if getattr(idx, "tz", None) is not None else idx


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


def pullback_ticker_stats(daily, mrank=None, start=None):
    """This ticker's own out-of-sample stats (entries from SETUP['oos_start'] on) for both grades plus
    the same-exit random baseline (enter on every uptrend close, same exit)."""
    start = pd.Timestamp(start or SETUP["oos_start"])
    if len(daily) and daily.index.tz is not None: start = start.tz_localize(daily.index.tz)
    f = setup_features(daily, mrank)
    res = {k: trade_stats([t for t in pullback_trades(f, f[col]) if t["entry"] >= start])
           for k, col in (("all", "fired"), ("grade_a", "grade_a"), ("random_same_exit", "uptrend"))}
    res["window"] = [str(start.date()), str(daily.index[-1].date())] if len(daily) else None
    return res


def pullback_setup(daily, mrank=None, rank_asof=None, rank_of=None):
    """State of the setup on the LAST bar of `daily` (pass completed sessions only)."""
    S = SETUP; n = len(daily)
    if n == 0: return {"status": "no_data"}
    f = setup_features(daily, mrank); x = f.iloc[-1]
    last_fire = f.index[f.fired.values]
    d0 = _naive(daily.index)[-1]
    ra = rank_asof.get(d0) if rank_asof is not None else None
    atrp = x.atr / x.c if x.c else np.nan
    out = {"bar_date": str(f.index[-1].date()), "bars": n, "close": num(x.c, 2), "sma200": num(x.sma200, 2),
           "sma5": num(x.sma5, 2), "rsi2": num(x.rsi2, 1), "adx": num(x.adx, 1),
           "mom_rank": None if pd.isna(x.mrank) else int(round(x.mrank)), "mom_rank_of": rank_of,
           "mom_asof": None if ra is None or pd.isna(ra) else str(pd.Timestamp(ra).date()),
           "in_top": bool(x.mrank <= S["mom_top"]) if not pd.isna(x.mrank) else False,
           "atr14": num(x.atr, 3), "atr_pct": num(atrp * 100, 2),
           "stop_3atr": num(x.c - S["stop_atr_mult"] * x.atr, 2),
           "size_mult": num(min(S["size_cap"], S["size_risk_atr"] / atrp), 2) if atrp and not pd.isna(atrp) else None,
           "last_fired": str(last_fire[-1].date()) if len(last_fire) else None}
    if n < S["trend_sma"] or pd.isna(x.sma200):
        out.update(status="insufficient_history", fired=False, grade=None,
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


# ---------------- intraday rows (round 3): 15m EMA9 vs EMA21, 5m/1m close vs session VWAP ----------------
# Definitions copied from research/research3.py feats() + descriptors3.py states(); completed bars only.
ROWS = {"15m": {"kind": "ema9_21", "minutes": 15}, "5m": {"kind": "vwap", "minutes": 5}, "1m": {"kind": "vwap", "minutes": 1}}

def _to_ny(idx):
    return idx.tz_convert(NY) if idx.tz is not None else idx.tz_localize(NY)

def completed_bars(df, minutes, now_ny):
    """Regular-session bars (09:30-16:00 ET) whose end time (start + bar length) is <= now. Excludes the bar still forming."""
    if not len(df): return df
    now_ny = pd.Timestamp(now_ny)
    idx = _to_ny(df.index); df = df.set_axis(idx)
    hm = idx.hour * 60 + idx.minute
    df = df[(hm >= 570) & (hm < 960) & df.Close.notna()]
    end = df.index + pd.Timedelta(minutes=minutes)
    return df[end <= now_ny]

def early_close(d):
    """NYSE 13:00 ET early closes: July 3 (when it is a trading day), the day after Thanksgiving, Dec 24 (when a trading day)."""
    d = pd.Timestamp(d).normalize()
    if not is_trading_day(d): return False
    nov = pd.date_range(f"{d.year}-11-01", f"{d.year}-11-30"); thanks = nov[nov.weekday == 3][3]
    return (d.month, d.day) in ((7, 3), (12, 24)) or d == thanks + pd.Timedelta(days=1)

def close_minutes(d):
    """Regular-session close in minutes after midnight ET for trading day d (960 = 16:00, 780 = 13:00)."""
    return 780 if early_close(d) else 960

def session_open(now_ny):
    """True on a trading day between 09:30 ET and the close (16:00, or 13:00 on early-close days)."""
    now_ny = pd.Timestamp(now_ny); hm = now_ny.hour * 60 + now_ny.minute; d = now_ny.tz_localize(None).normalize()
    return is_trading_day(d) and 570 <= hm < close_minutes(d)

def market_status(now_ny):
    """{state: open|pre|after|closed, label, next_open, closes_at}. Pre-market 04:00-09:30, after-hours to 20:00 ET."""
    now_ny = pd.Timestamp(now_ny); d = now_ny.tz_localize(None).normalize(); hm = now_ny.hour * 60 + now_ny.minute
    td = is_trading_day(d); cm = close_minutes(d) if td else None
    if td and 570 <= hm < cm: st = "open"
    elif td and 240 <= hm < 570: st = "pre"
    elif td and cm <= hm < 1200: st = "after"
    else: st = "closed"
    nxt = d if td and hm < 570 else next_trading_day(d)
    lab = {"open": "Market open", "pre": "Pre-market", "after": "After hours", "closed": "Market closed"}[st]
    return {"state": st, "label": lab, "early_close": bool(td and cm == 780),
            "closes_at": f"{cm // 60:02d}:{cm % 60:02d} ET" if st == "open" else None,
            "next_open": f"{nxt.date()} 09:30 ET" if st != "open" else None}

def calendar_lists(years):
    """Holidays and early closes for the given years (the front end uses them for the live market-status chip)."""
    hol = sorted(str(h.date()) for y in years for h in nyse_holidays(y))
    days = pd.date_range(f"{min(years)}-01-01", f"{max(years)}-12-31")
    return {"holidays": hol, "early_closes": [str(x.date()) for x in days if x.weekday() < 5 and early_close(x)]}


# ---------------- home page sections (config "home") -------------
def home_sections(rows, this_week, top):
    """rows: scanner rows (ticker, fired, grade, mom_rank, status). Returns the ordered home sections:
    firing  = every ticker whose pullback setup fires on the last completed close (Grade A first, then by rank),
    leaders = the current top `top` by 12-1 momentum rank (where Grade A setups come from), by rank,
    this_week = the user's own list, in config order (always shown, data or not)."""
    by = {r["ticker"]: r for r in rows}
    rk = lambda r: (r.get("mom_rank") is None, r.get("mom_rank") or 0, r["ticker"])
    fire = sorted([r for r in rows if r.get("fired")], key=lambda r: (r.get("grade") != "A",) + rk(r))
    lead = sorted([r for r in rows if r.get("mom_rank") is not None and r["mom_rank"] <= top], key=rk)
    return [{"key": "firing", "tickers": [r["ticker"] for r in fire]},
            {"key": "leaders", "tickers": [r["ticker"] for r in lead]},
            {"key": "this_week", "tickers": list(this_week), "missing": [t for t in this_week if t not in by]}]

def ema_state(df, minutes, now_ny):
    """15m row: Up if EMA9 > EMA21 of completed-bar closes (EMAs run continuously across sessions), Down if below.
    since = end time of the first bar of the current unbroken state run."""
    b = completed_bars(df, minutes, now_ny)
    if len(b) < 21: return {"kind": "ema9_21", "status": "insufficient", "score": None, "bars": len(b)}
    e9, e21 = ema(b.Close, 9), ema(b.Close, 21)
    st = np.sign((e9 - e21).values)
    cur = st[-1]; j = len(st) - 1
    while j > 0 and st[j - 1] == cur: j -= 1
    end = lambda i: b.index[i] + pd.Timedelta(minutes=minutes)
    return {"kind": "ema9_21", "status": "ok", "score": int(cur), "dir": int(cur),
            "state": "Up" if cur > 0 else "Down" if cur < 0 else "Flat",
            "ema9": num(e9.iloc[-1], 3), "ema21": num(e21.iloc[-1], 3),
            "since": end(j).isoformat(), "since_is_lower_bound": bool(j == 0),
            "last_bar_end": end(len(b) - 1).isoformat(), "bars": len(b)}

def vwap_state(df, minutes, now_ny):
    """5m/1m rows: close of the last completed bar vs session VWAP (typical price x volume, cumulative from 09:30 ET of
    that bar's session; zero volume -> weight 1e-9 as in the research). Above = +1, Below = -1, exact tie = 0.
    During market hours before today's first bar has closed -> status 'waiting' (no score)."""
    b = completed_bars(df, minutes, now_ny)
    if session_open(now_ny) and (not len(b) or b.index[-1].date() != now_ny.date()):
        return {"kind": "vwap", "status": "waiting", "score": None, "session": str(now_ny.date())}
    if not len(b): return {"kind": "vwap", "status": "insufficient", "score": None, "bars": 0}
    day = b.index[-1].date(); s = b[b.index.date == day]
    tp = (s.High + s.Low + s.Close) / 3; v = s.Volume.clip(lower=0).fillna(0); v = v.where(v > 0, 1e-9)
    vw = float((tp * v).sum() / v.sum()); c = float(s.Close.iloc[-1])
    sc = int(np.sign(c - vw))
    return {"kind": "vwap", "status": "ok", "score": sc, "dir": sc,
            "state": "Above" if sc > 0 else "Below" if sc < 0 else "At",
            "vwap": num(vw, 3), "close": num(c, 3), "dist_pct": num((c / vw - 1) * 100, 2),
            "session": str(day), "bars_today": len(s), "live_session": bool(day == now_ny.date() and session_open(now_ny)),
            "last_bar_end": (s.index[-1] + pd.Timedelta(minutes=minutes)).isoformat()}
