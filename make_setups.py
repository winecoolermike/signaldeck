#!/usr/bin/env python3
"""Derive site/setups.json (FROZEN out-of-sample research stats for the Pullback setup) from the
local research result files. Every number is copied from research/results_*.json; nothing is typed in.

    python make_setups.py          # needs research/results_{daily,stage2,cluster,round2,round2_robust,round3,round3_desc}.json

The research files are local-only (gitignored); the generated site/setups.json is committed and is not
rebuilt by the scheduled job (rule definitions and research stats are frozen; the job only recomputes
each ticker's own stats with new bars, via signals.pullback_ticker_stats).
"""
import json, hashlib, datetime as dt
from pathlib import Path
from signals import SETUP

ROOT = Path(__file__).parent; RD = ROOT / "research"; OUT = ROOT / "site" / "setups.json"
FILES = {k: RD / f"results_{k}.json" for k in ("daily", "stage2", "cluster", "round2", "round2_robust", "round3", "round3_desc")}
D, S, C, R2, RB, R3, R3D = (json.loads(FILES[k].read_text()) for k in FILES)
VERSIONS = {"all": "pb_long_rsi2<10_xSMA5"}
C2 = "C2 pullback in top-10 momentum"
SETS = ("all23", "broad16", "core7")
KEEP = ("n", "trades_per_ticker_year", "hit", "chance", "same_exit_random_hit", "same_exit_random_exp_net_pct",
        "p_hit", "p_hit_vs_same_exit", "exp_net_pct", "avg_win_net", "avg_loss_net", "profit_factor_net",
        "avg_hold_days", "port_cagr_net_pct", "port_maxdd_pct", "few")
pick = lambda m: {k: m.get(k) for k in KEEP if k in m}

n_h60_cand = sum(1 for k in S["h60"] if "_base_" not in k)
n_tested = D["params"]["n_daily_variants"] + D["params"]["ladder_levels"] + n_h60_cand
alpha = 0.05 / n_tested
data_end = max(v[1] for v in D["data"].values())


def variant_row(name, fam, src):
    m = src["all23"]["test"]; c7 = src["core7"]["test"]
    p = m.get("p_hit_vs_same_exit", m.get("p_hit"))
    base = m.get("same_exit_random_hit") if m.get("same_exit_random_hit") is not None else m.get("chance")
    ok = m["n"] >= SETUP["min_trades"] and p is not None and p < alpha and m["exp_net_pct"] > 0
    why = ("survived" if ok else "too few trades" if m["n"] < SETUP["min_trades"] else
           "lost money after costs" if m["exp_net_pct"] <= 0 else "hit rate not better than baseline (after multiple-testing adjustment)")
    return {"name": name, "family": fam, "n": m["n"], "hit": m["hit"], "baseline_hit": base,
            "baseline_kind": "random entries, same exit" if m.get("same_exit_random_hit") is not None else "random entries, same holding period",
            "p": p, "exp_net_pct": m["exp_net_pct"], "profit_factor_net": m.get("profit_factor_net"),
            "core7_n": c7.get("n"), "core7_hit": c7.get("hit"), "core7_exp_net_pct": c7.get("exp_net_pct"),
            "survived": ok, "verdict": why}


rows = []
for name, v in D["daily"].items():
    src = S["selected"].get(name, v)
    rows.append(variant_row(name, v["family"], src))
h60 = [{"name": k, "family": "60m", "n": v["all23"]["test"]["n"], "hit": v["all23"]["test"]["hit"],
        "exp_net_pct": v["all23"]["test"]["exp_net_pct"], "profit_factor_net": v["all23"]["test"]["profit_factor_net"],
        "core7_n": v["core7"]["test"]["n"], "core7_hit": v["core7"]["test"]["hit"], "core7_exp_net_pct": v["core7"]["test"]["exp_net_pct"],
        "survived": False, "verdict": "lost money after costs" if v["all23"]["test"]["exp_net_pct"] <= 0 else "not tested for significance"}
       for k, v in S["h60"].items() if "_base_" not in k]

