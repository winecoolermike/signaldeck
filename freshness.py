"""Decide whether a workflow run should rebuild data / rerun the backtest (idempotent schedule).

GitHub's cron is best effort: on Oct 26 2026 only 2 of 18 intraday slots fired and the 22:15 UTC post-close slot
started 3 h 13 min late. So the workflow now has several extra, off-the-hour slots, and every scheduled run first
checks the LIVE site: if what's published is already fresh, the run does nothing. Extra slots therefore cost
nothing, and whichever slot fires first after the close does the post-close build + backtest.

Usage in the workflow:  python freshness.py EVENT DATA_JSON BACKTEST_JSON [force_backtest]  -> writes build=/backtest=
to $GITHUB_OUTPUT (or prints them).
"""
import json, os, sys
from datetime import datetime, timezone
import pandas as pd
from signals import NY, is_trading_day, close_minutes, session_open

OPEN_MAX_AGE_MIN = 20      # during the session: rebuild if the live data.json is at least this old
SETTLE_MIN = 15            # after the close: a build counts as "post-close" only if made >= close + 15 min

def last_settled_close(now_ny):
    """NY timestamp of close+SETTLE of the most recent trading session that is settled at now_ny."""
    d = now_ny.tz_localize(None).normalize()
    for _ in range(15):
        if is_trading_day(d):
            t = (d + pd.Timedelta(minutes=close_minutes(d) + SETTLE_MIN)).tz_localize(NY)
            if t <= now_ny:
                return t, d
        d -= pd.Timedelta(days=1)
    raise RuntimeError("no trading day in the last 15 days")

def _ts(s):
    try:
        t = pd.Timestamp(s)                       # NB: pd.Timestamp(None) is NaT, not an error
        if pd.isna(t): return None
        return t.tz_localize("UTC") if t.tzinfo is None else t
    except Exception:
        return None

def decide(now, live_data, live_backtest, event, force_backtest=False):
    """now: aware datetime. live_data / live_backtest: parsed live JSON or None. Returns {build, backtest, reason}."""
    now_ny = pd.Timestamp(now).tz_convert(NY)
    settled, sess = last_settled_close(now_ny)
    g = _ts((live_data or {}).get("generated_at"))
    bar = ((live_data or {}).get("scanner") or {}).get("bar_date")
    bg = _ts((live_backtest or {}).get("generated_at"))
    bt_stale = bg is None or bg < settled
    if event != "schedule":                       # push / manual dispatch: always build
        return {"build": True, "backtest": bool(force_backtest), "reason": f"{event}: always build"}
    if session_open(now_ny):
        if g is None:
            return {"build": True, "backtest": False, "reason": "open: no live data.json"}
        age = (now_ny - g).total_seconds() / 60
        return {"build": age >= OPEN_MAX_AGE_MIN, "backtest": False,
                "reason": f"open: live data is {age:.0f} min old (rebuild at >= {OPEN_MAX_AGE_MIN})"}
    # outside the session: need one build made after the last session settled, with that session's bar
    data_stale = g is None or g < settled or (bar is not None and bar < str(sess.date()))
    return {"build": data_stale or bt_stale, "backtest": bt_stale,
            "reason": f"closed: last settled session {sess.date()} (settled {settled:%Y-%m-%d %H:%M %Z}); "
                      f"live data {'stale' if data_stale else 'fresh'} ({g}, bar {bar}); backtest {'stale' if bt_stale else 'fresh'} ({bg})"}

def _load(p):
    try:
        return json.load(open(p))
    except Exception:
        return None

if __name__ == "__main__":
    ev, dp, bp = sys.argv[1:4]
    force = len(sys.argv) > 4 and sys.argv[4].lower() == "true"
    r = decide(datetime.now(timezone.utc), _load(dp), _load(bp), ev, force)
    print("freshness:", r["reason"], "->", r)
    out = os.environ.get("GITHUB_OUTPUT")
    lines = f"build={'true' if r['build'] else 'false'}\nbacktest={'true' if r['backtest'] else 'false'}\n"
    if out:
        open(out, "a").write(lines)
    else:
        print(lines, end="")
