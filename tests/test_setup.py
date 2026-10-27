"""Unit tests for the Pullback setup, momentum grading and intraday rows
(python -m pytest tests  or  python tests/test_setup.py).

Uses small committed fixtures of real Yahoo bars (adjusted daily closes for the 23-ticker universe, SPY/AMZN daily
OHLCV, SPY 5m/15m), never live data. Expected values were computed by the research code (research2.py / research3.py).
"""
import sys, json
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from signals import (SETUP, UNIVERSE, NY, setup_features, pullback_setup, pullback_trades, pullback_ticker_stats,
                     completed_sessions, momentum_ranks, next_trading_day, is_trading_day, ema,
                     completed_bars, vwap_state, ema_state)

FX = ROOT / "tests" / "fixtures"
FIX = FX / "SPY_1d_adjusted.csv"
J = lambda n: json.loads((FX / n).read_text())


def closes23():
    c = pd.read_csv(FX / "universe23_close_adjusted.csv", index_col=0, parse_dates=True)
    return {s: c[s].dropna() for s in c.columns}

def intra(name):
    d = pd.read_csv(FX / name, index_col=0)
    d.index = pd.to_datetime(d.index, utc=True).tz_convert(NY)
    return d

def ny(s):
    return pd.Timestamp(s, tz=NY)


def spy():
    return pd.read_csv(FIX, index_col=0, parse_dates=True)


def test_known_spy_triggers():
    d = spy(); E = json.loads((ROOT / "tests" / "fixtures" / "expected.json").read_text())
    for t in E["triggers"]:
        day = pd.Timestamp(t["date"])
        st = pullback_setup(d.loc[:day])                   # data only up to that close
        assert st["status"] == "ok" and st["fired"] is True and st["bar_date"] == t["date"], st
        assert st["close"] > st["sma200"] and st["rsi2"] < SETUP["rsi_max"]
        assert st["grade"] == "B", st                      # no momentum rank supplied -> never grade A
    st = pullback_setup(d.loc[:E["not_fired"]])
    assert st["fired"] is False and st["grade"] is None


def test_no_lookahead():
    """The state on day t computed from bars <= t equals the full-history flag at t."""
    d = spy(); f = setup_features(d)
    for day in list(f.index[f.fired][:5]) + list(f.index[~f.fired & f.sma200.notna()][:5]):
        st = pullback_setup(d.loc[:day])
        assert st["fired"] == bool(f.fired.loc[day]), day


def test_not_fired_and_short_history():
    d = spy(); f = setup_features(d)
    day = f.index[(f.c < f.sma200) & (f.rsi2 < SETUP["rsi_max"])][0]   # oversold but below SMA200
    st = pullback_setup(d.loc[:day]); assert st["fired"] is False and st["above_sma200"] is False
    st = pullback_setup(d.iloc[:150]); assert st["status"] == "insufficient_history" and st["fired"] is False


def test_exit_rule():
    d = spy(); f = setup_features(d)
    for t in pullback_trades(f, f.fired):
        k = f.index.get_loc(t["exit"]); i = f.index.get_loc(t["entry"])
        assert 1 <= k - i <= SETUP["max_hold"]
        assert f.c.iloc[k] > f.sma5.iloc[k] or k - i == SETUP["max_hold"]
        assert all(f.c.iloc[j] <= f.sma5.iloc[j] for j in range(i + 1, k))   # first close above SMA5


def test_completed_sessions():
    d = spy(); last = d.index[-1]
    assert len(completed_sessions(d, pd.Timestamp(last.date()) + pd.Timedelta(hours=11))) == len(d) - 1
    assert len(completed_sessions(d, pd.Timestamp(last.date()) + pd.Timedelta(hours=16, minutes=5))) == len(d)


