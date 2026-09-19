"""Sequence items: what a sequence asks an agent to do."""
from pyuvm import uvm_sequence_item


class ApbItem(uvm_sequence_item):
    """One APB transfer, preceded by `idle` cycles with psel low (0 = back to back)."""

    def __init__(self, name="apb", write=False, addr=0, data=0, idle=1):
        super().__init__(name)
        self.write, self.addr, self.data, self.idle = write, addr, data, idle
        self.rdata = 0      # filled in by the driver
        self.slverr = 0

    def __str__(self):
        kind = "W" if self.write else "R"
        return f"APB {kind} @{self.addr:#04x} data={self.data:#x} rdata={self.rdata:#x} err={self.slverr}"


class RxFrameItem(uvm_sequence_item):
    """One frame driven onto rxd, preceded by `gap` idle cycles.

    period is clocks per bit (the device expects BAUD + 1). parity is None, "even" or
    "odd". bad_parity sends the wrong parity bit; bad_stop sends a 0 where the stop bit
    belongs. glitch > 0 drives rxd low for that many cycles INSTEAD of a frame (a false
    start when it is shorter than the device's start-bit check point).
    """

    def __init__(self, name="rxf", byte=0, period=1, parity=None, bad_parity=False, bad_stop=False,
                 gap=0, glitch=0):
        super().__init__(name)
        self.byte, self.period, self.parity = byte, period, parity
        self.bad_parity, self.bad_stop, self.gap, self.glitch = bad_parity, bad_stop, gap, glitch

    def bits(self):
        if self.glitch:
            return [0]
        out = [0] + [(self.byte >> k) & 1 for k in range(8)]
        if self.parity is not None:
            p = bin(self.byte).count("1") & 1
            if self.parity == "odd":
                p ^= 1
            out.append(p ^ 1 if self.bad_parity else p)
        out.append(0 if self.bad_stop else 1)
        return out
