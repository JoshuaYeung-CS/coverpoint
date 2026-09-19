"""Paths, tool environment and small helpers shared by the harness."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RTL = sorted((ROOT / "rtl").glob("*.sv"))
TOP = "cp_uart"
BUILD = ROOT / "build"
RESULTS = ROOT / "results"
MUTSEL_WIDTH = 16

# Everything Yosys does to the design before mutants are listed or applied. The list
# step and the apply step must run exactly this, or cell names stop matching.
#   -flatten     one module, so a mutant anywhere gets the top-level mutsel input
#   memory_map   FIFO storage becomes flops and muxes that write_verilog can emit
#   pmuxtree     parallel muxes become ordinary mux trees, so the simulator and the
#                solver cannot disagree about a mutant that makes two selects fire
PREP = f"prep -top {TOP} -flatten; memory_map; pmuxtree; opt_clean"


def tool_env() -> dict[str, str]:
    """Environment for the project-local tools. The venv must come before the conda
    prefix: conda ships its own python, which breaks the Verilator build if found first."""
    env = dict(os.environ)
    env["PATH"] = f"{ROOT / '.venv' / 'bin'}:{ROOT / '.cenv' / 'bin'}:{env.get('PATH', '')}"
    env["YOWASP_CACHE_DIR"] = str(ROOT / ".cache" / "yowasp")
    return env


def yosys(script: str, cwd: Path | None = None, quiet: bool = True) -> str:
    """Run a Yosys script and return its output. Raises on a non-zero exit."""
    cmd = ["yowasp-yosys"] + (["-q"] if quiet else []) + ["-p", script]
    out = subprocess.run(cmd, cwd=cwd or ROOT, env=tool_env(), capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"yosys failed:\n{out.stdout}\n{out.stderr}")
    return out.stdout


def read_sources() -> str:
    return "; ".join(f"read_verilog -sv {p.relative_to(ROOT)}" for p in RTL)


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n")


def load(path: Path):
    return json.loads(path.read_text())