def test_matches_research_if_present():
    """If local research results exist, the shared code must reproduce the per-ticker OOS numbers."""
    rp = ROOT / "research" / "results_stage2.json"; dp = ROOT / "research" / "data"
    if not rp.exists(): return
    R = json.loads(rp.read_text())["selected"]
    for sym in ["AMT", "CCI", "SBAC", "VZ", "T", "TMUS", "SPY", "WMT"]:
        p = dp / f"{sym}_1d.pkl"
        if not p.exists(): continue
        d = pd.read_pickle(p)
        s = pullback_ticker_stats(d)
        ref = R["pb_long_rsi2<10_xSMA5"]["per_ticker_test"][sym]
        assert s["all"]["n"] == ref["n"], (sym, s["all"]["n"], ref["n"])
        if ref["n"]:
            assert abs(s["all"]["hit"] - ref["hit"]) < 1e-3 and abs(s["all"]["exp_net_pct"] - ref["exp_net_pct"]) < 2e-3, sym


def test_grade_a_matches_round2_if_present():
    """With local research data, momentum-graded (C2) per-ticker OOS stats must equal research2.py's."""
    rp = ROOT / "research" / "results_round2.json"; dp = ROOT / "research" / "data"
    if not rp.exists() or not all((dp / f"{s}_1d.pkl").exists() for s in UNIVERSE): return
    R = json.loads(rp.read_text())["C"]["C2 pullback in top-10 momentum"]["per_ticker_test"]
    D = {s: pd.read_pickle(dp / f"{s}_1d.pkl") for s in UNIVERSE}
    rank, _, _ = momentum_ranks({s: d.Close for s, d in D.items()}, last_bar_complete_month=False)
    for sym in ["AMT", "CCI", "SBAC", "VZ", "T", "TMUS"]:
        g = pullback_ticker_stats(D[sym], rank[sym])["grade_a"]; ref = R[sym]
        assert g["n"] == ref["n"], (sym, g["n"], ref["n"])
        if ref["n"]: assert abs(g["hit"] - ref["hit"]) < 1e-3 and abs(g["exp_net_pct"] - ref["exp_net_pct"]) < 2e-3, sym


# ---------------- momentum rank (Grade A) ----------------
def test_momentum_ranks_match_research():
    E = J("expected_momentum.json"); C = closes23()
    assert set(C) <= set(UNIVERSE) and len(C) == 23    # fixture = the original 23 (still part of the scan universe)
    rank, asof, M = momentum_ranks(C)
    for day, exp in E["ranks"].items():
        for s, r in exp.items():
            got = rank.loc[day, s]
            assert (r is None and pd.isna(got)) or got == r, (day, s, got, r)
    for day, me in E["rank_asof"].items():
        assert str(asof.loc[day].date()) == me, (day, asof.loc[day])
    assert M.loc["2023-08-31"].notna().sum() == 22          # SPCX has no 12-1 momentum -> ranks are "of 22"


def test_grade_by_rank_on_historical_dates():
    """AMZN fired on both dates; rank 10 (inclusive) -> A, rank 14 after the Aug month-end re-rank -> B."""
    E = J("expected_momentum.json"); C = closes23()
    amzn = pd.read_csv(FX / "AMZN_1d_adjusted.csv", index_col=0, parse_dates=True)
    for t in E["amzn_triggers"]:
        day = t["date"]
        Ct = {s: c.loc[:day] for s, c in C.items()}                     # universe data only up to that close
        rank, asof, M = momentum_ranks(Ct)
        st = pullback_setup(amzn.loc[:day], rank["AMZN"], asof, int(M.iloc[-1].notna().sum()))
        assert st["fired"] is True and st["bar_date"] == day, st
        assert st["mom_rank"] == t["rank"] and st["grade"] == t["grade"] and st["mom_rank_of"] == 22, st
        assert abs(st["stop_3atr"] - (st["close"] - 3 * st["atr14"])) < 0.02
    st = pullback_setup(amzn.loc[:"2023-08-17"])                         # no rank -> B
    assert st["grade"] == "B" and st["mom_rank"] is None


