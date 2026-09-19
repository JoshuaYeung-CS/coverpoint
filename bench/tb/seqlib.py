"""Small helpers every sequence uses."""
import cocotb
from cocotb.triggers import FallingEdge
from pyuvm import uvm_sequence

from . import regs
from .items import ApbItem, RxFrameItem


async def wait_cycles(n):
    for _ in range(n):
        await FallingEdge(cocotb.top.pclk)


class ApbSeq(uvm_sequence):
    """Base for sequences that run on the APB sequencer."""

    async def wr(self, addr, data, idle=1):
        item = ApbItem("wr", write=True, addr=addr, data=data, idle=idle)
        await self.start_item(item)
        await self.finish_item(item)
        return item

    async def rd(self, addr, idle=1):
        item = ApbItem("rd", write=False, addr=addr, idle=idle)
        await self.start_item(item)
        await self.finish_item(item)
        return item

    async def status(self):
        return (await self.rd(regs.STATUS)).rdata


class RxSeq(uvm_sequence):
    """Base for sequences that run on the UART (rxd) sequencer."""

    async def frame(self, byte, period=1, parity=None, **kw):
        item = RxFrameItem("rxf", byte=byte, period=period, parity=parity, **kw)
        await self.start_item(item)
        await self.finish_item(item)
        return item

    async def glitch(self, cycles, gap=0):
        item = RxFrameItem("glitch", glitch=cycles, gap=gap)
        await self.start_item(item)
        await self.finish_item(item)
        return item


def frame_cycles(div, parity=False, stop2=False):
    """Clock cycles one transmitted frame occupies (SPEC section 5)."""
    return (10 + int(parity) + int(stop2)) * (div + 1)
