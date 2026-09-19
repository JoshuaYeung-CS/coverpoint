"""Constrained-random stimulus.

Two sequences run side by side: one programs the device over APB the way driver software
might (configure, send, poll, drain, acknowledge interrupts, occasionally misbehave), the
other plays the far end of the serial line. They share a `Line` object so the far end
normally talks at the speed and parity the device was last told to expect, and
deliberately does not some of the time.

Every choice is drawn from one seeded generator, and every weight is in `Knobs`, so a
run is reproduced exactly by its seed and the stimulus mix is a reviewable table rather
than something buried in code.
"""
from dataclasses import dataclass, field

from . import regs
from .seqlib import ApbSeq, RxSeq, wait_cycles


@dataclass
class Knobs:
    # relative weights of the APB operations
    ops: dict = field(default_factory=lambda: {
        "send": 22, "drain": 14, "status": 10, "config": 8, "baud": 5, "irq_en": 5, "irq_ack": 8,
        "read_any": 6, "bad_access": 3, "pause": 12, "toggle_enable": 4, "reset": 1,
    })
    # baud divisor: mostly tiny so that many frames fit in the budget, sometimes realistic
    div_choices: tuple = ((0, 30), (1, 20), (2, 10), (3, 10), ("4-15", 18), ("16-255", 3))
    idle_choices: tuple = ((0, 35), (1, 30), (2, 15), ("3-8", 15), ("9-40", 5))
    special_bytes: tuple = (0x00, 0xFF, 0x55, 0xAA)
    p_special_byte: float = 0.25
    # the far end of the line
    p_rx_bad_parity: float = 0.12
    p_rx_bad_stop: float = 0.08
    p_rx_glitch: float = 0.06
    p_rx_wrong_speed: float = 0.04
    p_rx_back_to_back: float = 0.45
    rx_gap_max: int = 60


class Line:
    """What the device was last programmed with, as far as the stimulus knows."""

    def __init__(self):
        self.ctrl = 0
        self.div = 0

    @property
    def parity(self):
        if not self.ctrl & regs.PAR_EN:
            return None
        return "odd" if self.ctrl & regs.PAR_ODD else "even"


def pick(rng, choices):
    values, weights = zip(*choices)
    v = rng.choices(values, weights)[0]
    if isinstance(v, str):
        lo, hi = map(int, v.split("-"))
        return rng.randint(lo, hi)
    return v


def rand_byte(rng, k):
    if rng.random() < k.p_special_byte:
        return rng.choice(k.special_bytes)
    return rng.randrange(256)


class ApbRandomSeq(ApbSeq):
    def __init__(self, name, rng, line, knobs, reset_cb):
        super().__init__(name)
        self.rng, self.line, self.k, self.reset_cb = rng, line, knobs, reset_cb

    def idle(self):
        return pick(self.rng, self.k.idle_choices)

    async def body(self):
        rng, k = self.rng, self.k
        names, weights = zip(*k.ops.items())
        await self.op_config(enable=True)
        while True:
            op = rng.choices(names, weights)[0]
            await getattr(self, f"op_{op}")()

    async def op_config(self, enable=False):
        rng = self.rng
        ctrl = rng.randrange(64)
        if enable or rng.random() < 0.85:
            ctrl |= regs.TX_EN | regs.RX_EN
        if rng.random() < 0.6:
            ctrl &= ~regs.LOOPBACK
        self.line.ctrl = ctrl
        await self.wr(regs.CTRL, ctrl | (rng.getrandbits(26) << 6 if rng.random() < 0.2 else 0), self.idle())

    async def op_toggle_enable(self):
        bit = self.rng.choice((regs.TX_EN, regs.RX_EN, regs.LOOPBACK, regs.STOP2))
        self.line.ctrl ^= bit
        await self.wr(regs.CTRL, self.line.ctrl, self.idle())

    async def op_baud(self):
        self.line.div = pick(self.rng, self.k.div_choices)
        await self.wr(regs.BAUD, self.line.div, self.idle())

    async def op_send(self):
        for _ in range(self.rng.randint(1, 7)):
            await self.wr(regs.TXDATA, rand_byte(self.rng, self.k), self.idle())

    async def op_drain(self):
        # Either poll STATUS and read while there is data (what software does), or read blind.
        if self.rng.random() < 0.6:
            for _ in range(6):
                if regs.rx_count(await self.status()) == 0:
                    break
                await self.rd(regs.RXDATA, self.idle())
        else:
            for _ in range(self.rng.randint(1, 5)):
                await self.rd(regs.RXDATA, self.idle())

    async def op_status(self):
        await self.rd(regs.STATUS, self.idle())

    async def op_irq_en(self):
        await self.wr(regs.IRQ_EN, self.rng.randrange(64), self.idle())

    async def op_irq_ack(self):
        stat = (await self.rd(regs.IRQ_STAT, self.idle())).rdata
        mask = stat if self.rng.random() < 0.6 else self.rng.randrange(64)
        # a few idle cycles sometimes, so the clear can land on the edge an event fires
        await self.wr(regs.IRQ_STAT, mask, self.idle())

    async def op_read_any(self):
        await self.rd(self.rng.choice(regs.MAPPED), self.idle())

    async def op_bad_access(self):
        rng = self.rng
        if rng.random() < 0.5:
            addr = rng.choice([a for a in range(256) if a not in regs.MAPPED])
            if rng.random() < 0.5:
                await self.wr(addr, rng.getrandbits(32), self.idle())
            else:
                await self.rd(addr, self.idle())
        else:
            await self.wr(rng.choice(regs.READ_ONLY), rng.getrandbits(32), self.idle())

    async def op_pause(self):
        await wait_cycles(pick(self.rng, (("1-10", 50), ("11-60", 35), ("61-400", 15))))

    async def op_reset(self):
        await self.reset_cb()
        self.line.ctrl, self.line.div = 0, 0
        await self.op_config(enable=True)


class RxRandomSeq(RxSeq):
    def __init__(self, name, rng, line, knobs):
        super().__init__(name)
        self.rng, self.line, self.k = rng, line, knobs

    async def body(self):
        rng, k = self.rng, self.k
        while True:
            gap = 0 if rng.random() < k.p_rx_back_to_back else rng.randint(1, k.rx_gap_max)
            period = self.line.div + 1
            if rng.random() < k.p_rx_glitch:
                await self.glitch(rng.randint(1, max(1, period)), gap=gap)
                continue
            if rng.random() < k.p_rx_wrong_speed:
                period = max(1, period + rng.choice((-1, 1, 2)))
            await self.frame(rand_byte(rng, k), period=period, parity=self.line.parity,
                             bad_parity=rng.random() < k.p_rx_bad_parity,
                             bad_stop=rng.random() < k.p_rx_bad_stop, gap=gap)