def test_momentum_no_lookahead():
    """Rank on day t from data <= t equals the full-history rank at t, including around a month-end close."""
    C = closes23(); full, fa, _ = momentum_ranks(C)
    for day in ["2023-07-28", "2023-07-31", "2023-08-01", "2023-08-17", "2023-08-30", "2023-08-31", "2023-09-01"]:
        r, a, _ = momentum_ranks({s: c.loc[:day] for s, c in C.items()})
        x, y = r.iloc[-1], full.loc[day]
        assert ((x == y) | (x.isna() & y.isna())).all(), day
        assert a.iloc[-1] == fa.loc[day], day
    # changing a future price must not change today's rank
    C2 = {s: c.copy() for s, c in C.items()}; C2["AMZN"].loc["2023-09-01":] *= 3
    r2, _, _ = momentum_ranks(C2)
    assert ((r2.loc[:"2023-08-31"] == full.loc[:"2023-08-31"]) | full.loc[:"2023-08-31"].isna()).all().all()


def test_month_end_calendar():
    assert next_trading_day("2026-10-30") == pd.Timestamp("2026-11-02")     # Fri Oct 30 = last trading day of Oct
    assert next_trading_day("2024-03-28") == pd.Timestamp("2024-04-01")     # Good Friday 2024-03-29
    assert not is_trading_day("2026-04-03") and not is_trading_day("2026-11-26") and is_trading_day("2026-10-12")
    assert not is_trading_day("2026-07-03") and is_trading_day("2021-12-31")   # observed July 4; no NYE closure


# ---------------- intraday rows (round 3) ----------------
def test_vwap_row_matches_research_and_waits():
    d = intra("SPY_5m.csv"); E = J("expected_rows.json")["vwap_5m"]
    st = vwap_state(d, 5, ny("2026-10-23 17:00"))                           # after the close: whole session
    assert st["status"] == "ok" and abs(st["vwap"] - E["2026-10-23 15:55:00-04:00"]) < 1e-3 and st["bars_today"] == 78
    assert st["score"] == (1 if st["close"] > st["vwap"] else -1) and st["state"] in ("Above", "Below")
    assert np.sign(st["dist_pct"]) == st["score"]
    mid = vwap_state(d, 5, ny("2026-10-23 10:02"))                           # 09:55 bar ends 10:00 (in); 10:00 bar still forming
    assert mid["bars_today"] == 6 and abs(mid["vwap"] - E["2026-10-23 09:55:00-04:00"]) < 1e-3, mid
    w = vwap_state(d, 5, ny("2026-10-23 09:33"))
    assert w["status"] == "waiting" and w["score"] is None
    pre = vwap_state(d, 5, ny("2026-10-23 08:00"))                           # before the open: last session's state
    assert pre["status"] == "ok" and pre["session"] == "2026-10-22" and abs(pre["vwap"] - E["2026-10-22 15:55:00-04:00"]) < 1e-3


def test_rows_ignore_in_progress_bar():
    """No lookahead: the forming bar (and anything after now) cannot change a row."""
    d5, d15 = intra("SPY_5m.csv"), intra("SPY_15m.csv"); now = ny("2026-10-23 11:07")
    for fn, d, m in ((vwap_state, d5, 5), (ema_state, d15, 15)):
        a = fn(d, m, now)
        x = d.astype(float); late = x.index + pd.Timedelta(minutes=m) > now      # forming bar + everything after now
        assert late.sum() > 0
        x.loc[late, ["Open", "High", "Low", "Close"]] *= 1.5; x.loc[late, "Volume"] *= 3
        b = fn(x, m, now)
        assert a == b, (fn.__name__, a, b)
        assert pd.Timestamp(a["last_bar_end"]) <= now
    assert len(completed_bars(d15, 15, ny("2026-10-23 11:07"))) == len(completed_bars(d15, 15, ny("2026-10-23 11:00")))


