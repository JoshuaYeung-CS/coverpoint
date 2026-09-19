"""From raw outcomes to the scored table. Pure functions: no tools, no clocks.

A mutant is killed by an arm when that arm's checker fired on it (a lockstep mismatch in
simulation, a counterexample from reset in the formal run) while the same stimulus passed
on the unmutated design. Mutants proved equivalent are removed from every arm's
denominator. Mutants that nothing killed and that could not be proved equivalent stay in
as survivors.
"""
from __future__ import annotations

import math

GRID = (100, 300, 1000, 3000, 11690, 30000, 116900)


def wilson(k: int, n: int, z: float = 1.959964) -> list[float]:
    if n == 0:
        return [0.0, 0.0]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 4), round(c + h, 4)]


def arm(killed: set, live: set) -> dict:
    k = len(killed & live)
    return {"killed": k, "survived": len(live) - k, "score": round(k / len(live), 4), "ci95": wilson(k, len(live))}


def bins_at(timeline: list, cycle: int) -> int:
    hit = 0
    for c, n in timeline:
        if c < cycle:
            hit = n
    return hit


def score_sample(mutants: dict, outcomes: dict, plan: dict, dev_keys: set | None = None) -> dict:
    rnd = plan["random"]
    seeds = [str(s) for s in rnd["seeds"]]
    B, L = rnd["budget_equal"], rnd["budget_long"]
    mm = {int(k): v for k, v in outcomes["mutants"].items()}
    ids = set(mm)
    equivalent = {k for k, v in mm.items() if v["equivalence"]["verdict"] == "equivalent"}
    live = ids - equivalent

    smoke = {k for k, v in mm.items() if v["smoke"] is not None}
    directed = {k for k, v in mm.items() if v["directed"] is not None}
    rand = {s: {b: {k for k, v in mm.items() if v["random"][s] is not None and v["random"][s] < b}
                for b in (B, L)} for s in seeds}
    fv = {k for k, v in mm.items() if v["formal"]["status"] == "FAIL"}
    fv_timeout = sorted(k for k, v in mm.items() if v["formal"]["status"] == "TIMEOUT")
    rand_union = {b: set().union(*(rand[s][b] for s in seeds)) for b in (B, L)}
    any_sim = smoke | directed | rand_union[L]
    anything = any_sim | fv
    unresolved = live - anything

    def seeds_summary(b):
        per = [arm(rand[s][b], live) for s in seeds]
        ks = [p["killed"] for p in per]
        return {"per_seed_killed": ks, "mean_killed": round(sum(ks) / len(ks), 2), "min_killed": min(ks),
                "max_killed": max(ks), "mean_score": round(sum(ks) / len(ks) / len(live), 4),
                "union": arm(rand_union[b], live)}

    golden = outcomes["golden"]
    directed_cycles = sum(t["cycles"] for t in golden["directed"])
    curve = []
    for c in GRID:
        curve.append({
            "cycles": c,
            "random_mean_killed": round(sum(len({k for k in live if mm[k]["random"][s] is not None
                                                 and mm[k]["random"][s] < c}) for s in seeds) / len(seeds), 2),
            "directed_killed": len({k for k in live if mm[k]["directed"] is not None
                                    and mm[k]["directed"]["cycles_to_kill"] < c}),
            "random_mean_bins": round(sum(bins_at(golden["random"][s]["timeline"], c) for s in seeds) / len(seeds), 2),
        })

    bins = golden["bins"]
    closure = {s: next((c for c, n in golden["random"][s]["timeline"] if n == bins), None) for s in seeds}
    all_bins_missed = None
    cum, cum_cycles, directed_cov = None, 0, []
    for t in golden["directed"]:
        missed = set(t["missed"])
        cum = missed if cum is None else cum & missed
        cum_cycles += t["cycles"]
        directed_cov.append({"test": t["test"], "cycles_so_far": cum_cycles, "bins_hit_so_far": bins - len(cum)})

    paired = {s: {"directed_only": len((directed - rand[s][B]) & live), "random_only": len((rand[s][B] - directed) & live)}
              for s in seeds}
    fkills = sorted(mm[k]["formal"]["frame"] for k in fv)
    by_id = {m["id"]: m for m in mutants["mutants"]}

    def describe(k):
        m = by_id[k]
        return {"id": k, "mode": m["mode"], "cell": m["cell"], "port": m.get("port"), "portbit": m.get("portbit"),
                "wire": m.get("wire"), "wirebit": m.get("wirebit"), "src": m["src"]}

    out = {
        "sample": outcomes["sample"], "mutants": len(ids), "equivalent": len(equivalent), "scored": len(live),
        "unresolved_survivors": sorted(unresolved),
        "arms": {
            "smoke": {**arm(smoke, live), "cycles": golden["smoke"]["cycles"]},
            "directed": {**arm(directed, live), "cycles": directed_cycles},
            "random_equal_cycles": {**seeds_summary(B), "cycles": B},
            "random_long": {**seeds_summary(L), "cycles": L},
            "formal": {**arm(fv, live), "frames": plan["formal"]["frames"], "max_div": plan["formal"]["max_div"],
                       "undecided": len(live - fv) - len(set(fv_timeout) & live), "timeout": fv_timeout,
                       "median_frame_of_kill": fkills[len(fkills) // 2] if fkills else None,
                       "deepest_kill_frame": fkills[-1] if fkills else None},
            "any_simulation": arm(any_sim, live),
            "anything": arm(anything, live),
        },
        "paired_directed_vs_random_equal": paired,
        "formal_vs_simulation": {
            "formal_only": sorted((fv - any_sim) & live),
            "simulation_only": len((any_sim - fv) & live),
            "formal_not_directed": sorted((fv - directed) & live),
            "formal_not_random_equal_any_seed": sorted((fv - rand_union[B]) & live),
        },
        "curve": curve,
        "coverage": {"bins": bins, "random_cycle_of_closure": closure,
                     "random_bins_at_equal_budget": {s: bins_at(golden["random"][s]["timeline"], B) for s in seeds},
                     "random_missed_at_long_budget": {s: golden["random"][s]["missed"] for s in seeds},
                     "directed_cumulative": directed_cov, "smoke_bins": golden["smoke"]["hit"]},
        "survivors": {
            "directed": [describe(k) for k in sorted(live - directed)],
            "random_long_union": [describe(k) for k in sorted(live - rand_union[L])],
            "anything": [describe(k) for k in sorted(unresolved)],
        },
    }
    if dev_keys is not None:
        out["overlap_with_dev"] = len({m["key"] for m in mutants["mutants"]} & dev_keys)
    return out
