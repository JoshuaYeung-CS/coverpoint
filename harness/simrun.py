"""Run the simulation bench against mutants.

The mutant netlist is compiled by Verilator once per sample. Every (mutant, test, seed)
is then its own simulator process, told which mutant to switch on through CP_MUTSEL, so
no state can leak from one run to the next. The bench writes one JSON record per run.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .common import BUILD, RESULTS, ROOT, RTL, TOP, dump, load, tool_env

VERILATOR_ARGS = ["-Wno-fatal", "-Wno-WIDTHEXPAND", "-Wno-WIDTHTRUNC", "-Wno-CASEOVERLAP",
                  "-Wno-UNOPTFLAT", "-Wno-DECLFILENAME", "-Wno-UNUSEDSIGNAL", "-O3"]
TEST_MODULE = "bench.tb.entry"


def _runner():
    from cocotb_tools.runner import get_runner
    return get_runner("verilator")


def build(sample: str) -> Path:
    """Compile the sample's netlist (or, for sample 'rtl', the original RTL with
    Verilator's structural coverage switched on)."""
    os.environ.update({k: v for k, v in tool_env().items() if k in ("PATH", "YOWASP_CACHE_DIR")})
    build_dir = BUILD / sample / "sim_build"
    if sample == "rtl":
        sources, args = RTL, VERILATOR_ARGS + ["--coverage"]
    else:
        sources, args = [BUILD / sample / f"{TOP}_mut.v"], VERILATOR_ARGS
    _runner().build(sources=sources, hdl_toplevel=TOP, build_dir=build_dir, build_args=args, always=False)
    return build_dir


def run_one(sample: str, mutsel: int, test: str, seed: int, budget: int, cover: bool = False) -> dict:
    """One simulator process. Returns the bench's record, or an 'error' record if the
    process produced none (which is reported, never counted as a kill)."""
    build_dir = BUILD / sample / "sim_build"
    tag = f"{test}_s{seed}_m{mutsel}"
    work = BUILD / sample / "runs" / tag
    work.mkdir(parents=True, exist_ok=True)
    out = work / "result.json"
    out.unlink(missing_ok=True)
    env = tool_env()
    env.update({
        "CP_MUTSEL": str(mutsel), "CP_TEST": test, "CP_SEED": str(seed), "CP_BUDGET": str(budget),
        "CP_OUT": str(out), "CP_COVER": "1" if cover else "0", "CP_HAS_MUTSEL": "0" if sample == "rtl" else "1",
        "COCOTB_TEST_MODULES": TEST_MODULE, "COCOTB_TOPLEVEL": TOP, "TOPLEVEL_LANG": "verilog",
        "COCOTB_RESULTS_FILE": str(work / "results.xml"),
        "COCOTB_LOG_LEVEL": "WARNING", "COCOTB_REDUCED_LOG_FMT": "1",
    })
    import cocotb_tools.config
    import find_libpython
    env["PATH"] += os.pathsep + str(cocotb_tools.config.libs_dir)
    env["GPI_USERS"] = ";".join([find_libpython.find_libpython(), cocotb_tools.config.pygpi_entry_point()])
    env["PYGPI_PYTHON_BIN"] = sys.executable
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), *sys.path])
    t0 = time.time()
    with open(work / "sim.log", "w") as log:
        subprocess.run([str(build_dir / TOP)], cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT)
    if out.exists():
        rec = json.loads(out.read_text())
    else:
        rec = {"error": "no result written", "killed": False}
    rec.update({"mutsel": mutsel, "test": test, "seed": seed, "budget": budget,
                "wall_s": round(time.time() - t0, 2)})
    return rec


def run_matrix(sample: str, jobs_spec: list[tuple[int, str, int, int]], jobs: int) -> list[dict]:
    build(sample)
    with ThreadPoolExecutor(jobs) as ex:
        return list(ex.map(lambda j: run_one(sample, *j), jobs_spec))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sample")
    ap.add_argument("--test", required=True)
    ap.add_argument("--seeds", type=int, nargs="+", default=[0])
    ap.add_argument("--budget", type=int, required=True)
    ap.add_argument("--ids", type=int, nargs="*")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.ids is None:
        a.ids = [0] + [m["id"] for m in load(RESULTS / a.sample / "mutants.json")["mutants"]]
    spec = [(k, a.test, s, a.budget) for s in a.seeds for k in a.ids]
    recs = run_matrix(a.sample, spec, a.jobs)
    killed = sum(1 for r in recs if r.get("killed") and r["mutsel"] != 0)
    print(f"{a.test}: {len(recs)} runs, {killed} kills, "
          f"{sum(1 for r in recs if 'error' in r)} errors, "
          f"{sum(r['wall_s'] for r in recs):.0f} s of simulator time")
    if a.out:
        dump(Path(a.out), recs)


if __name__ == "__main__":
    main()
