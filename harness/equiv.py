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
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .aig import build_aig, parse, run_abc
from .common import BUILD, MUTSEL_WIDTH, RESULTS, ROOT, TOP, dump, load, tool_env, yosys

INPUTS = [("pclk", 1), ("presetn", 1), ("psel", 1), ("penable", 1), ("pwrite", 1),
          ("paddr", 8), ("pwdata", 32), ("rxd", 1)]
OUTPUTS = [("prdata", 32), ("pready", 1), ("pslverr", 1), ("txd", 1), ("irq", 1)]

ENV_ASSUMPTIONS = '  `include "env.svh"'


def exposed_netlist(sample: str) -> tuple[Path, list[tuple[str, int]]]:
    """A copy of the sample's netlist with every register also brought out as an output,
    so the miter can state 'all state equal' without knowing any internal name."""
    out = BUILD / sample
    rel = out.relative_to(ROOT)
    path = out / f"{TOP}_exposed.v"
    if not path.exists():
        yosys(f"read_verilog {rel}/{TOP}_mut.v; hierarchy -top {TOP}; proc; opt_clean; "
              f"expose -dff; opt_clean; write_verilog -noattr {rel}/{TOP}_exposed.v")
    known = {n for n, _ in INPUTS + OUTPUTS} | {"mutsel"}
    regs = []
    for m in re.finditer(r"^\s*output (?:\[(\d+):0\] )?(\S+)\s*;", path.read_text(), re.M):
        name = m.group(2)
        if name not in known:
            regs.append((name, int(m.group(1) or 0) + 1))
    return path, regs


def miter_text(regs: list[tuple[str, int]], with_state: bool) -> str:
    def decl(n, w):
        return f"[{w - 1}:0] " if w > 1 else ""

    def conn(side):
        pins = [f".{n}({n})" for n, _ in INPUTS]
        pins += [f".{n}({side}_{n})" for n, _ in OUTPUTS]
        pins += [f".{esc(n)}({side}_s{i})" for i, (n, _) in enumerate(regs)]
        return ", ".join(pins)

    def esc(n):
        return n + " " if n.startswith("\\") else n

    lines = ["module miter(" + ", ".join(f"input {decl(n, w)}{n}" for n, w in INPUTS) + ");"]
    for side in ("g", "m"):
        lines += [f"  wire {decl(n, w)}{side}_{n};" for n, w in OUTPUTS]
        lines += [f"  wire {decl(n, w)}{side}_s{i};" for i, (n, w) in enumerate(regs)]
    lines.append(f"  {TOP} u_gold ({conn('g')}, .mutsel({MUTSEL_WIDTH}'d0));")
    lines.append(f"  {TOP} u_mut  ({conn('m')}, .mutsel({MUTSEL_WIDTH}'d`MUT));")
    lines.append(ENV_ASSUMPTIONS)
    lines.append("  always @(*) if (!f_init) begin")
    lines += [f"    assert (g_{n} == m_{n});" for n, _ in OUTPUTS]
    if with_state:
        lines += [f"    assert (g_s{i} == m_s{i});" for i in range(len(regs))]
    lines += ["  end", "endmodule", ""]
    return "\n".join(lines)


def classify(sample: str, mut: int, seconds: int) -> dict:
    """Bounded search for a difference, then an unbounded proof attempt (PDR), each inside
    `seconds` of wall-clock."""
    work = BUILD / sample / "equiv"
    netlist, regs = exposed_netlist(sample)
    work.mkdir(parents=True, exist_ok=True)
    miter = work / "miter_ports.sv"
    if not miter.exists():
        miter.write_text(miter_text([], with_state=False))
        (work / netlist.name).write_text(netlist.read_text())
        (work / "env.svh").write_text((ROOT / "formal" / "env.svh").read_text())
    aig = build_aig(work, f"m{mut}", [f"read_verilog -sv -formal -DMUT={mut} miter_ports.sv",
                                      f"read_verilog {netlist.name}"], "miter")
    out, wall = run_abc(aig, f"scorr; dc2; bmc3 -F 100000 -T {seconds}; pdr -T {seconds}")
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
    ap.add_argument("--seconds", type=int, default=120, help="wall-clock budget per engine per mutant")
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args()
    ids = a.ids or [m["id"] for m in load(RESULTS / a.sample / "mutants.json")["mutants"]]
    exposed_netlist(a.sample)
    with ThreadPoolExecutor(a.jobs) as ex:
        recs = list(ex.map(lambda k: classify(a.sample, k, a.seconds), ids))
    dump(RESULTS / a.sample / "equivalence.json", {"seconds": a.seconds, "mutants": recs})
    tally: dict[str, int] = {}
    for r in recs:
        tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1
    print(tally)


if __name__ == "__main__":
    main()
