"""Print the scored tables from results/, and check every number the documents quote."""
from __future__ import annotations

from .common import RESULTS, ROOT, load

CITED = ROOT / "docs" / "CITED.json"


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def table(sample: str) -> None:
    s = load(RESULTS / sample / "score.json")
    a = s["arms"]
    print(f"\n=== {sample}: {s['mutants']} mutants, {s['equivalent']} proved equivalent, "
          f"{s['scored']} scored, {len(s['unresolved_survivors'])} survived everything unresolved")
    print(f"{'technique':<44}{'killed':>8}{'survived':>10}{'score':>9}   {'95% interval':<17}{'cycles':>9}")

    def row(name, arm, cycles):
        ci = f"{pct(arm['ci95'][0])}-{pct(arm['ci95'][1])}" if "ci95" in arm else ""
        print(f"{name:<44}{arm['killed']:>8}{arm['survived']:>10}{pct(arm['score']):>9}   {ci:<17}{cycles:>9}")

    row("one smoke test", a["smoke"], a["smoke"]["cycles"])
    row("directed suite", a["directed"], a["directed"]["cycles"])
    for key, label in (("random_equal_cycles", "random, equal cycles"), ("random_long", "random, 10x cycles")):
        r = a[key]
        mean = {"killed": r["mean_killed"], "survived": round(s["scored"] - r["mean_killed"], 2), "score": r["mean_score"]}
        row(f"{label} (mean, {len(r['per_seed_killed'])} seeds)", mean, r["cycles"])
        print(f"{'':<4}per seed {r['min_killed']} to {r['max_killed']} killed; any seed: {r['union']['killed']}")
    f = a["formal"]
    row(f"formal, bounded ({f['frames']} cycles deep, div <= {f['max_div']})", f, "n/a")
    print(f"{'':<4}undecided {f['undecided']}, timed out {len(f['timeout'])}; median counterexample "
          f"{f['median_frame_of_kill']} cycles, deepest {f['deepest_kill_frame']}")
    row("any simulation arm", a["any_simulation"], "")
    row("any arm", a["anything"], "")

    print("\nkills and functional coverage against cycles spent")
    print(f"{'cycles':>9}{'directed killed':>18}{'random killed (mean)':>23}{'random bins (mean)':>21}")
    for c in s["curve"]:
        print(f"{c['cycles']:>9}{c['directed_killed']:>18}{c['random_mean_killed']:>23}{c['random_mean_bins']:>21}")
    cov = s["coverage"]
    closed = [v for v in cov["random_cycle_of_closure"].values() if v is not None]
    print(f"functional coverage: {cov['bins']} bins; smoke {cov['smoke_bins']}; directed suite "
          f"{cov['directed_cumulative'][-1]['bins_hit_so_far']}; random closes all bins in "
          f"{len(closed)} of {len(cov['random_cycle_of_closure'])} seeds"
          + (f" (cycle {min(closed)} to {max(closed)})" if closed else ""))


def main_report() -> None:
    proof = RESULTS / "proof.json"
    if proof.exists():
        p = load(proof)
        print(f"unbounded proof of the original design: with invariants {p['with_invariants']['status']}, "
              f"without {p['without_invariants']['status']}")
    for sample in ("dev", "confirmatory"):
        if (RESULTS / sample / "score.json").exists():
            table(sample)


def lookup(obj, path):
    for key in path:
        obj = obj[key] if isinstance(obj, dict) else obj[int(key)]
    return obj


def check_cited() -> list[str]:
    """Every entry of docs/CITED.json names a value in the results and the documents that
    quote it; the formatted value must appear in each of them."""
    problems = []
    if not CITED.exists():
        return problems
    for c in load(CITED):
        value = lookup(load(RESULTS / c["file"]), c["path"])
        if isinstance(value, list):
            value = len(value)
        text = c["format"].format(value * c.get("scale", 1))
        for doc in c["docs"]:
            if text not in (ROOT / doc).read_text():
                problems.append(f"{doc} does not contain {text!r} ({c['file']}:{'/'.join(map(str, c['path']))})")
    return problems