ladder = []
for name, v in D["ladder"].items():
    a, c7 = v["all23"], v["core7"]["test"]
    ladder.append({"level": name, "train_n": a["train"]["n"], "train_hit": a["train"]["hit"], "n": a["test"]["n"],
                   "trades_per_ticker_year": a["test"]["trades_per_ticker_year"], "hit": a["test"]["hit"],
                   "exp_net_pct": a["test"]["exp_net_pct"], "core7_n": c7["n"], "core7_hit": c7["hit"],
                   "kind": "current rule, 5-day hold" if name.startswith("current") else "pullback, exit close>SMA5 or 10d"})

# round-2 metric names -> the round-1 names the site already reads
R2MAP = {"n": "n", "per_ticker_year": "trades_per_ticker_year", "hit": "hit", "base_hit": "same_exit_random_hit",
         "base_exp_net_pct": "same_exit_random_exp_net_pct", "p": "p_hit_vs_same_exit", "exp_net_pct": "exp_net_pct",
         "avg_win_pct": "avg_win_net", "avg_loss_pct": "avg_loss_net", "pf": "profit_factor_net", "avg_hold": "avg_hold_days",
         "cagr_pct": "port_cagr_net_pct", "maxdd_pct": "port_maxdd_pct", "few": "few",
         "worst_trade_pct": "worst_trade_pct", "t_clustered": "t_clustered"}
pick2 = lambda m: {R2MAP[k]: v for k, v in m.items() if k in R2MAP}

versions = {}
for key, name in VERSIONS.items():
    sel = S["selected"][name]
    versions[key] = {"research_name": name,
                     "label": "close > SMA200 & RSI(2) < 10" + (" & ADX(14) > 25" if key == "grade_a" else ""),
                     "test": {s: pick(sel[s]["test"]) for s in SETS}, "train": {s: pick(sel[s]["train"]) for s in SETS},
                     "test_by_year": sel["all23"]["test_by_year"],
                     "next_open_entry": pick(S["next_open"][name]["all23"]["test"]),
                     "date_clustered": {s: C[f"{name}|{s}"] for s in SETS if f"{name}|{s}" in C},
                     "core7_per_ticker_test": {t: pick(m) for t, m in sel["per_ticker_test"].items() if t in D["params"]["tickers"]["core7"]}}
c2 = R2["C"][C2]
versions["grade_a"] = {"research_name": C2, "source": "round 2 (results_round2.json)",
                       "label": "close > SMA200 & RSI(2) < 10 & top-10 of 23 by 12-1 momentum (last month-end)",
                       "test": {s_: pick2(c2[s_]["test"]) for s_ in SETS}, "train": {s_: pick2(c2[s_]["train"]) for s_ in SETS},
                       "test_by_year": c2["all23"]["by_year"],
                       "next_open_entry": pick2(RB["C2 next-open entry"]["all23"]["test"]),
                       "date_clustered": {s_: {"t": c2[s_]["test"].get("t_clustered")} for s_ in SETS},
                       "core7_per_ticker_test": {t: pick2(m) for t, m in c2["per_ticker_test"].items() if t in D["params"]["tickers"]["core7"]}}

# optional 3xATR disaster stop and ATR sizing (round 2, information only; the rule itself has no stop)
A = R2["A"]
def wt(m): return {k: m.get(k) for k in ("n", "hit", "exp_net_pct", "pf", "worst_trade_pct", "avg_loss_pct", "maxdd_pct")}
risk = {"stop": {"label": f"{SETUP['stop_atr_mult']}x ATR({SETUP['atr_len']}) below the signal close, resting stop (gap-through fills at the open)",
                 "all_pullbacks": {"no_stop": {"test": wt(A["A0 base pullback"]["all23"]["test"]), "train": wt(A["A0 base pullback"]["all23"]["train"])},
                                   "stop": {"test": wt(A["A4 stop 3xATR"]["all23"]["test"]), "train": wt(A["A4 stop 3xATR"]["all23"]["train"])}},
                 "grade_a": {"no_stop": {"test": wt(c2["all23"]["test"]), "train": wt(c2["all23"]["train"])},
                             "stop": {"test": wt(RB["C2 + 3xATR stop"]["all23"]["test"]), "train": wt(RB["C2 + 3xATR stop"]["all23"]["train"])}}},
        "sizing": {"label": f"weight = min({SETUP['size_cap']:g}, {SETUP['size_risk_atr']*100:g}% / ATR%)",
                   "no_sizing": {"test": wt(A["A0 base pullback"]["all23"]["test"])},
                   "atr_sizing": {"test": wt(A["A12 ATR sizing"]["all23"]["test"])}},
        "round2_alpha": R2["meta"].get("alpha"), "round2_tests_cumulative": R2["meta"].get("n_variants_cumulative")}