def test_ema_row_state_and_since():
    d = intra("SPY_15m.csv"); E = J("expected_rows.json")["ema_15m_last"]
    st = ema_state(d, 15, ny("2026-10-23 17:00"))
    assert abs(st["ema9"] - E["ema9"]) < 1e-3 and abs(st["ema21"] - E["ema21"]) < 1e-3
    assert st["score"] == (1 if E["ema9"] > E["ema21"] else -1) and st["state"] == ("Up" if st["score"] > 0 else "Down")
    b = completed_bars(d, 15, ny("2026-10-23 17:00")); sgn = np.sign((ema(b.Close, 9) - ema(b.Close, 21)).values)
    since = pd.Timestamp(st["since"]); k = list(b.index + pd.Timedelta(minutes=15)).index(since)
    assert (sgn[k:] == sgn[-1]).all() and sgn[k - 1] != sgn[-1]          # first bar of the current unbroken run


# ---------------- round 4: scan universe, market calendar, home sections, freshness ----------------
from signals import CFG, universe_from_config, early_close, close_minutes, session_open, market_status, calendar_lists, home_sections


def test_universe_from_config():
    U = universe_from_config(CFG); su = CFG["scan_universe"]
    assert len(U) == len(set(U)) == 118 and UNIVERSE == U
    assert U[:len(CFG["tickers"])] == CFG["tickers"]                      # This Week first, in config order
    assert set(CFG["comparison_tickers"]) | set(su["etfs"]) | set(su["sp100"]) <= set(U)
    assert len(su["sp100"]) == 100 and len(su["etfs"]) == 15
    rel = ROOT / "research" / "fetch4_reliability.json"                    # the universe round 4 was validated on
    if rel.exists():
        assert set(json.loads(rel.read_text())["universe"]) == set(U)
    cfg = {"tickers": ["A", "B"], "comparison_tickers": ["B", "C"], "scan_universe": {"etfs": ["C", "D"], "sp100": ["A", "E"]}}
    assert universe_from_config(cfg) == ["A", "B", "C", "D", "E"]
    assert universe_from_config({"tickers": ["A"], "comparison_tickers": ["B"]}) == ["A", "B"]   # no scan_universe -> old list


def test_early_close_and_market_status():
    for d in ["2026-11-27", "2026-12-24", "2025-07-03", "2025-11-28", "2025-12-24", "2027-11-26"]:
        assert early_close(d) and close_minutes(pd.Timestamp(d)) == 780, d
    for d in ["2026-07-03", "2026-11-26", "2026-12-25", "2026-10-26", "2027-12-24", "2026-11-28"]:
        assert not early_close(d), d                                       # holidays / weekends / normal days
    assert session_open(ny("2026-11-27 12:59")) and not session_open(ny("2026-11-27 13:00"))
    assert session_open(ny("2026-10-26 15:59")) and not session_open(ny("2026-10-26 16:00"))
    assert not session_open(ny("2026-10-26 09:29")) and session_open(ny("2026-10-26 09:30"))
    M = lambda t: market_status(ny(t))
    assert M("2026-10-26 10:00")["state"] == "open" and M("2026-10-26 10:00")["closes_at"] == "16:00 ET"
    assert M("2026-11-27 10:00")["closes_at"] == "13:00 ET" and M("2026-11-27 10:00")["early_close"]
    assert M("2026-11-27 14:00")["state"] == "after"
    assert M("2026-10-26 08:00")["state"] == "pre" and M("2026-10-26 08:00")["next_open"] == "2026-10-26 09:30 ET"
    assert M("2026-10-26 21:00")["state"] == "closed" and M("2026-10-26 21:00")["next_open"] == "2026-10-27 09:30 ET"
    assert M("2026-10-24 12:00")["state"] == "closed" and M("2026-10-24 12:00")["next_open"] == "2026-10-26 09:30 ET"   # Saturday
    assert M("2026-11-26 12:00")["state"] == "closed" and M("2026-11-26 12:00")["next_open"] == "2026-11-27 09:30 ET"   # Thanksgiving
    C = calendar_lists([2026, 2027])
    assert "2026-11-26" in C["holidays"] and "2026-07-03" in C["holidays"] and "2027-12-24" in C["holidays"]
    assert C["early_closes"] == ["2026-11-27", "2026-12-24", "2027-11-26"]


