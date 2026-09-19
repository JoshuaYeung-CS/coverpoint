"""The unbounded proof of the original design.

SymbiYosys, k-induction, z3. The specification shadow, the output assertions and the
refinement invariants are compiled into the device module (CP_FORMAL_WHITEBOX), with no
bound on the baud divisor. Two runs, and the contrast between them is the point:

  with the invariants      PASS     every output matches the specification on every
                                    cycle, for every legal input sequence, forever
  without the invariants   UNKNOWN  the same assertions, the same design: the base case
                                    passes and the induction step fails, from a starting
                                    state that no reset sequence can reach

UNKNOWN is not FAIL. Nothing is wrong with the design in the second run; the claim is
simply not inductive on its own.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time

from .common import BUILD, RESULTS, ROOT, RTL, dump, tool_env

FILES = ("env.svh", "shadow.svh", "asserts.svh", "invariants.svh")


def sby_text(defines: str, depth: int) -> str:
    rtl = " ".join(p.name for p in RTL)
    files = "\n".join([p.name for p in RTL] + list(FILES))
    return f"""[options]
mode prove
depth {depth}
[engines]
smtbmc z3
[script]
read_verilog -sv -formal {defines} {rtl}
prep -top cp_uart
[files]
{files}
"""


def run(name: str, defines: str, depth: int) -> dict:
    work = BUILD / "proof"
    work.mkdir(parents=True, exist_ok=True)
    for src in list(RTL) + [ROOT / "formal" / f for f in FILES]:
        shutil.copyfile(src, work / src.name)
    (work / f"{name}.sby").write_text(sby_text(defines, depth))
    t0 = time.time()
    p = subprocess.run(["yowasp-sby", "-f", "--yosys", "yowasp-yosys", "--smtbmc", "yowasp-yosys-smtbmc",
                        f"{name}.sby"], cwd=work, env=tool_env(), capture_output=True, text=True)
    status = re.search(r"DONE \((\w+), rc=(\d+)\)", p.stdout)
    engines = {which: result for result, which in re.findall(r"returned (\w+) for (basecase|induction)", p.stdout)}
    failed = sorted(set(re.findall(r"induction: .*Assert failed in cp_uart: (\S+)", p.stdout)))
    return {"status": status.group(1) if status else "ERROR", "depth": depth,
            "basecase": engines.get("basecase"), "induction": engines.get("induction"),
            "induction_failed_on": failed, "wall_s": round(time.time() - t0, 1)}


def main(out=None) -> dict:
    res = {
        "with_invariants": run("with_invariants", "-DCP_FORMAL_WHITEBOX", 2),
        "without_invariants": run("without_invariants", "-DCP_FORMAL_WHITEBOX -DCP_FORMAL_NO_INVARIANTS", 2),
    }
    stable = {k: {x: y for x, y in v.items() if x != "wall_s"} for k, v in res.items()}
    dump((out or RESULTS) / "proof.json", stable)
    print({k: (v["status"], v["wall_s"]) for k, v in res.items()})
    return stable


if __name__ == "__main__":
    main()