# round-3 intraday evidence (descriptive): why each row uses the indicator it uses
DS = R3D["descriptors"]
def dsc(m): return {k: m.get(k) for k in ("agree_session_to_date", "flips_per_session", "persist_3bar", "rest_hit", "rest_base",
                                           "rest_excess_pp", "rest_t_dayclustered", "n_days", "n_bars", "coverage")}
row_ev = {}
for iv, ch in R3D["choice"].items():
    row_ev[iv] = {"chosen": ch, "current": "S1 score bias (current)", "split": R3["meta"]["split"].get(iv),
                  "test": {k: dsc(v) for k, v in DS[iv]["test"].items() if isinstance(v, dict)},
                  "bars_per_session": DS[iv]["test"].get("bars_per_session")}
alpha3 = R3["meta"]["alpha"]
def surv(m): return m["n"] >= SETUP["min_trades"] and m.get("p") is not None and m["p"] < alpha3 and m["net_pct"] > 0
it = {k: v["all23"]["test"] for k, v in R3["intraday"].items()}
intr = {"n_rules": len(it), "survivors": [k for k, m in it.items() if surv(m)],
        "n_net_positive": sum(m["net_pct"] > 0 for m in it.values()),
        "best_net_pct": max(m["net_pct"] for m in it.values()), "worst_net_pct": min(m["net_pct"] for m in it.values()),
        "round_trip_cost_pct": round(R3["meta"]["round_trip"] * 100, 3)}
rows3 = {"rows": row_ev, "total": {k: {"std_hit": v["std"]["hit"], "std_base": v["std"]["base"], "rest_hit": v["rest"]["hit"],
                                       "rest_base": v["rest"]["base"], "rest_t": v["rest"]["t_dayclustered"], "n_days": v["n_days"]}
                                   for k, v in R3D["total"].items() if k in ("T0", "T1")},
         "intraday_rules": intr, "tests_round3": R3["meta"]["n_r3"], "tests_cumulative": R3["meta"]["n_cum"], "alpha_cumulative": alpha3,
         "grade_a_p": c2["all23"]["test"]["p"]}

cur = D["daily"]["current_h5"]
out = {"generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
       "frozen": True, "rule": SETUP,
       "research": {"train": D["params"]["train"], "test": [D["params"]["test"][0], data_end],
                    "cost_per_side": D["params"]["cost_per_side"], "tickers": D["params"]["tickers"],
                    "variants_tested": n_tested, "bonferroni_alpha": alpha,
                    "survival_rule": f"all-23 out-of-sample: >= {SETUP['min_trades']} trades, hit-rate p < {alpha:.5f} vs baseline (Bonferroni over {n_tested} variants), net expectancy > 0 after costs",
                    "buy_hold": S["buy_hold"],
                    "source_files": {k: {"file": f"research/{p.name}", "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for k, p in FILES.items()}},
       "current_rule_oos": {s: pick(cur[s]["test"]) | {"horizon_days": 5} for s in SETS},
       "versions": versions, "variants": rows, "variants_60m": h60, "ladder": ladder, "risk": risk, "round3": rows3}
OUT.write_text(json.dumps(out, indent=1, default=str))
print("wrote", OUT, "| survived:", [r["name"] for r in rows if r["survived"]], "| tested", n_tested, "alpha", alpha)
