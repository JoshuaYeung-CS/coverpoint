"""The experiment, end to end.

    python -m harness.run score dev            score a sample, write results/<sample>/
    python -m harness.run reproduce --check    redo every scored sample from the RTL up and
                                               fail if any outcome or cited number drifted
    python -m harness.run report               print the tables from the committed results

Everything that decides an outcome is read from docs/prereg.json. Nothing here looks at
which mutants survived in order to decide what to run.
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import equiv, formal, mutants, prove, report, simrun
from .common import BUILD, RESULTS, ROOT, dump, load
from .score import score_sample

PLAN = ROOT / "docs" / "prereg.json"
JOBS = 8


def pmap(fn, items, jobs=JOBS):
    with ThreadPoolExecutor(jobs) as ex:
        return list(ex.map(fn, items))


def golden_runs(sample: str, plan: dict) -> dict:
    """Every test and every seed on the unmutated design (mutsel = 0), with functional
    coverage on. Any mismatch here means the bench or the design is wrong and nothing
    that follows would mean anything, so it stops the run."""
    rnd = plan["random"]
    jobs = [(plan["baseline_test"], 0, 0)] + [(t, 0, 0) for t in plan["directed"]]
    jobs += [(rnd["test"], s, rnd["budget_long"]) for s in rnd["seeds"]]
    recs = pmap(lambda j: simrun.run_one(sample, 0, j[0], j[1], j[2], cover=True), jobs)
    bad = [r for r in recs if r.get("killed") or "error" in r]
    if bad:
        raise SystemExit(f"the unmutated design fails its own bench: {bad[:3]}")
    out = {"smoke": None, "directed": [], "random": {}}
    for r in recs:
        cov = r["coverage"]
        entry = {"cycles": r["cycles"], "hit": cov["hit"], "missed": cov["missed"], "timeline": cov["timeline"]}
        if r["test"] == plan["baseline_test"]:
            out["smoke"] = entry
        elif r["test"] == rnd["test"]:
            out["random"][str(r["seed"])] = entry
        else:
            out["directed"].append({"test": r["test"], **entry})
    out["bins"] = recs[0]["coverage"]["bins"]
    return out


def simulate(sample: str, ids: list[int], plan: dict, cost: dict, golden: dict) -> dict:
    rnd = plan["random"]
    res = {k: {"smoke": None, "directed": None, "random": {}} for k in ids}

    t0 = time.time()
    for r in pmap(lambda k: simrun.run_one(sample, k, plan["baseline_test"], 0, 0), ids):
        _check(r)
        if r["killed"]:
            res[r["mutsel"]]["smoke"] = r["kill_cycle"]
    cost["smoke_wall_s"] = round(time.time() - t0, 1)

    # The directed suite runs in its fixed order. A mutant leaves the suite at the first
    # test that kills it; what is recorded is that test and the cycles spent up to the kill.
    t0 = time.time()
    alive, spent = list(ids), 0
    lengths = {t["test"]: t["cycles"] for t in golden["directed"]}
    for test in plan["directed"]:
        for r in pmap(lambda k: simrun.run_one(sample, k, test, 0, 0), alive):
            _check(r)
            if r["killed"]:
                res[r["mutsel"]]["directed"] = {"test": test, "cycles_to_kill": spent + r["kill_cycle"]}
        alive = [k for k in alive if res[k]["directed"] is None]
        spent += lengths[test]
    cost["directed_wall_s"] = round(time.time() - t0, 1)

    # Each random seed runs once to the long budget and stops at the first mismatch, so
    # the kill cycle answers "killed within B cycles?" for every B up to the long budget.
    t0 = time.time()
    jobs = [(k, s) for s in rnd["seeds"] for k in ids]
    for r in pmap(lambda j: simrun.run_one(sample, j[0], rnd["test"], j[1], rnd["budget_long"]), jobs):
        _check(r)
        res[r["mutsel"]]["random"][str(r["seed"])] = r["kill_cycle"] if r["killed"] else None
    cost["random_wall_s"] = round(time.time() - t0, 1)
    return res


def _check(rec: dict) -> None:
    if "error" in rec:
        raise SystemExit(f"simulator run produced no result: {rec}")


def score(sample: str, out_dir: Path) -> dict:
    plan = load(PLAN)
    spec = plan["samples"][sample]
    cost: dict = {}
    t_all = time.time()
    rec = mutants.generate(sample, spec["seed"], spec["count"], out_dir)
    ids = [m["id"] for m in rec["mutants"]]
    simrun.build(sample)

    golden = golden_runs(sample, plan)
    sims = simulate(sample, ids, plan, cost, golden)

    fplan = plan["formal"]
    t0 = time.time()
    fv = pmap(lambda k: formal.check(sample, k, fplan["frames"], fplan["max_div"], fplan["safety_seconds"]), [0] + ids)
    cost["formal_wall_s"] = round(time.time() - t0, 1)
    cost["formal_solver_s"] = round(sum(r["wall_s"] for r in fv), 1)
    if fv[0]["status"] != "UNDECIDED":
        raise SystemExit(f"the property set does not hold on the unmutated design: {fv[0]}")
    fv = {r["id"]: r for r in fv[1:]}

    def killed(k):
        s = sims[k]
        return (s["smoke"] is not None or s["directed"] is not None
                or any(v is not None for v in s["random"].values()) or fv[k]["status"] == "FAIL")

    # Equivalence: a full attempt (search, then proof) on the mutants nothing killed, and a
    # search-only consistency check on the rest. A mutant that a test killed can never be
    # proved equivalent; if that ever happened the harness itself would be wrong.
    eplan = plan["equivalence"]
    t0 = time.time()
    survivors = [k for k in ids if not killed(k)]
    eq = pmap(lambda k: equiv.classify(sample, k, eplan["bmc_frames"], eplan["pdr_frames"], eplan["safety_seconds"]),
              survivors)
    chk = pmap(lambda k: equiv.classify(sample, k, eplan["killed_check_frames"], 0, eplan["safety_seconds"]),
               [k for k in ids if killed(k)])
    cost["equivalence_wall_s"] = round(time.time() - t0, 1)
    contradictions = [r["id"] for r in chk if r["verdict"] == "equivalent"]
    if contradictions:
        raise SystemExit(f"mutants both killed and proved equivalent: {contradictions}")
    eq = {r["id"]: r for r in eq + chk}
    cost["equivalence_max_proof_s"] = max([r["wall_s"] for r in eq.values() if r["verdict"] == "equivalent"], default=0)

    outcomes = {"sample": sample, "golden": golden, "mutants": {
        str(k): {**sims[k],
                 "formal": {x: v for x, v in fv[k].items() if x not in ("id", "wall_s")},
                 "equivalence": {x: v for x, v in eq[k].items() if x not in ("id", "wall_s")}}
        for k in ids}}
    cost["total_wall_s"] = round(time.time() - t_all, 1)
    dump(out_dir / "outcomes.json", outcomes)
    dump(out_dir / "cost.json", cost)
    dev_keys = None
    if sample != "dev" and (RESULTS / "dev" / "mutants.json").exists():
        dev_keys = {m["key"] for m in load(RESULTS / "dev" / "mutants.json")["mutants"]}
    dump(out_dir / "score.json", score_sample(rec, outcomes, plan, dev_keys))
    return outcomes


def stable(name: str, obj):
    """What `reproduce` compares. Everything, except one by-product: for a mutant whose
    equivalence check came back 'unresolved', the depth the search happened to reach before
    its time cap. That depth depends on how busy the machine is; the verdict does not.
    (Amended after the confirmatory sample was opened: docs/DEVIATIONS.md, item 2.)"""
    if name != "outcomes.json":
        return obj
    out = {**obj, "mutants": {}}
    for k, v in obj["mutants"].items():
        eq = v["equivalence"]
        if eq["verdict"] == "unresolved":
            eq = {x: y for x, y in eq.items() if x != "frames"}
        out["mutants"][k] = {**v, "equivalence": eq}
    return out


def compare() -> list[str]:
    """Compare the last reproduce run (build/reproduce/) with the committed results."""
    drift = []
    if load(BUILD / "reproduce" / "proof.json") != load(RESULTS / "proof.json"):
        drift.append("proof.json")
    for sample in ("dev", "confirmatory"):
        committed, out = RESULTS / sample, BUILD / "reproduce" / sample
        if not (committed / "outcomes.json").exists():
            continue
        for name in ("mutants.json", "outcomes.json", "score.json"):
            if stable(name, load(out / name)) != stable(name, load(committed / name)):
                drift.append(f"{sample}/{name}")
    return drift


def reproduce(check: bool, rerun: bool = True) -> int:
    if rerun:
        prove.main(BUILD / "reproduce")
        for sample in ("dev", "confirmatory"):
            if (RESULTS / sample / "outcomes.json").exists():
                score(sample, BUILD / "reproduce" / sample)
    drift = compare()
    report.main_report()
    if check:
        drift += report.check_cited()
        if drift:
            print("\nDRIFT:", *drift, sep="\n  ")
            return 1
        print("\nreproduced: every outcome and every cited number matches the commit")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prove")
    s = sub.add_parser("score")
    s.add_argument("sample", choices=("dev", "confirmatory"))
    r = sub.add_parser("reproduce")
    r.add_argument("--check", action="store_true")
    r.add_argument("--compare-only", action="store_true",
                   help="do not re-run; compare the last run in build/reproduce/ with results/")
    sub.add_parser("report")
    a = ap.parse_args()
    if a.cmd == "prove":
        prove.main()
    elif a.cmd == "score":
        score(a.sample, RESULTS / a.sample)
        report.main_report()
    elif a.cmd == "reproduce":
        sys.exit(reproduce(a.check, rerun=not a.compare_only))
    else:
        report.main_report()


if __name__ == "__main__":
    main()
