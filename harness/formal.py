"""Run the formal property set against mutants.

The property module (formal/cp_uart_props.sv) only touches top-level ports, so the same
file checks every mutant. For each mutant ABC searches, breadth first from reset, for any
legal input sequence that violates any property, up to a fixed number of clock cycles.
The budget is a depth, not a time, so the outcome does not depend on how fast or how busy
the machine is; seconds are recorded as cost only. Two outcomes, never merged:

  FAIL        a real counterexample from reset exists; its length in cycles is recorded
  UNDECIDED   no violation within the depth

A run that hits the safety timeout before reaching the depth is flagged, not scored.

UNDECIDED is not a pass and is never counted as a kill. The design itself is not checked
here: it is proved for all time in harness/prove.py.
"""
from __future__ import annotations

import argparse
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .aig import build_aig, parse, run_abc
from .common import BUILD, RESULTS, ROOT, TOP, dump, load

FORMAL = ROOT / "formal"
# The order of the assertions in formal/asserts.svh; ABC reports a violated output by index.
PROPERTY_FILES = ("cp_uart_props.sv", "env.svh", "shadow.svh", "asserts.svh")


def check(sample: str, mut: int, frames: int, max_div: int, safety: int = 900) -> dict:
    work = BUILD / sample / "formal"
    work.mkdir(parents=True, exist_ok=True)
    for src in [FORMAL / f for f in PROPERTY_FILES] + [BUILD / sample / f"{TOP}_mut.v"]:
        dst = work / src.name
        if not dst.exists() or dst.read_bytes() != src.read_bytes():
            shutil.copyfile(src, dst)
    aig = build_aig(work, f"m{mut}", [
        f"read_verilog -sv -formal -DMUT={mut} -DFV_MAX_DIV={max_div} cp_uart_props.sv",
        f"read_verilog {TOP}_mut.v"], "cp_uart_fv")
    out, wall = run_abc(aig, f"scorr; dc2; bmc3 -F {frames} -T {safety}")
    rec = {"id": mut, "wall_s": round(wall, 2), **parse(out)}
    if rec["status"] == "UNDECIDED" and rec["frames"] < frames:
        rec["status"] = "TIMEOUT"
    for f in (aig, aig.with_suffix(".ys")):
        f.unlink(missing_ok=True)
    return rec


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sample")
    ap.add_argument("--ids", type=int, nargs="*")
    ap.add_argument("--frames", type=int, required=True, help="depth of the bounded search, in clock cycles")
    ap.add_argument("--max-div", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--out")
    a = ap.parse_args()
    ids = a.ids if a.ids is not None else [0] + [m["id"] for m in load(RESULTS / a.sample / "mutants.json")["mutants"]]
    with ThreadPoolExecutor(a.jobs) as ex:
        recs = list(ex.map(lambda k: check(a.sample, k, a.frames, a.max_div), ids))
    tally: dict[str, int] = {}
    for r in recs:
        tally[r["status"]] = tally.get(r["status"], 0) + 1
    print(tally, f"{sum(r['wall_s'] for r in recs):.0f} s of solver time")
    if a.out:
        dump(Path(a.out), {"frames": a.frames, "max_div": a.max_div, "runs": recs})


if __name__ == "__main__":
    main()
