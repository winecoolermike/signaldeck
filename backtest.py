#!/usr/bin/env python3
"""SignalDeck backtest: how often did each signal call the next move correctly over the past year?

Uses the SAME signal code as the live dashboard (signals.py: frame_signal, bias_conf, levels),
recomputed day by day / bar by bar using only the data that existed at that bar's close
(the trailing window the live builder would have fetched: 2y of daily bars, 730d of 60m bars).
Forward returns use closes strictly after the signal bar. Real Yahoo Finance data only; anything
that cannot be computed is null. Writes site/backtest.json.   Not financial advice.
"""
import json, math, sys, datetime as dt, warnings, traceback
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd, yfinance as yf
from signals import ROOT, CFG, num, frame_signal, levels, history

warnings.filterwarnings("ignore")
OUT = ROOT / "site" / "backtest.json"
SIGNAL_DAYS = 252            # ~1 trading year of daily signals
DAILY_H = [1, 5, 10]         # forward horizons, trading days
H60 = [1, 4, 7]              # forward horizons, 60m bars (7 bars ~ 1 session)
H60_SPAN_DAYS = 365          # 60m signals over the last ~1 year
LEVEL_DAYS = 10
MIN_N = 30                   # below this a result is flagged "too few to trust"
BUCKETS = [("<60", 0, 59), ("60-79", 60, 79), ("80+", 80, 100)]
TF = {t["key"]: t for t in CFG["timeframes"]}


def _logpmf(i, n, p):
    return math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * math.log(p) + (n - i) * math.log(1 - p)

def binom_sf(k, n, p):
    """P(X >= k) for X ~ Binomial(n, p): one-sided p-value that hits beat chance (exact, log-space)."""
    if n == 0 or p is None: return None
    p = min(max(p, 1e-12), 1 - 1e-12)
    return min(1.0, sum(math.exp(_logpmf(i, n, p)) for i in range(k, n + 1)))

def binom_cdf(k, n, p):
    """P(X <= k): one-sided p-value that hits were WORSE than chance."""
    if n == 0 or p is None: return None
    p = min(max(p, 1e-12), 1 - 1e-12)
    return min(1.0, sum(math.exp(_logpmf(i, n, p)) for i in range(0, k + 1)))


def pvals(hits, n, p, h):
    """Overlap-adjusted one-sided binomial p-values. Forward windows of h bars overlap, so consecutive
    outcomes are not independent; we conservatively shrink the sample to n/h independent trials."""
    if not n or p is None: return None, None, 0
    ne = max(1, round(n / h)); ke = round(hits * ne / n)
    return binom_sf(ke, ne, p), binom_cdf(ke, ne, p), ne


def window(df, i, lookback):
    """Bars the live builder would have had at bar i's close: (t_i - lookback, t_i]."""
    t = df.index[i]
    return df.loc[(df.index > t - lookback) & (df.index <= t)]


def signal_series(df, idx, lookback):
    rows = []
    for i in idx:
        w = window(df, i, lookback)
        s = frame_signal(w)
        rows.append({"i": i, "t": df.index[i], "bias": s.get("bias"), "conf": s.get("confidence"),
                     "score": s.get("score"), "bars": len(w), "missing": s.get("missing") or []})
    return pd.DataFrame(rows)


def fwd(close, i, h):
    j = i + h
    return float(close.iloc[j] / close.iloc[i] - 1) if j < len(close) else None


