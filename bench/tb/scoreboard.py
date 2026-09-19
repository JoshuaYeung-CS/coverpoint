"""The checker. One reference model, stepped in lockstep with the device, compared on
every output in every cycle. It is the same for every test, directed or random, so a
difference in what two tests catch is a difference in stimulus and nothing else."""
import cocotb
from cocotb.triggers import Event, FallingEdge, ReadOnly
from pyuvm import uvm_scoreboard

from bench.model import UartModel

INPUTS = ("presetn", "psel", "penable", "pwrite", "paddr", "pwdata", "rxd")
OUTPUTS = ("prdata", "pready", "pslverr", "txd", "irq")


class LockstepScoreboard(uvm_scoreboard):
    def build_phase(self):
        self.dut = cocotb.top
        self.model = UartModel()
        self.budget = 0                 # 0 = no limit; set by the test
        self.cycle = 0
        self.armed = False              # outputs mean nothing before the first reset edge
        self.mismatch = None            # (cycle, signal, expected, got)
        self.finished = Event()
        self.listeners = []             # called after every model step: f(model, inputs, cycle)

    async def run_phase(self):
        d, m = self.dut, self.model
        ins_h = [getattr(d, n) for n in INPUTS]
        outs_h = [getattr(d, n) for n in OUTPUTS]
        while True:
            await FallingEdge(d.pclk)
            await ReadOnly()
            ins = [int(h.value) for h in ins_h]
            if self.armed:
                prdata, pready, pslverr = m.comb(*ins[1:6])
                expected = (prdata, pready, pslverr, m.txd, m.irq)
                for name, h, exp in zip(OUTPUTS, outs_h, expected):
                    got = int(h.value)
                    if got != exp:
                        self.mismatch = (self.cycle, name, exp, got)
                        self.finished.set()
                        return
            m.step(*ins)
            if ins[0] == 0:
                self.armed = True
            for f in self.listeners:
                f(m, ins, self.cycle)
            self.cycle += 1
            if self.budget and self.cycle >= self.budget:
                self.finished.set()
                return