def test_home_sections():
    R = [{"ticker": "X", "fired": True, "grade": "B", "mom_rank": 40}, {"ticker": "Y", "fired": True, "grade": "A", "mom_rank": 9},
         {"ticker": "Z", "fired": False, "mom_rank": 1}, {"ticker": "W", "fired": True, "grade": "A", "mom_rank": 3},
         {"ticker": "V", "fired": False, "mom_rank": 10}, {"ticker": "U", "fired": False, "mom_rank": 11},
         {"ticker": "S", "fired": False, "mom_rank": None, "status": "insufficient_history"}]
    S = {x["key"]: x for x in home_sections(R, ["S", "Q", "X"], 10)}
    assert [x["key"] for x in home_sections(R, [], 10)] == ["firing", "leaders", "this_week"]
    assert S["firing"]["tickers"] == ["W", "Y", "X"]                       # Grade A first, then by rank
    assert S["leaders"]["tickers"] == ["Z", "W", "Y", "V"]                 # rank <= 10, by rank (11 excluded)
    assert S["this_week"]["tickers"] == ["S", "Q", "X"] and S["this_week"]["missing"] == ["Q"]
    assert home_sections([], ["A"], 10)[0]["tickers"] == []


def test_u4_ranks_match_research4_if_present():
    D4 = ROOT / "research" / "data4"
    if not D4.exists(): print("  (research/data4 not present; skipped)"); return
    raw = {s: pd.read_pickle(D4 / f"{s}_1d.pkl") for s in UNIVERSE if (D4 / f"{s}_1d.pkl").exists()}
    assert len(raw) == 118
    rank, asof, _ = momentum_ranks({s: x["Close"].dropna() for s, x in raw.items()})
    # independent re-implementation of research4.load(): SPY calendar, 12-1 momentum, rank at each month-end
    spy = raw["SPY"].loc["2003-01-01":]; ix = spy.index.to_series()
    mend = pd.Series((ix.dt.to_period("M") != ix.shift(-1).dt.to_period("M")).values, spy.index); mend.iloc[-1] = False
    MOM = pd.DataFrame({s: (x.Close.shift(21) / x.Close.shift(252) - 1) for s, x in raw.items()}).reindex(spy.index)
    R = MOM.loc[spy.index[mend.values]].rank(axis=1, ascending=False)
    R = R.loc["2005-01-01":]
    L = rank.reindex(R.index)[R.columns]
    both = R.notna() & L.notna()
    assert both.values.sum() > 20000 and (R.notna() == L.notna()).values.all()
    assert (R[both] == L[both]).values[both.values].all()
    assert R.iloc[-1].notna().sum() == 117                                 # SPCX unranked (under a year of data)


def test_build_cards_falls_back_to_previous_card():
    import build_data as B
    orig = B.build_ticker
    def fake(sym, asof, U):
        if sym.endswith("BAD"): raise RuntimeError("download failed")
        if sym == "EMPTY": return {"ticker": sym, "status": "no_data"}
        return {"ticker": sym, "status": "ok", "v": 2}
    prev = {"tickers": [{"ticker": "BAD", "status": "ok", "v": 1, "notes": []}, {"ticker": "EMPTY", "status": "ok", "v": 1}]}
    try:
        B.build_ticker = fake
        out = {c["ticker"]: c for c in B.build_cards(["OK", "BAD", "EMPTY", "NEW_BAD"], None, None, prev)}
    finally:
        B.build_ticker = orig
    assert out["OK"] == {"ticker": "OK", "status": "ok", "v": 2}
    assert out["BAD"]["v"] == 1 and out["BAD"]["stale"] and out["EMPTY"]["stale"] and out["EMPTY"]["v"] == 1
    assert out["NEW_BAD"]["status"] == "no_data" and "stale" not in out["NEW_BAD"]  # nothing previous to fall back on
    assert list(out) == ["OK", "BAD", "EMPTY", "NEW_BAD"]


