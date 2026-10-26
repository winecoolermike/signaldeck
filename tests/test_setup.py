"""Unit tests for the Pullback setup (python -m pytest tests  or  python tests/test_setup.py).

Uses a small committed fixture of real Yahoo SPY daily bars (adjusted), never live data.
"""
import sys, json
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from signals import SETUP, setup_features, pullback_setup, pullback_trades, pullback_ticker_stats, completed_sessions

FIX = ROOT / "tests" / "fixtures" / "SPY_1d_adjusted.csv"


def spy():
    return pd.read_csv(FIX, index_col=0, parse_dates=True)


def test_known_spy_triggers():
    d = spy(); E = json.loads((ROOT / "tests" / "fixtures" / "expected.json").read_text())
    for t in E["triggers"]:
        day = pd.Timestamp(t["date"])
        st = pullback_setup(d.loc[:day])                   # data only up to that close
        assert st["status"] == "ok" and st["fired"] is True and st["bar_date"] == t["date"], st
        assert st["close"] > st["sma200"] and st["rsi2"] < SETUP["rsi_max"]
        assert st["grade"] == t["grade"], st
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
        for key, name in (("all", "pb_long_rsi2<10_xSMA5"), ("grade_a", "pb_rsi2<10_adx>25_long")):
            ref = R[name]["per_ticker_test"][sym]
            assert s[key]["n"] == ref["n"], (sym, key, s[key]["n"], ref["n"])
            if ref["n"]:
                assert abs(s[key]["hit"] - ref["hit"]) < 1e-3 and abs(s[key]["exp_net_pct"] - ref["exp_net_pct"]) < 2e-3, (sym, key)


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"): v(); print("ok", k)
