#!/usr/bin/env python3
"""Derive site/setups.json (FROZEN out-of-sample research stats for the Pullback setup) from the
local research result files. Every number is copied from research/results_*.json; nothing is typed in.

    python make_setups.py          # needs research/results_daily.json, results_stage2.json, results_cluster.json

The research files are local-only (gitignored); the generated site/setups.json is committed and is not
rebuilt by the scheduled job (rule definitions and research stats are frozen; the job only recomputes
each ticker's own stats with new bars, via signals.pullback_ticker_stats).
"""
import json, hashlib, datetime as dt
from pathlib import Path
from signals import SETUP

ROOT = Path(__file__).parent; RD = ROOT / "research"; OUT = ROOT / "site" / "setups.json"
FILES = {k: RD / f"results_{k}.json" for k in ("daily", "stage2", "cluster")}
D, S, C = (json.loads(FILES[k].read_text()) for k in ("daily", "stage2", "cluster"))
VERSIONS = {"all": "pb_long_rsi2<10_xSMA5", "grade_a": "pb_rsi2<10_adx>25_long"}
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
       "versions": versions, "variants": rows, "variants_60m": h60, "ladder": ladder}
OUT.write_text(json.dumps(out, indent=1, default=str))
print("wrote", OUT, "| survived:", [r["name"] for r in rows if r["survived"]], "| tested", n_tested, "alpha", alpha)