def stats(sig, close, horizons, label_unit):
    """Hit rates per bias + baselines for each horizon."""
    out = {}
    for h in horizons:
        r = sig["i"].map(lambda i: fwd(close, i, h))
        d = sig.assign(r=r).dropna(subset=["r"])
        d = d[d.bias.notna()]
        n_all = len(d)
        if n_all == 0:
            out[str(h)] = {"n": 0}; continue
        p_up = float((d.r > 0).mean()); p_dn = float((d.r < 0).mean())
        res = {"n": n_all, "unit": label_unit, "p_up": num(p_up, 4), "p_down": num(p_dn, 4),
               "always_call_hit": num(p_up, 4), "avg_ret_all": num(d.r.mean(), 5)}
        for b in ("CALL", "PUT", "NEUT"):
            x = d[d.bias == b]
            e = {"n": len(x), "avg_ret": num(x.r.mean(), 5) if len(x) else None,
                 "pct_up": num((x.r > 0).mean(), 4) if len(x) else None}
            if b != "NEUT":
                hits = int((x.r > 0).sum() if b == "CALL" else (x.r < 0).sum())
                base = p_up if b == "CALL" else p_dn
                e.update(hits=hits, hit_rate=num(hits / len(x), 4) if len(x) else None, baseline=num(base, 4),
                         edge_pts=num((hits / len(x) - base) * 100, 1) if len(x) else None,
                         p_value=num(pvals(hits, len(x), base, h)[0], 4) if len(x) else None,
                         few=len(x) < MIN_N)
            else:
                e["few"] = len(x) < MIN_N
            res[b] = e
        dirn = d[d.bias.isin(["CALL", "PUT"])]
        hits = int(((dirn.bias == "CALL") & (dirn.r > 0)).sum() + ((dirn.bias == "PUT") & (dirn.r < 0)).sum())
        nd = len(dirn)
        exp = ((dirn.bias == "CALL").sum() * p_up + (dirn.bias == "PUT").sum() * p_dn) / nd if nd else None
        pb, pw, ne = pvals(hits, nd, exp, h)
        res["directional"] = {"n_effective": ne, "n": nd, "hits": hits, "hit_rate": num(hits / nd, 4) if nd else None,
                              "chance_same_mix": num(exp, 4), "always_call": num(p_up, 4),
                              "best_constant_guess": num(max(p_up, p_dn), 4),
                              "edge_vs_chance_pts": num((hits / nd - exp) * 100, 1) if nd else None,
                              "p_value": num(pb, 4), "p_value_worse": num(pw, 4), "few": nd < MIN_N}
        # confidence buckets (directional signals only; NEUT reported separately)
        bk = []
        for name, lo, hi in BUCKETS:
            x = dirn[(dirn.conf >= lo) & (dirn.conf <= hi)]
            hh = int(((x.bias == "CALL") & (x.r > 0)).sum() + ((x.bias == "PUT") & (x.r < 0)).sum())
            ex = ((x.bias == "CALL").sum() * p_up + (x.bias == "PUT").sum() * p_dn) / len(x) if len(x) else None
            bk.append({"bucket": name, "n": len(x), "hits": hh, "hit_rate": num(hh / len(x), 4) if len(x) else None,
                       "chance_same_mix": num(ex, 4), "few": len(x) < MIN_N})
        res["conf_buckets"] = bk
        out[str(h)] = res
    return out


def level_test(daily, sig, lookback):
    """For CALL (long) / PUT (short) days: within 10 days, did price reach MAIN Potential Exit
    before the Extended Entry (treated as a stop)? Entry assumed at the signal day's close.
    Same-day touches of both can't be ordered with daily bars and are reported separately."""
    def run(rows, direction):
        c = {"n": 0, "target_first": 0, "stop_first": 0, "same_day_both": 0, "neither": 0}
        for _, s in rows.iterrows():
            i = int(s.i)
            if i + 1 >= len(daily): continue
            lv = levels(window(daily, i, lookback), direction)
            if not lv or lv["main_exit"] is None or lv["ext_entry"] is None: continue
            tgt, stop = lv["main_exit"], lv["ext_entry"]
            fut = daily.iloc[i + 1:i + 1 + LEVEL_DAYS]
            if len(fut) < LEVEL_DAYS: continue          # need the full 10-day window
            c["n"] += 1; outcome = "neither"
            for _, b in fut.iterrows():
                th = b.High >= tgt if direction > 0 else b.Low <= tgt
                st = b.Low <= stop if direction > 0 else b.High >= stop
                if th and st: outcome = "same_day_both"; break
                if th: outcome = "target_first"; break
                if st: outcome = "stop_first"; break
            c[outcome] += 1
        n = c["n"]
        c.update({k + "_pct": num(c[k] / n, 4) if n else None for k in ("target_first", "stop_first", "same_day_both", "neither")})
        c["few"] = n < MIN_N
        return c
    s = sig[sig.bias.notna()]
    return {"call_long": run(s[s.bias == "CALL"], 1), "put_short": run(s[s.bias == "PUT"], -1),
            "baseline_long_every_day": run(s, 1), "baseline_short_every_day": run(s, -1)}


