"""The one cocotb test. The harness picks the pyuvm test, the mutant, the seed and the
cycle budget through CP_* environment variables and reads the result back as JSON."""
import json
import os

import cocotb
import pyuvm
from cocotb.clock import Clock

from . import tests  # noqa: F401  (registers the pyuvm tests)
from .env import RESULT


@cocotb.test()
async def run(dut):
    for name in ("psel", "penable", "pwrite", "paddr", "pwdata"):
        getattr(dut, name).value = 0
    dut.presetn.value = 1
    dut.rxd.value = 1
    if os.environ.get("CP_HAS_MUTSEL", "1") == "1":
        dut.mutsel.value = int(os.environ.get("CP_MUTSEL", "0"))
    cocotb.start_soon(Clock(dut.pclk, 10, unit="ns").start())
    await pyuvm.uvm_root().run_test(os.environ["CP_TEST"])
    out = os.environ.get("CP_OUT")
    if out:
        with open(out, "w") as f:
            json.dump(RESULT, f)
