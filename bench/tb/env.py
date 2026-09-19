"""Environment and base test."""
import json
import os
import random

import cocotb
from cocotb.triggers import FallingEdge, First
from pyuvm import ConfigDB, uvm_env, uvm_test

from .agents import ApbAgent, UartAgent
from .scoreboard import LockstepScoreboard

RESULT = {}                              # filled in by the test, written out by entry.py


class Env(uvm_env):
    def build_phase(self):
        self.apb = ApbAgent("apb", self)
        self.uart = UartAgent("uart", self)
        self.sb = LockstepScoreboard("sb", self)


class BaseTest(uvm_test):
    """Reset, run `main_seq`, stop at the first mismatch, the budget, or the end of the
    stimulus plus a drain, whichever comes first."""

    drain = 40                            # cycles to keep checking after the stimulus ends

    def build_phase(self):
        self.env = Env("env", self)
        self.seed = int(os.environ.get("CP_SEED", "0"))
        self.rng = random.Random(self.seed)
        ConfigDB().set(None, "*", "rng", self.rng)

    def end_of_elaboration_phase(self):
        self.env.sb.budget = int(os.environ.get("CP_BUDGET", "0"))
        if os.environ.get("CP_COVER", "0") == "1":
            from .coverage import Coverage
            self.cov = Coverage(self.env)
        else:
            self.cov = None

    async def main_seq(self):
        raise NotImplementedError

    async def reset(self, cycles=2):
        d = cocotb.top
        await FallingEdge(d.pclk)
        d.presetn.value = 0
        for _ in range(cycles):
            await FallingEdge(d.pclk)
        d.presetn.value = 1

    async def _stimulus(self):
        await self.reset()
        await self.main_seq()
        for _ in range(self.drain):
            await FallingEdge(cocotb.top.pclk)

    async def run_phase(self):
        self.raise_objection()
        sb = self.env.sb
        stim = cocotb.start_soon(self._stimulus())
        await First(sb.finished.wait(), stim.complete)
        RESULT.update({
            "killed": sb.mismatch is not None,
            "kill_cycle": sb.mismatch[0] if sb.mismatch else None,
            "kill_signal": sb.mismatch[1] if sb.mismatch else None,
            "kill_expected": sb.mismatch[2] if sb.mismatch else None,
            "kill_got": sb.mismatch[3] if sb.mismatch else None,
            "cycles": sb.cycle,
            "stimulus_finished": stim.done(),
        })
        if self.cov is not None:
            RESULT["coverage"] = self.cov.report()
        self.drop_objection()