def backtest_ticker(sym):
    tk = yf.Ticker(sym)
    out = {"ticker": sym, "status": "ok", "notes": []}
    # ---- daily (Main) ----
    daily = history(tk, "1d", "5y")
    if daily.empty:
        return {"ticker": sym, "status": "no_data", "notes": ["No daily history from Yahoo Finance."]}
    lb = pd.DateOffset(years=2)                                    # live builder fetches period=2y
    start = max(0, len(daily) - SIGNAL_DAYS)
    sig = signal_series(daily, range(start, len(daily)), lb)
    valid = sig[sig.bias.notna()]
    out["daily"] = {"bars_available": len(daily), "first_bar": str(daily.index[0].date()),
                    "signal_days": len(valid), "from": str(valid.t.iloc[0].date()) if len(valid) else None,
                    "to": str(valid.t.iloc[-1].date()) if len(valid) else None,
                    "bias_counts": {b: int((valid.bias == b).sum()) for b in ("CALL", "PUT", "NEUT")},
                    "horizons": stats(valid, daily.Close, DAILY_H, "trading days"),
                    "levels": level_test(daily, valid, lb)}
    miss = sorted({m for ms in valid.missing for m in ms})
    if miss: out["notes"].append(f"Daily: some signal days lacked enough history for {', '.join(miss)} (skipped and reweighted, exactly as live).")
    if len(daily) < SIGNAL_DAYS + 200:
        out["notes"].append(f"Only {len(daily)} daily bars exist (since {daily.index[0].date()}), so the year-long test is incomplete for this ticker.")
    out["small_sample"] = len(valid) < SIGNAL_DAYS * 0.75
    # ---- 60m on its own ----
    try:
        h = history(tk, "60m", TF["60m"]["period"])
        if len(h):
            cutoff = h.index[-1] - pd.Timedelta(days=H60_SPAN_DAYS)
            idx = [i for i in range(len(h)) if h.index[i] > cutoff]
            s60 = signal_series(h, idx, pd.Timedelta(days=730))
            v60 = s60[s60.bias.notna()]
            out["h60"] = {"bars_available": len(h), "signal_bars": len(v60),
                          "from": str(v60.t.iloc[0].date()) if len(v60) else None, "to": str(v60.t.iloc[-1].date()) if len(v60) else None,
                          "bias_counts": {b: int((v60.bias == b).sum()) for b in ("CALL", "PUT", "NEUT")},
                          "horizons": stats(v60, h.Close, H60, "60m bars")}
        else:
            out["h60"] = None; out["notes"].append("60m: no intraday history returned.")
    except Exception as e:
        out["h60"] = None; out["notes"].append(f"60m: error {e}")
    return out


