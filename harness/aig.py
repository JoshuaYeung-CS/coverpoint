"""Turn a formal problem into an AIGER file with Yosys and hand it to ABC.

SymbiYosys with z3 proves the original design (harness/prove.py). For the hundreds of
bounded checks on mutants z3 is far too slow on this Mac (depth 14 in 15 minutes), so
those go to ABC's bit-level engines, which reach depth 30 in the time z3 reaches 12.

The Yosys steps are the ones SymbiYosys uses for its own AIGER back end, with one
addition: every register with no reset value in its declaration starts at zero
(`setundef -zero -init`). The environment asserts reset in the first cycle and nothing is
checked during it, so the pre-reset state cannot matter; pinning it lets ABC see that two
copies of the same logic start equal, which is what makes equivalence checking cheap.
"""
from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

from .common import ROOT, tool_env

ABC = ROOT / ".tools" / "abc" / "abc"

TO_AIG = """prep -top {top} -flatten
async2sync
chformal -assume -early
setundef -zero -init
opt_clean
formalff -clk2ff -ff2anyinit
chformal -live -fair -cover -remove
setundef -undriven -anyseq
opt -fast
formalff -assume
setattr -unset keep
delete -output
opt -full
techmap
opt -fast
simplemap
dffunmap
aigmap
opt_clean
write_aiger -I -B -zinit -no-startoffset {aig}
"""


def build_aig(work: Path, name: str, reads: list[str], top: str) -> Path:
    """`reads` are read_verilog lines; file names in them are relative to `work`."""
    script = work / f"{name}.ys"
    script.write_text("\n".join(reads) + "\n" + TO_AIG.format(top=top, aig=f"{name}.aig"))
    p = subprocess.run(["yowasp-yosys", "-q", "-s", script.name], cwd=work, env=tool_env(),
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"yosys failed on {script}:\n{p.stdout}\n{p.stderr}")
    return work / f"{name}.aig"


def run_abc(aig: Path, commands: str) -> tuple[str, float]:
    t0 = time.time()
    p = subprocess.run([str(ABC), "-c", f"read_aiger {aig.name}; fold; strash; {commands}"],
                       cwd=aig.parent, capture_output=True, text=True)
    return p.stdout + p.stderr, time.time() - t0


def parse(out: str) -> dict:
    """What ABC concluded. `frames` is how deep the bounded search got without a violation."""
    m = re.search(r"Output (\d+) of miter \S+ was asserted in frame (\d+)", out)
    if m:
        return {"status": "FAIL", "output": int(m.group(1)), "frame": int(m.group(2))}
    if "Property proved" in out or "Networks are equivalent" in out:
        return {"status": "PROVED"}
    frames = [int(x) for x in re.findall(r"No output (?:asserted|failed) in (\d+) frames", out)]
    frames += [int(x) for x in re.findall(r"Reached timeout \(\d+ seconds\) in frame (\d+)", out)]
    return {"status": "UNDECIDED", "frames": max(frames) if frames else 0}