def test_freshness_decide():
    from freshness import decide
    u = lambda s: pd.Timestamp(s, tz=NY).tz_convert("UTC")                # times below are New York
    dj = lambda g, bar="2026-10-26": {"generated_at": u(g).isoformat(), "scanner": {"bar_date": bar}}
    bj = lambda g: {"generated_at": u(g).isoformat()}
    # push / dispatch always build; backtest only when asked
    assert decide(u("2026-10-26 12:00"), dj("2026-10-26 11:59"), bj("2026-10-26 11:00"), "push") == {"build": True, "backtest": False, "reason": "push: always build"}
    assert decide(u("2026-10-26 12:00"), None, None, "workflow_dispatch", True)["backtest"]
    # during the session: rebuild only if the live data is >= 20 min old; never the backtest
    assert not decide(u("2026-10-26 12:00"), dj("2026-10-26 11:45"), None, "schedule")["build"]
    r = decide(u("2026-10-26 12:00"), dj("2026-10-26 11:40"), None, "schedule"); assert r["build"] and not r["backtest"]
    assert decide(u("2026-10-26 12:00"), None, None, "schedule")["build"]                   # live site unreachable
    # after the close: the first slot builds + backtests, later slots skip (idempotent)
    pre = dj("2026-10-26 15:50"), bj("2026-10-23 18:20")
    assert decide(u("2026-10-26 16:10"), *pre, "schedule") == decide(u("2026-10-26 16:10"), *pre, "schedule")
    r = decide(u("2026-10-26 16:10"), *pre, "schedule"); assert not r["build"] and not r["backtest"]   # close not settled yet (16:15): 15:50 data and Friday's backtest are current
    r = decide(u("2026-10-26 18:17"), *pre, "schedule"); assert r["build"] and r["backtest"]
    done = dj("2026-10-26 18:19"), bj("2026-10-26 18:20")
    for t in ["2026-10-26 18:47", "2026-10-26 19:33", "2026-10-26 21:13", "2026-10-27 08:07", "2026-10-27 09:07"]:
        assert decide(u(t), *done, "schedule")["build"] is False, t
    # a build made after the close but still carrying the previous session's bar is stale
    assert decide(u("2026-10-26 18:47"), dj("2026-10-26 18:19", bar="2026-10-23"), bj("2026-10-26 18:20"), "schedule")["build"]
    # backtest missing / older than the close -> rerun even if data is fresh
    r = decide(u("2026-10-26 18:47"), dj("2026-10-26 18:19"), None, "schedule"); assert r["build"] and r["backtest"]
    # weekend / holiday: the last session is Friday / the day before
    assert not decide(u("2026-10-31 12:00"), dj("2026-10-30 18:30", "2026-10-30"), bj("2026-10-30 18:31"), "schedule")["build"]
    assert decide(u("2026-10-31 12:00"), dj("2026-10-30 15:00", "2026-10-30"), bj("2026-10-30 18:31"), "schedule")["build"]
    assert not decide(u("2026-11-26 20:00"), dj("2026-11-25 17:00", "2026-11-25"), bj("2026-11-25 17:00"), "schedule")["build"]
    # early close (13:00): settled at 13:15, so a 14:00 run builds and later ones skip
    r = decide(u("2026-11-27 14:00"), dj("2026-11-27 12:50", "2026-11-27"), bj("2026-11-26 10:00"), "schedule"); assert r["build"] and r["backtest"]
    assert not decide(u("2026-11-27 18:00"), dj("2026-11-27 14:01", "2026-11-27"), bj("2026-11-27 14:05"), "schedule")["build"]


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"): v(); print("ok", k)
