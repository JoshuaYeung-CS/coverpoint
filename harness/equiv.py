"""Classify a mutant that nothing killed: is it a real survivor, or does it not change
behaviour at all?

Two copies of the mutant netlist are driven with the same inputs, one with mutsel = 0 and
one with mutsel = k, under the same environment the testbench guarantees (reset first,
legal APB). Three outcomes, never merged:

  different    a legal input sequence from reset makes some output differ
  equivalent   the outputs are proven equal for all time (ABC merges whatever logic of the
               two copies it can prove equal by induction, then runs PDR on what is left)
  unresolved   no difference found and no proof, inside the time budget
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .aig import build_aig, parse, run_abc
from .common import BUILD, MUTSEL_WIDTH, RESULTS, ROOT, TOP, dump, load, tool_env, yosys

INPUTS = [("pclk", 1), ("presetn", 1), ("psel", 1), ("penable", 1), ("pwrite", 1),
          ("paddr", 8), ("pwdata", 32), ("rxd", 1)]
OUTPUTS = [("prdata", 32), ("pready", 1), ("pslverr", 1), ("txd", 1), ("irq", 1)]

ENV_ASSUMPTIONS = '  `include "env.svh"'


def miter_text() -> str:
    def decl(w):
        return f"[{w - 1}:0] " if w > 1 else ""

    def conn(side):
        return ", ".join([f".{n}({n})" for n, _ in INPUTS] + [f".{n}({side}_{n})" for n, _ in OUTPUTS])

    lines = ["module miter(" + ", ".join(f"input {decl(w)}{n}" for n, w in INPUTS) + ");"]
    for side in ("g", "m"):
        lines += [f"  wire {decl(w)}{side}_{n};" for n, w in OUTPUTS]
    lines.append(f"  {TOP} u_gold ({conn('g')}, .mutsel({MUTSEL_WIDTH}'d0));")
    lines.append(f"  {TOP} u_mut  ({conn('m')}, .mutsel({MUTSEL_WIDTH}'d`MUT));")
    lines.append(ENV_ASSUMPTIONS)
    lines.append("  always @(*) if (!f_init) begin")
    lines += [f"    assert (g_{n} == m_{n});" for n, _ in OUTPUTS]
    lines += ["  end", "endmodule", ""]
    return "\n".join(lines)


def classify(sample: str, mut: int, bmc_frames: int, pdr_frames: int = 0, safety: int = 900) -> dict:
    """Bounded search for a difference to `bmc_frames` cycles; then, if `pdr_frames` is
    non-zero, an unbounded proof attempt. Budgets are depths, so the verdict does not
    depend on the machine; the safety timeout only ever turns a verdict into 'unresolved'."""
    work = BUILD / sample / "equiv"
    work.mkdir(parents=True, exist_ok=True)
    netlist = BUILD / sample / f"{TOP}_mut.v"
    for name, text in (("miter.sv", miter_text()), (netlist.name, netlist.read_text()),
                       ("env.svh", (ROOT / "formal" / "env.svh").read_text())):
        f = work / name
        if not f.exists() or f.read_text() != text:
            f.write_text(text)
    aig = build_aig(work, f"m{mut}", [f"read_verilog -sv -formal -DMUT={mut} miter.sv",
                                      f"read_verilog {netlist.name}"], "miter")
    script = f"scorr; dc2; bmc3 -F {bmc_frames} -T {safety}"
    if pdr_frames:
        script += f"; pdr -F {pdr_frames} -T {safety}"
    out, wall = run_abc(aig, script)
    res = parse(out)
    verdict = {"FAIL": "different", "PROVED": "equivalent", "UNDECIDED": "unresolved"}[res["status"]]
    for f in (aig, aig.with_suffix(".ys")):
        f.unlink(missing_ok=True)
    return {"id": mut, "verdict": verdict, "wall_s": round(wall, 2),
            **{k: v for k, v in res.items() if k != "status"}}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sample")
    ap.add_argument("--ids", type=int, nargs="*", help="mutant ids (default: all)")
    ap.add_argument("--bmc-frames", type=int, default=40)
    ap.add_argument("--pdr-frames", type=int, default=200)
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args()
    ids = a.ids or [m["id"] for m in load(RESULTS / a.sample / "mutants.json")["mutants"]]
    with ThreadPoolExecutor(a.jobs) as ex:
        recs = list(ex.map(lambda k: classify(a.sample, k, a.bmc_frames, a.pdr_frames), ids))
    dump(RESULTS / a.sample / "equivalence.json", {"bmc_frames": a.bmc_frames, "pdr_frames": a.pdr_frames, "mutants": recs})
    tally: dict[str, int] = {}
    for r in recs:
        tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1
    print(tally)


if __name__ == "__main__":
    main()
