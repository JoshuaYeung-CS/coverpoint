"""Supplementary: Verilator line and toggle coverage of the ORIGINAL RTL under each
simulation arm. Not part of the pre-registered score. Structural coverage of a mutated
netlist would mean nothing, so this runs on rtl/ only."""
from __future__ import annotations

import re
from collections import defaultdict

from . import simrun
from .common import BUILD, RESULTS, ROOT, dump, load


def points(dat) -> dict:
    """{(type, point): count} from one coverage.dat."""
    out = {}
    for line in dat.read_text(errors="replace").splitlines():
        if not line.startswith("C '"):
            continue
        key, count = line[3:].rsplit("' ", 1)
        kind = re.search("\x01t\x02(\\w+)", key)
        out[(kind.group(1) if kind else "other", key)] = int(count)
    return out


def summarise(runs: list[tuple[str, int, int]]) -> dict:
    total = defaultdict(int)
    for test, seed, budget in runs:
        simrun.run_one("rtl", 0, test, seed, budget)
        for k, v in points(BUILD / "rtl" / "runs" / f"{test}_s{seed}_m0" / "coverage.dat").items():
            total[k] += v
    res = {}
    for kind in sorted({k[0] for k in total}):
        hit = sum(1 for k, v in total.items() if k[0] == kind and v > 0)
        n = sum(1 for k in total if k[0] == kind)
        res[kind] = {"hit": hit, "points": n, "percent": round(100 * hit / n, 1)}
    return res


def main() -> None:
    plan = load(ROOT / "docs" / "prereg.json")
    simrun.build("rtl")
    rnd = plan["random"]
    res = {
        "smoke": summarise([(plan["baseline_test"], 0, 0)]),
        "directed": summarise([(t, 0, 0) for t in plan["directed"]]),
        "random_one_seed_equal_cycles": summarise([(rnd["test"], 0, rnd["budget_equal"])]),
    }
    dump(RESULTS / "structural.json", res)
    for arm, r in res.items():
        print(arm, {k: f"{v['hit']}/{v['points']} ({v['percent']}%)" for k, v in r.items()})


if __name__ == "__main__":
    main()