def summary(tickers):
    """Plain-language findings derived only from the computed numbers (5-day horizon headline)."""
    lines, pooled_h, pooled_e, pooled_n = [], 0, 0.0, 0
    for t in tickers:
        if t.get("status") != "ok": lines.append(f"{t['ticker']}: no data."); continue
        r = t["daily"]["horizons"].get("5", {}); d = r.get("directional", {})
        if not d.get("n"):
            lines.append(f"{t['ticker']}: no directional signals to score."); continue
        hr, ch, pv = d["hit_rate"] * 100, d["chance_same_mix"] * 100, d["p_value"]
        pw = d.get("p_value_worse")
        verdict = ("beat chance by a statistically meaningful margin" if pv is not None and pv < 0.05 and hr > ch
                   else "did slightly better than chance, but not by enough to rule out luck" if hr > ch
                   else "did WORSE than chance - the move tended to reverse" if pw is not None and pw < 0.05
                   else "did worse than chance, though not by a statistically conclusive margin" if hr < ch - 3
                   else "did no better than chance")
        tag = " (too few signals to trust)" if d["few"] or t.get("small_sample") else ""
        lines.append(f"{t['ticker']}: daily CALL/PUT signals were right {hr:.0f}% of the time over 5 days "
                     f"(n={d['n']}) vs {ch:.0f}% expected from guessing with the same CALL/PUT mix; {verdict}{tag}.")
        if not t.get("small_sample"):
            pooled_h += d["hits"]; pooled_e += d["chance_same_mix"] * d["n"]; pooled_n += d["n"]
    head = None
    if pooled_n:
        ph, pe = pooled_h / pooled_n * 100, pooled_e / pooled_n * 100
        head = (f"Across tickers with a full year of data, daily signals were right {ph:.0f}% of the time over 5 days "
                f"vs {pe:.0f}% by chance (n={pooled_n}, overlapping windows). "
                + ("That is an edge on paper, but small and from one year of one market regime."
                   if ph - pe >= 3 else "In plain terms: the signals describe the trend so far; "
                   "over this year they did not predict the next move better than a coin flip with the same CALL/PUT mix."))
    # pooled confidence buckets (5-day) and pooled 60m (4 bars), full-year tickers only
    extra = []
    full = [t for t in tickers if t.get("status") == "ok" and not t.get("small_sample")]
    bk = {}
    for t in full:
        for b in t["daily"]["horizons"].get("5", {}).get("conf_buckets", []):
            a = bk.setdefault(b["bucket"], [0, 0, 0.0])
            a[0] += b["hits"]; a[1] += b["n"]; a[2] += (b["chance_same_mix"] or 0) * b["n"]
    parts = [f"{k}: {v[0]/v[1]*100:.0f}% right vs {v[2]/v[1]*100:.0f}% chance (n={v[1]})" for k, v in bk.items() if v[1]]
    if parts:
        hi, mid = bk.get("80+"), bk.get("60-79")
        if hi and mid and hi[1] and mid[1]:
            better = hi[0] / hi[1] > mid[0] / mid[1]
            parts.append("higher confidence " + ("was somewhat more accurate" if better else "did NOT mean more accurate - 80+ signals were right less often than 60-79"))
        extra.append("By confidence (5-day, pooled): " + "; ".join(parts) + ".")
    h = [t["h60"]["horizons"].get("4", {}).get("directional", {}) for t in full if t.get("h60")]
    h = [x for x in h if x.get("n")]
    if h:
        n = sum(x["n"] for x in h); k = sum(x["hits"] for x in h); e = sum(x["chance_same_mix"] * x["n"] for x in h)
        extra.append(f"60-minute signals (pooled, 4 bars ahead): {k/n*100:.1f}% right vs {e/n*100:.1f}% chance (n={n}) - essentially a coin flip.")
    return {"headline": head, "per_ticker": lines, "extra": extra, "pooled": {"n": pooled_n, "hit_rate": num(pooled_h / pooled_n, 4) if pooled_n else None,
                                                              "chance": num(pooled_e / pooled_n, 4) if pooled_n else None}}


def main():
    out = {"generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
           "as_of_market_date": str(dt.datetime.now(ZoneInfo("America/New_York")).date()),
           "source": f"Yahoo Finance via yfinance {yf.__version__} (unofficial; prices not dividend-adjusted)",
           "params": {"signal_days": SIGNAL_DAYS, "daily_horizons": DAILY_H, "h60_horizons": H60, "h60_span_days": H60_SPAN_DAYS,
                      "level_days": LEVEL_DAYS, "min_n": MIN_N, "buckets": [b[0] for b in BUCKETS],
                      "bias_threshold": CFG["bias_threshold"], "indicator_weights": CFG["indicator_weights"]},
           "skipped_timeframes": {
               "30m/15m/5m": "Yahoo only provides ~60 calendar days (~40 sessions) of these bars, and 200 of them are needed "
                             "before the SMA200 vote even exists. That leaves a few weeks of one market regime with heavily "
                             "overlapping trades - too small to mean anything, so they are not backtested.",
               "1m": "Only ~7 days of 1-minute history exist: not backtestable.",
               "Total (blended)": "The live Total blends all six timeframes, but four of them only have weeks of history, so a "
                                  "year-long backtest of the blend is impossible. The 60m timeframe is backtested on its own instead."},
           "tickers": []}
    for sym in CFG["tickers"]:
        print("backtesting", sym, file=sys.stderr)
        try:
            out["tickers"].append(backtest_ticker(sym))
        except Exception as e:
            traceback.print_exc()
            out["tickers"].append({"ticker": sym, "status": "no_data", "notes": [f"backtest error: {e}"]})
    out["summary"] = summary(out["tickers"])
    OUT.write_text(json.dumps(out, indent=1))
    print("wrote", OUT, file=sys.stderr)


if __name__ == "__main__":
    if sys.argv[1:] == ["--summary-only"]:      # re-derive summary text from an existing backtest.json
        d = json.loads(OUT.read_text()); d["summary"] = summary(d["tickers"]); OUT.write_text(json.dumps(d, indent=1))
    else:
        main()
