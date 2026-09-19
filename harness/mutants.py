"""Mechanical bug source: sample single-point mutations of the elaborated design with
Yosys `mutate`, and build ONE netlist that holds all of them behind a `mutsel` input.

`mutsel = 0` is the unmutated design; `mutsel = k` activates mutant k and nothing else.
One netlist means one Verilator build per sample, and the same file serves simulation,
the formal property runs and the equivalence miter. The method is the one YosysHQ's MCY
(Mutation Cover with Yosys) uses; nothing of MCY itself is used here.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shlex
import subprocess
from pathlib import Path

from . import guard
from .common import BUILD, MUTSEL_WIDTH, PREP, RESULTS, ROOT, RTL, TOP, dump, read_sources, tool_env, yosys

FIELDS = ("mode", "module", "cell", "port", "portbit", "ctrlbit", "wire", "wirebit")


def rtl_digest() -> str:
    h = hashlib.sha256()
    for p in RTL:
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def parse_line(line: str) -> dict:
    """One `mutate ...` command, as written by `mutate -list`, into a record."""
    tok = shlex.split(line.replace("\\", "\\\\"))
    rec: dict = {"src": []}
    i = 1
    while i < len(tok):
        t = tok[i]
        if t == "-ctrl":
            rec["id"] = int(tok[i + 3])
            i += 4
        elif t == "-src":
            rec["src"].append(tok[i + 1])
            i += 2
        elif t.startswith("-") and t[1:] in FIELDS:
            rec[t[1:]] = tok[i + 1]
            i += 2
        else:
            raise ValueError(f"unexpected token {t!r} in {line!r}")
    for f in ("portbit", "ctrlbit", "wirebit"):
        if f in rec:
            rec[f] = int(rec[f])
    # What makes two mutants the same mutant, whatever sample they were drawn in.
    rec["key"] = "|".join(str(rec.get(f, "")) for f in ("mode", "cell", "port", "portbit", "ctrlbit"))
    return rec


def generate(sample: str, seed: int, count: int) -> dict:
    guard.check_sample_allowed(sample, seed, count)
    out = BUILD / sample
    out.mkdir(parents=True, exist_ok=True)
    rel = out.relative_to(ROOT)
    listing = out / "mutants.ys"
    yosys(f"{read_sources()}; {PREP}; "
          f"mutate -list {count} -seed {seed} -ctrl mutsel {MUTSEL_WIDTH} 1 -o {rel}/mutants.ys")
    lines = [ln for ln in listing.read_text().splitlines() if ln.startswith("mutate ")]

    script = out / "apply.ys"
    script.write_text("\n".join([*read_sources().split("; "), *PREP.split("; "), *lines,
                                 "opt_clean", f"write_verilog -noattr {rel}/{TOP}_mut.v"]) + "\n")
    yosys(f"script {rel}/apply.ys")

    netlist = out / f"{TOP}_mut.v"
    text = netlist.read_text()
    if not re.search(rf"input \[{MUTSEL_WIDTH - 1}:0\] mutsel;", text):
        raise RuntimeError("mutsel did not come out as a top-level input")

    banner = subprocess.run(["yowasp-yosys", "-V"], env=tool_env(), capture_output=True, text=True).stdout
    version = " ".join(banner.split()[:5])
    mutants = [parse_line(ln) for ln in lines]
    assert [m["id"] for m in mutants] == list(range(1, len(mutants) + 1))
    record = {
        "sample": sample, "seed": seed, "requested": count, "count": len(mutants),
        "distinct_keys": len({m["key"] for m in mutants}),
        "yosys": version, "prep": PREP, "rtl_sha256": rtl_digest(),
        "netlist_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "mutants": mutants,
    }
    dump(RESULTS / sample / "mutants.json", record)
    return record


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sample", help="sample name, e.g. dev or confirmatory")
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--count", type=int, required=True)
    a = ap.parse_args()
    rec = generate(a.sample, a.seed, a.count)
    modes: dict[str, int] = {}
    for m in rec["mutants"]:
        modes[m["mode"]] = modes.get(m["mode"], 0) + 1
    tagged = sum(1 for m in rec["mutants"] if m["src"])
    print(f"{rec['sample']}: {rec['count']} mutants ({rec['distinct_keys']} distinct), "
          f"modes {modes}, {tagged} with a source location")


if __name__ == "__main__":
    main()
