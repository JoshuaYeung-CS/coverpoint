"""pyuvm tests, selected by name through CP_TEST."""
import cocotb

from . import regs
from .directed import *  # noqa: F401,F403
from .env import BaseTest
from .random_seqs import ApbRandomSeq, Knobs, Line, RxRandomSeq
from .seqlib import ApbSeq, wait_cycles


class SmokeSeq(ApbSeq):
    """The first test anyone writes: send one byte through loopback and read it back."""

    async def body(self):
        await self.wr(regs.CTRL, regs.TX_EN | regs.RX_EN | regs.LOOPBACK)
        await self.wr(regs.TXDATA, 0xA5)
        await wait_cycles(20)
        await self.status()
        await self.rd(regs.RXDATA)
        await self.status()


class smoke(BaseTest):
    async def main_seq(self):
        await SmokeSeq("smoke").start(self.env.apb.seqr)


class random_mix(BaseTest):
    """Constrained-random stimulus on both interfaces until the cycle budget runs out."""

    knobs = Knobs()

    async def main_seq(self):
        line = Line()
        apb = ApbRandomSeq("apb_random", self.rng, line, self.knobs, self.reset)
        rx = RxRandomSeq("rx_random", self.rng, line, self.knobs)
        cocotb.start_soon(rx.start(self.env.uart.seqr))
        await apb.start(self.env.apb.seqr)
