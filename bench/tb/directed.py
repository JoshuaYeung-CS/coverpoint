"""Hand-written directed tests, one specified behaviour at a time.

These sequences do not check anything themselves. The lockstep scoreboard compares the
reference model against the device on every output in every cycle, so a directed test's
whole job is stimulus: drive the device into each behaviour docs/SPEC.md names, and a
wrong implementation differs at a port while it is happening.

Two consequences shape every sequence below.

* `txd`, `irq`, `pready` and `pslverr` are watched whether or not anyone looks at them,
  but internal state only reaches a port through a register read. So STATUS and IRQ_STAT
  are read after every interesting event, and often back to back *during* one so the busy
  flags are sampled inside their window, and every register written is read back.
* Where a rule is about two things happening at the same edge, aiming one access at that
  edge is a single point of failure: the sequencer hands an item to the driver with a
  cycle of slack. Those scenarios are repeated with the delay stepped across a window
  that brackets the computed edge (`sweep` below), so one iteration lands on it.

The timing the sweeps are computed from, all of it from docs/SPEC.md plus the APB driver:
an item posted at falling edge `x` completes at edge `x + idle + 1`, so two accesses can
never complete on adjacent edges; a TXDATA write completing at edge `n` starts a frame at
`n + 1`; a frame of `N` slots at period `P` starting at `s` ends, and the next one starts,
at `s + NP`; the rxd driver putting the start bit on the line in cycle `t` makes the
start-detect edge `c = t + 2`, and the stop sample lands at `c + h + 9P` (`+ P` again with
parity).

docs/TESTPLAN.md maps every rule in the specification to the test that reaches it.
"""
import cocotb
from cocotb.triggers import Event

from . import regs
from .env import BaseTest
from .seqlib import ApbSeq, RxSeq, frame_cycles, wait_cycles

ALL_ONES = 0xFFFFFFFF

# one bit at a time, including bits far above every field in the register map
WALK = [1 << k for k in range(9)] + [1 << 15, 1 << 16, 1 << 31]

# unmapped addresses: a near neighbour of every mapped one, and both ends of the space
UNMAPPED = (0x01, 0x02, 0x03, 0x05, 0x07, 0x0B, 0x0D, 0x11, 0x15, 0x19, 0x1C, 0x20, 0x7F, 0xFF)

SWEEP = 3                       # cycles either side of a computed alignment


def sweep(nominal, width=SWEEP):
    """Delays to try either side of a computed alignment. Never 0: a delay of 0 posts the
    item from the read-only phase of the previous access and can alias onto a delay of 1."""
    return list(range(max(1, nominal - width), nominal + width + 1))


class RxChannel:
    """A one-deep request/acknowledge channel from the APB sequence to the rxd sequence,
    so neither side ever has to guess where the other one is. `post` hands over an action
    and returns immediately (the APB sequence keeps driving while the frame is in flight);
    `wait_ack` blocks until the line goes quiet again."""

    def __init__(self):
        self._req, self._ack = Event(), Event()
        self._req_set = self._ack_set = False
        self.action = None

    def post(self, **action):
        self.action = action
        self._req_set = True
        self._req.set()

    async def wait_ack(self):
        if not self._ack_set:
            await self._ack.wait()
        self._ack.clear()
        self._ack_set = False

    async def send(self, **action):
        self.post(**action)
        await self.wait_ack()

    async def take(self):
        if not self._req_set:
            await self._req.wait()
        self._req.clear()
        self._req_set = False
        return self.action

    def ack(self):
        self._ack_set = True
        self._ack.set()


class RxScript(RxSeq):
    """The far end of the serial line. A `burst` is driven as one item chain so the frames
    in it are contiguous: with no gap the next start bit follows the previous stop bit in
    the very next cycle, which is the earliest edge section 6 allows a new frame."""

    def __init__(self, name, chan):
        super().__init__(name)
        self.chan = chan

    async def _one(self, f):
        if f.get("glitch"):
            await self.glitch(f["glitch"], gap=f.get("gap", 0))
        else:
            await self.frame(f.get("byte", 0), period=f.get("period", 1), parity=f.get("parity"),
                             bad_parity=f.get("bad_parity", False), bad_stop=f.get("bad_stop", False),
                             gap=f.get("gap", 0))

    async def body(self):
        while True:
            action = await self.chan.take()
            kind = action["kind"]
            if kind == "stop":
                self.chan.ack()
                return
            if kind == "burst":
                for f in action["frames"]:
                    await self._one(f)
            elif kind == "idle":
                await wait_cycles(action["cycles"])
            else:
                await self._one(action)
            self.chan.ack()


class DirSeq(ApbSeq):
    """Base for the directed APB sequences: the reset the test owns, and the channel to
    the rxd sequence when the test drives the line."""

    def __init__(self, name="dir", reset_cb=None, rx=None):
        super().__init__(name)
        self.reset_cb, self.rx = reset_cb, rx

    async def snapshot(self, idle=1):
        """Everything readable without side effects, in one pass."""
        for addr in (regs.CTRL, regs.BAUD, regs.STATUS, regs.IRQ_EN, regs.IRQ_STAT):
            await self.rd(addr, idle=idle)


def start_rx(test):
    """Wire the rxd sequence up alongside the APB one."""
    chan = RxChannel()
    cocotb.start_soon(RxScript("rx", chan).start(test.env.uart.seqr))
    return chan


# --------------------------------------------------------------------------------------
# Registers: reset values, masking of unused bits, APB spacing
# --------------------------------------------------------------------------------------

class RegsSeq(DirSeq):
    async def body(self):
        # Section 8 reset values, read back to back and spaced, so a decoder that needs an
        # idle cycle is caught on the same values.
        for idle in (0, 1, 3):
            await self.snapshot(idle=idle)
        await self.rd(regs.TXDATA)                   # write-only: reads 0, and is no error
        await self.rd(regs.RXDATA)                   # empty: returns 0 and pops nothing
        await self.rd(regs.STATUS, idle=0)

        # Section 1: bits that are not named ignore writes and read as 0.
        for reg in (regs.CTRL, regs.BAUD, regs.IRQ_EN):
            for pattern in (ALL_ONES, 0x55555555, 0xAAAAAAAA, 0):
                await self.wr(reg, pattern, idle=0)
                await self.rd(reg, idle=0)
        for reg in (regs.CTRL, regs.BAUD, regs.IRQ_EN):
            for pattern in WALK:
                await self.wr(reg, pattern, idle=0)
                await self.rd(reg, idle=0)
            await self.wr(reg, 0, idle=1)

        # A mid-test reset from a thoroughly non-zero state: two bytes looped round into
        # the RX FIFO, interrupts enabled and pending, a large divisor programmed.
        await self.wr(regs.BAUD, 1)
        await self.wr(regs.CTRL, regs.TX_EN | regs.RX_EN | regs.LOOPBACK)
        await self.wr(regs.TXDATA, 0x5A, idle=0)
        await self.wr(regs.TXDATA, 0xC3, idle=0)
        await wait_cycles(2 * frame_cycles(1) + 12)
        await self.rd(regs.STATUS, idle=0)
        await self.rd(regs.IRQ_STAT, idle=0)
        await self.wr(regs.IRQ_EN, ALL_ONES, idle=0)      # irq is high from here
        await self.wr(regs.BAUD, 0xFF, idle=0)
        await self.reset_cb()
        await self.snapshot(idle=0)
        await self.rd(regs.RXDATA, idle=0)               # the FIFO went with it
        await self.rd(regs.STATUS, idle=0)


class dir_reset_and_regs(BaseTest):
    async def main_seq(self):
        await RegsSeq("regs", self.reset).start(self.env.apb.seqr)


# --------------------------------------------------------------------------------------
# Error accesses, and that they change nothing
# --------------------------------------------------------------------------------------

class ErrorAccessSeq(DirSeq):
    async def body(self):
        # Build a state worth disturbing: two bytes round the loopback into the RX FIFO,
        # two parked in the TX FIFO behind a cleared tx_en, IRQ_STAT bits set, irq high.
        await self.wr(regs.BAUD, 0)
        await self.wr(regs.CTRL, regs.TX_EN | regs.RX_EN | regs.LOOPBACK)
        await self.wr(regs.TXDATA, 0x81, idle=0)
        await self.wr(regs.TXDATA, 0x7E, idle=0)
        await wait_cycles(2 * frame_cycles(0) + 12)
        await self.wr(regs.CTRL, 0)                       # nothing may move from here on
        await self.wr(regs.TXDATA, 0x24, idle=0)
        await self.wr(regs.TXDATA, 0x99, idle=0)
        await self.wr(regs.IRQ_EN, regs.IRQ_RX_AVAIL, idle=0)
        await self.snapshot(idle=0)

        # Every error access, read and written, carrying all-ones data.
        for addr in UNMAPPED:
            await self.rd(addr, idle=0)
            await self.wr(addr, ALL_ONES, idle=0)
        await self.wr(regs.STATUS, ALL_ONES, idle=0)      # read-only
        await self.wr(regs.RXDATA, ALL_ONES, idle=0)      # read-only, and must not pop
        await self.rd(regs.TXDATA, idle=0)                # not an error; reads 0
        await self.rd(regs.TXDATA, idle=2)
        for addr in UNMAPPED[:4]:
            await self.wr(addr, 0, idle=2)                # spaced as well as back to back

        # Nothing moved.
        await self.snapshot(idle=0)
        await self.rd(regs.RXDATA, idle=0)                # still the first byte received
        await self.rd(regs.RXDATA, idle=0)
        await self.rd(regs.STATUS, idle=0)


class dir_error_access(BaseTest):
    async def main_seq(self):
        await ErrorAccessSeq("errors", self.reset).start(self.env.apb.seqr)


# --------------------------------------------------------------------------------------
# Transmit frame format: parity and stop bits against the data patterns that pin them
# --------------------------------------------------------------------------------------

TX_FORMATS = (0,
              regs.PAR_EN,
              regs.PAR_EN | regs.PAR_ODD,
              regs.STOP2,
              regs.PAR_EN | regs.STOP2,
              regs.PAR_EN | regs.PAR_ODD | regs.STOP2)


class TxFormatSeq(DirSeq):
    async def body(self):
        div = 0
        await self.wr(regs.BAUD, div)
        for fmt in TX_FORMATS:
            par, stop2 = bool(fmt & regs.PAR_EN), bool(fmt & regs.STOP2)
            await self.wr(regs.CTRL, regs.TX_EN | fmt)
            for byte in (0x00, 0xFF, 0x55):
                await self.wr(regs.TXDATA, byte, idle=0)
                await self.rd(regs.STATUS, idle=0)        # tx_busy inside the frame
                await self.rd(regs.STATUS, idle=0)
                await wait_cycles(frame_cycles(div, par, stop2) + 4)
                await self.rd(regs.STATUS, idle=0)        # idle again, FIFO empty
                await self.rd(regs.IRQ_STAT, idle=0)      # tx_empty_ev
                await self.wr(regs.IRQ_STAT, ALL_ONES, idle=0)

        # Walking ones, four at a time, so the frames also run back to back out of a full
        # FIFO: every data bit on its own, and every frame boundary with no idle cycle.
        await self.wr(regs.CTRL, regs.TX_EN | regs.PAR_EN)
        for base in (0, 4):
            for k in range(base, base + 4):
                await self.wr(regs.TXDATA, 1 << k, idle=0)
            await self.rd(regs.STATUS, idle=0)
            await wait_cycles(4 * frame_cycles(div, True) + 6)
            await self.rd(regs.STATUS, idle=0)
            await self.rd(regs.IRQ_STAT, idle=0)
        await self.wr(regs.TXDATA, 0xAA, idle=0)
        await wait_cycles(frame_cycles(div, True) + 6)
        await self.rd(regs.STATUS, idle=0)


class dir_tx_formats(BaseTest):
    async def main_seq(self):
        await TxFormatSeq("tx_formats", self.reset).start(self.env.apb.seqr)


# --------------------------------------------------------------------------------------
# TX FIFO: fill, full, overflow, drain back to back, and the tx_en gate
# --------------------------------------------------------------------------------------

class TxFifoSeq(DirSeq):
    async def body(self):
        await self.wr(regs.BAUD, 0)
        await self.wr(regs.CTRL, 0)                       # tx_en low: the FIFO just fills
        for byte in (0x11, 0x22, 0x44, 0x88):
            await self.wr(regs.TXDATA, byte, idle=0)
            await self.rd(regs.STATUS, idle=0)            # tx_count 1..4, tx_full at 4
        await self.wr(regs.TXDATA, 0xEE, idle=0)          # discarded: tx_ovf
        await self.rd(regs.STATUS, idle=0)
        await self.rd(regs.IRQ_STAT, idle=0)
        await self.wr(regs.TXDATA, 0xDD, idle=0)          # still full, still discarded
        await self.rd(regs.STATUS, idle=0)
        await self.wr(regs.IRQ_STAT, regs.IRQ_TX_OVF, idle=0)
        await self.rd(regs.IRQ_STAT, idle=0)

        # Enabling the transmitter drains the FIFO back to back; the discarded bytes must
        # never appear on the line, and the four that were kept must appear in order.
        await self.wr(regs.CTRL, regs.TX_EN, idle=0)
        for _ in range(8):
            await self.rd(regs.STATUS, idle=0)            # busy, count falling
        await wait_cycles(4 * frame_cycles(0) + 6)
        await self.rd(regs.STATUS, idle=0)
        await self.rd(regs.IRQ_STAT, idle=0)              # tx_empty_ev
        await self.wr(regs.IRQ_STAT, ALL_ONES, idle=0)

        # tx_en cleared mid-frame: the frame in flight finishes, the queued byte waits.
        await self.wr(regs.BAUD, 2)
        await self.wr(regs.CTRL, regs.TX_EN)
        await self.wr(regs.TXDATA, 0x3C, idle=0)
        await self.wr(regs.TXDATA, 0xC3, idle=0)
        await wait_cycles(8)
        await self.wr(regs.CTRL, 0, idle=0)               # cleared while tx_busy
        await self.rd(regs.STATUS, idle=0)
        await wait_cycles(frame_cycles(2) + 8)
        await self.rd(regs.STATUS, idle=0)                # one byte queued, not busy
        await self.rd(regs.IRQ_STAT, idle=0)
        await self.wr(regs.CTRL, regs.TX_EN, idle=0)      # and away it goes
        await wait_cycles(frame_cycles(2) + 8)
        await self.rd(regs.STATUS, idle=0)
        await self.rd(regs.IRQ_STAT, idle=0)


class dir_tx_fifo_and_enable(BaseTest):
    async def main_seq(self):
        await TxFifoSeq("tx_fifo", self.reset).start(self.env.apb.seqr)


# --------------------------------------------------------------------------------------
# Section 7 on the transmit side: a push at the edge the transmitter pops
# --------------------------------------------------------------------------------------

class TxSameEdgeSeq(DirSeq):
    """Both scenarios aim a TXDATA write at the edge where the second frame starts back
    to back, which is the first pop edge far enough from an APB access to be reachable.
    Two APB transfers cannot complete on adjacent edges, so the first frame start (one
    edge after the write that filled the FIFO) is out of reach by construction."""

    async def body(self):
        # A push at the edge that would empty the FIFO: the count never reaches 0, so
        # tx_empty_ev must not be set. IRQ_STAT is read straight afterwards, because the
        # frame after next sets the bit anyway and a late read cannot tell the two apart.
        for d in sweep(9):
            await self.reset_cb()
            await self.wr(regs.IRQ_EN, regs.IRQ_TX_EMPTY)
            await self.wr(regs.TXDATA, 0x5A, idle=0)      # tx_en is 0 out of reset, so
            await self.wr(regs.TXDATA, 0xA5, idle=0)      # both bytes sit in the FIFO
            await self.wr(regs.CTRL, regs.TX_EN, idle=0)  # completes at m: frame 1 at m+1
            await wait_cycles(d)
            await self.wr(regs.TXDATA, 0x0F, idle=0)      # aimed at m + 11
            await self.rd(regs.IRQ_STAT, idle=0)
            await self.rd(regs.STATUS, idle=0)
            await wait_cycles(30 - d)                     # same length however it lands
            await self.rd(regs.IRQ_STAT, idle=0)
            await self.rd(regs.STATUS, idle=0)

        # A push at that edge with the FIFO already full: dropped, and tx_ovf set, even
        # though the transmitter pops at the same edge.
        for d in sweep(7):
            await self.reset_cb()
            await self.wr(regs.IRQ_EN, regs.IRQ_TX_OVF)
            for byte in (0x12, 0x34, 0x56, 0x78):
                await self.wr(regs.TXDATA, byte, idle=0)
            await self.wr(regs.CTRL, regs.TX_EN, idle=0)  # completes at m: pops at m+1
            await self.wr(regs.TXDATA, 0x9A, idle=0)      # back to full at m+2
            await wait_cycles(d)
            await self.wr(regs.TXDATA, 0xBC, idle=0)      # aimed at m + 11
            await self.rd(regs.IRQ_STAT, idle=0)
            await self.rd(regs.STATUS, idle=0)
            await wait_cycles(30 - d)
            await self.rd(regs.IRQ_STAT, idle=0)
            await self.rd(regs.STATUS, idle=0)


class dir_tx_same_edge(BaseTest):
    async def main_seq(self):
        await TxSameEdgeSeq("tx_same_edge", self.reset).start(self.env.apb.seqr)


# --------------------------------------------------------------------------------------
# Configuration written under a frame in flight, and at the exact edge one starts
# --------------------------------------------------------------------------------------

class MidFrameConfigSeq(DirSeq):
    async def body(self):
        # Transmit: the frame in flight keeps the parameters captured at its start edge,
        # and the next frame picks the new ones up.
        await self.wr(regs.BAUD, 3)
        await self.wr(regs.CTRL, regs.TX_EN)
        await self.wr(regs.TXDATA, 0x96, idle=0)
        await wait_cycles(10)
        await self.wr(regs.CTRL, regs.TX_EN | regs.PAR_EN | regs.PAR_ODD | regs.STOP2, idle=0)
        await self.wr(regs.BAUD, 0, idle=0)
        await self.rd(regs.STATUS, idle=0)                # still busy on the old frame
        await wait_cycles(frame_cycles(3) + 8)
        await self.rd(regs.STATUS, idle=0)
        await self.wr(regs.TXDATA, 0x96, idle=0)          # now odd parity, two stops, P=1
        await wait_cycles(frame_cycles(0, True, True) + 8)
        await self.rd(regs.STATUS, idle=0)

        # Receive: same rule at the other end. The line runs at period 4 throughout.
        await self.wr(regs.BAUD, 3)
        await self.wr(regs.CTRL, regs.RX_EN)
        await self.wr(regs.IRQ_STAT, ALL_ONES, idle=0)
        self.rx.post(kind="frame", byte=0x4B, period=4)
        await wait_cycles(14)
        await self.rd(regs.STATUS, idle=0)                # rx_busy
        await self.wr(regs.BAUD, 0, idle=0)
        await self.wr(regs.CTRL, regs.RX_EN | regs.PAR_EN, idle=0)
        await self.rx.wait_ack()
        await wait_cycles(8)
        await self.rd(regs.STATUS, idle=0)
        await self.rd(regs.RXDATA, idle=0)                # 0x4B, no parity error
        await self.rd(regs.IRQ_STAT, idle=0)

        # Section 7: a CTRL write landing on the edge a frame starts back to back. The
        # frame must capture the old format; the new one would add a parity bit and a
        # second stop bit, which is three extra slots on the line.
        for d in sweep(9):
            await self.reset_cb()
            await self.wr(regs.TXDATA, 0x5A, idle=0)
            await self.wr(regs.TXDATA, 0xA5, idle=0)
            await self.wr(regs.CTRL, regs.TX_EN, idle=0)  # completes at m: frame 1 at m+1
            await wait_cycles(d)
            await self.wr(regs.CTRL, regs.TX_EN | regs.PAR_EN | regs.STOP2, idle=0)
            await self.rd(regs.STATUS, idle=0)
            await wait_cycles(34 - d)
            await self.rd(regs.STATUS, idle=0)

        # The same rule at the receiver's start-detect edge, with BAUD. A captured div of
        # 5 against a line running at period 2 samples nonsense and frames badly.
        for d in sweep(2, 2):
            await self.reset_cb()
            await self.wr(regs.BAUD, 1)
            await self.wr(regs.CTRL, regs.RX_EN, idle=0)  # completes at a: start at a+3
            self.rx.post(kind="frame", byte=0x6C, period=2)
            await wait_cycles(d)
            await self.wr(regs.BAUD, 5, idle=0)
            await self.rd(regs.STATUS, idle=0)
            await wait_cycles(30 - d)
            await self.rx.wait_ack()
            await wait_cycles(6)
            await self.rd(regs.STATUS, idle=0)
            await self.rd(regs.RXDATA, idle=0)
            await self.rd(regs.RXDATA, idle=0)


class dir_midframe_config(BaseTest):
    async def main_seq(self):
        rx = start_rx(self)
        await MidFrameConfigSeq("midframe", self.reset, rx).start(self.env.apb.seqr)


# --------------------------------------------------------------------------------------
# Receive from the pin: divisors, parities, data patterns
# --------------------------------------------------------------------------------------

RX_CASES = ((0, None, 0x55), (1, "even", 0xAA), (2, "odd", 0x00),
            (3, None, 0xFF), (2, "even", 0x3C), (1, "odd", 0x81))


class RxBasicSeq(DirSeq):
    async def body(self):
        for div, parity, byte in RX_CASES:
            ctrl = regs.RX_EN
            if parity:
                ctrl |= regs.PAR_EN | (regs.PAR_ODD if parity == "odd" else 0)
            await self.wr(regs.BAUD, div)
            await self.wr(regs.CTRL, ctrl, idle=0)
            await self.wr(regs.IRQ_STAT, ALL_ONES, idle=0)
            self.rx.post(kind="frame", byte=byte, period=div + 1, parity=parity)
            for _ in range(3):
                await self.rd(regs.STATUS, idle=0)        # rx_busy inside the frame
            await self.rx.wait_ack()
            await wait_cycles(6)
            await self.rd(regs.STATUS, idle=0)            # one entry, not busy
            await self.rd(regs.IRQ_STAT, idle=0)          # rx_avail_ev
            await self.rd(regs.RXDATA, idle=0)            # the byte, perr and ferr clear
            await self.rd(regs.STATUS, idle=0)            # empty again


class dir_rx_basic(BaseTest):
    async def main_seq(self):
        rx = start_rx(self)
        await RxBasicSeq("rx_basic", self.reset, rx).start(self.env.apb.seqr)


# --------------------------------------------------------------------------------------
# Receive errors, and the rx_en gate
# --------------------------------------------------------------------------------------

# (CTRL, what the line sends, wrong parity bit, stop bit held low). Every combination of
# the two error flags is sent under each parity setting: with parity enabled the stop bit
# is sampled a whole bit period later than without it, so a framing error under even and
# odd parity is a different sample point from the one the no-parity case exercises.
RX_ERROR_CASES = (
    (regs.RX_EN | regs.PAR_EN, "even", True, False),
    (regs.RX_EN | regs.PAR_EN | regs.PAR_ODD, "odd", True, False),
    (regs.RX_EN, None, False, True),
    (regs.RX_EN | regs.PAR_EN, "even", False, True),
    (regs.RX_EN | regs.PAR_EN | regs.PAR_ODD, "odd", False, True),
    (regs.RX_EN | regs.PAR_EN, "even", True, True),
    (regs.RX_EN | regs.PAR_EN | regs.PAR_ODD, "odd", True, True),
)


class RxErrorSeq(DirSeq):
    async def body(self):
        # rx_en low: a whole frame goes past and the receiver never moves.
        await self.wr(regs.BAUD, 1)
        await self.wr(regs.CTRL, 0)
        self.rx.post(kind="frame", byte=0x5A, period=2)
        for _ in range(6):
            await self.rd(regs.STATUS, idle=0)            # never busy, count stays 0
        await self.rx.wait_ack()
        await wait_cycles(4)
        await self.rd(regs.STATUS, idle=0)
        await self.rd(regs.IRQ_STAT, idle=0)
        await self.rd(regs.RXDATA, idle=0)                # nothing to pop

        # The same frame with rx_en set.
        await self.wr(regs.CTRL, regs.RX_EN, idle=0)
        await self.rx.send(kind="frame", byte=0x5A, period=2)
        await wait_cycles(6)
        await self.rd(regs.STATUS, idle=0)
        await self.rd(regs.RXDATA, idle=0)

        # Parity error (even and odd), framing error, and both at once. A framing error
        # leaves the line low, so the receiver may legitimately start again at e+1; the
        # drain afterwards takes whatever that produced.
        for ctrl, parity, bad_p, bad_s in RX_ERROR_CASES:
            await self.wr(regs.CTRL, ctrl)
            await self.wr(regs.IRQ_STAT, ALL_ONES, idle=0)
            await self.rx.send(kind="frame", byte=0x6B, period=2, parity=parity,
                               bad_parity=bad_p, bad_stop=bad_s)
            await wait_cycles(8)
            await self.rd(regs.STATUS, idle=0)
            await self.rd(regs.RXDATA, idle=0)            # perr in bit 8, ferr in bit 9
            await self.rd(regs.IRQ_STAT, idle=0)
            await wait_cycles(frame_cycles(1, parity is not None) + 12)
            for _ in range(3):
                await self.rd(regs.RXDATA, idle=0)
            await self.rd(regs.STATUS, idle=0)

        # rx_en cleared mid-frame does not abort the frame.
        await self.wr(regs.BAUD, 3)
        await self.wr(regs.CTRL, regs.RX_EN)
        await self.wr(regs.IRQ_STAT, ALL_ONES, idle=0)
        self.rx.post(kind="frame", byte=0x9C, period=4)
        await wait_cycles(16)
        await self.wr(regs.CTRL, 0, idle=0)               # cleared while rx_busy
        await self.rd(regs.STATUS, idle=0)
        await self.rx.wait_ack()
        await wait_cycles(8)
        await self.rd(regs.STATUS, idle=0)
        await self.rd(regs.RXDATA, idle=0)                # the frame still completed
        await self.rd(regs.IRQ_STAT, idle=0)


class dir_rx_errors_and_enable(BaseTest):
    async def main_seq(self):
        rx = start_rx(self)
        await RxErrorSeq("rx_errors", self.reset, rx).start(self.env.apb.seqr)


# --------------------------------------------------------------------------------------
# False starts: the start check at c + h, from both sides of it
# --------------------------------------------------------------------------------------

# (div, glitches that must be false starts, the glitch that must be accepted as a start)
FALSE_START_CASES = ((5, (1, 2), 3), (7, (2, 3), 4), (15, (7,), 8))


class FalseStartSeq(DirSeq):
    async def body(self):
        await self.wr(regs.CTRL, regs.RX_EN)
        for div, short, atcheck in FALSE_START_CASES:
            await self.wr(regs.BAUD, div)
            await self.wr(regs.IRQ_STAT, ALL_ONES, idle=0)
            for cycles in short:
                self.rx.post(kind="glitch", cycles=cycles)
                for _ in range(4):
                    await self.rd(regs.STATUS, idle=0)    # rx_busy only while checking
                await self.rx.wait_ack()
                await wait_cycles(div + 4)
                await self.rd(regs.STATUS, idle=0)        # idle again, nothing received
                await self.rd(regs.IRQ_STAT, idle=0)
            # one cycle longer: the check passes and a frame of ones is received
            await self.rx.send(kind="glitch", cycles=atcheck)
            await wait_cycles(frame_cycles(div) + 8)
            await self.rd(regs.STATUS, idle=0)
            await self.rd(regs.RXDATA, idle=0)            # 0xFF, no framing error
            await self.rd(regs.IRQ_STAT, idle=0)
            await self.wr(regs.IRQ_STAT, ALL_ONES, idle=0)

        # A glitch of exactly h followed with no gap: the real start bit lands on c+h+1,
        # the first edge the receiver is allowed to look at again.
        await self.wr(regs.BAUD, 5)
        await self.rx.send(kind="burst", frames=[{"glitch": 2}, {"byte": 0x5A, "period": 6}])
        await wait_cycles(frame_cycles(5) + 12)
        await self.rd(regs.STATUS, idle=0)
        await self.rd(regs.RXDATA, idle=0)
        await self.rd(regs.RXDATA, idle=0)

        # With h = 0 the check is edge c itself and always passes, so even a one-cycle
        # glitch is a frame.
        await self.wr(regs.BAUD, 0)
        await self.rx.send(kind="glitch", cycles=1)
        await wait_cycles(frame_cycles(0) + 8)
        await self.rd(regs.STATUS, idle=0)
        await self.rd(regs.RXDATA, idle=0)
        await self.rd(regs.IRQ_STAT, idle=0)


class dir_rx_false_start(BaseTest):
    async def main_seq(self):
        rx = start_rx(self)
        await FalseStartSeq("false_start", self.reset, rx).start(self.env.apb.seqr)


# --------------------------------------------------------------------------------------
# RX FIFO: fill, overrun, order, and reading past empty
# --------------------------------------------------------------------------------------

class RxFifoSeq(DirSeq):
    async def body(self):
        await self.wr(regs.BAUD, 0)
        await self.wr(regs.CTRL, regs.RX_EN)
        await self.wr(regs.IRQ_EN, regs.IRQ_RX_AVAIL | regs.IRQ_RX_OVR, idle=0)
        for byte in (0xC1, 0xC2, 0xC4, 0xC8):
            await self.rx.send(kind="frame", byte=byte)
            await wait_cycles(4)
            await self.rd(regs.STATUS, idle=0)            # rx_count climbs, rx_full at 4
            await self.rd(regs.IRQ_STAT, idle=0)
        await self.rx.send(kind="frame", byte=0xFE)       # lost: rx_ovr
        await wait_cycles(4)
        await self.rd(regs.STATUS, idle=0)
        await self.rd(regs.IRQ_STAT, idle=0)
        for _ in range(regs.FIFO_DEPTH):
            await self.rd(regs.RXDATA, idle=0)            # the first four, in order
            await self.rd(regs.STATUS, idle=0)
        await self.rd(regs.RXDATA, idle=0)                # empty: 0, and nothing pops
        await self.rd(regs.RXDATA, idle=2)
        await self.rd(regs.STATUS, idle=0)

        # Frames with no gap between them: the next start bit is the first edge after the
        # stop sample, which is the earliest section 6 allows.
        await self.wr(regs.IRQ_STAT, ALL_ONES, idle=0)
        await self.rx.send(kind="burst", frames=[{"byte": b} for b in (0x13, 0x26, 0x4C)])
        await wait_cycles(6)
        await self.rd(regs.STATUS, idle=0)
        for _ in range(4):
            await self.rd(regs.RXDATA, idle=0)
        await self.rd(regs.STATUS, idle=0)
        await self.rd(regs.IRQ_STAT, idle=0)


class dir_rx_fifo(BaseTest):
    async def main_seq(self):
        rx = start_rx(self)
        await RxFifoSeq("rx_fifo", self.reset, rx).start(self.env.apb.seqr)


# --------------------------------------------------------------------------------------
# Section 7 on the receive side: a read at the edge the receiver pushes
# --------------------------------------------------------------------------------------

class RxSameEdgeSeq(DirSeq):
    """One scenario, three FIFO levels. The RXDATA read is stepped across the stop-sample
    edge of a frame that arrives with the FIFO empty (the read must do nothing and the
    entry must survive), holding two entries (both happen, the count is unchanged) and
    full (the frame is lost to an overrun even though a pop happens at that edge). Every
    iteration drains one read past empty, and the drained *order* is what a mishandled
    simultaneous push and pop disturbs."""

    async def body(self):
        for preload in (0, 2, 4):
            for d in sweep(10):
                await self.reset_cb()
                await self.wr(regs.IRQ_EN, regs.IRQ_RX_AVAIL | regs.IRQ_RX_OVR)
                await self.wr(regs.CTRL, regs.RX_EN, idle=0)
                if preload:
                    await self.rx.send(kind="burst",
                                       frames=[{"byte": 0xB0 + i} for i in range(preload)])
                    await wait_cycles(6)
                await self.rd(regs.STATUS, idle=0)        # completes at a
                self.rx.post(kind="frame", byte=0xC5)     # start bit at a+1, stop at a+12
                await wait_cycles(d)
                await self.rd(regs.RXDATA, idle=0)        # aimed at a + 12
                await self.rd(regs.STATUS, idle=0)
                await wait_cycles(24 - d)
                await self.rx.wait_ack()
                await self.rd(regs.IRQ_STAT, idle=0)
                for _ in range(preload + 2):
                    await self.rd(regs.RXDATA, idle=0)
                await self.rd(regs.STATUS, idle=0)


class dir_rx_same_edge(BaseTest):
    async def main_seq(self):
        rx = start_rx(self)
        await RxSameEdgeSeq("rx_same_edge", self.reset, rx).start(self.env.apb.seqr)


# --------------------------------------------------------------------------------------
# Loopback
# --------------------------------------------------------------------------------------

class LoopbackSeq(DirSeq):
    async def body(self):
        await self.wr(regs.BAUD, 0)
        for extra, parity in ((0, None), (regs.PAR_EN, "even"),
                              (regs.PAR_EN | regs.PAR_ODD, "odd")):
            await self.wr(regs.CTRL, regs.TX_EN | regs.RX_EN | regs.LOOPBACK | extra)
            await self.wr(regs.IRQ_STAT, ALL_ONES, idle=0)
            # a different byte on the pin at the same time: it must be ignored entirely
            self.rx.post(kind="frame", byte=0x3C)
            await self.wr(regs.TXDATA, 0xA5, idle=0)
            await self.rd(regs.STATUS, idle=0)            # tx_busy, then rx_busy as well
            await self.rd(regs.STATUS, idle=0)
            await self.rd(regs.STATUS, idle=0)
            await wait_cycles(frame_cycles(0, parity is not None) + 10)
            await self.rx.wait_ack()
            await self.rd(regs.STATUS, idle=0)            # exactly one entry
            await self.rd(regs.RXDATA, idle=0)            # 0xA5, not 0x3C
            await self.rd(regs.RXDATA, idle=0)            # and nothing behind it
            await self.rd(regs.IRQ_STAT, idle=0)

        # With loopback cleared the pin is live again.
        await self.wr(regs.CTRL, regs.RX_EN)
        await self.rx.send(kind="frame", byte=0x3C)
        await wait_cycles(6)
        await self.rd(regs.STATUS, idle=0)
        await self.rd(regs.RXDATA, idle=0)
        await self.rd(regs.IRQ_STAT, idle=0)


class dir_loopback(BaseTest):
    async def main_seq(self):
        rx = start_rx(self)
        await LoopbackSeq("loopback", self.reset, rx).start(self.env.apb.seqr)


# --------------------------------------------------------------------------------------
# Interrupts: masking, every source, write-1-to-clear, and set winning over clear
# --------------------------------------------------------------------------------------

class IrqSeq(DirSeq):
    async def body(self):
        # Every source set while IRQ_EN is 0. irq is compared every cycle, so this stretch
        # is the masking check; IRQ_STAT must still hold all six bits at the end of it.
        await self.wr(regs.IRQ_EN, 0)
        await self.wr(regs.BAUD, 0)
        await self.wr(regs.CTRL, 0)
        for byte in (0x01, 0x02, 0x03, 0x04, 0x05):       # the fifth is dropped: tx_ovf
            await self.wr(regs.TXDATA, byte, idle=0)
        await self.wr(regs.CTRL, regs.TX_EN, idle=0)      # four frames, then tx_empty_ev
        await wait_cycles(4 * frame_cycles(0) + 8)
        await self.rd(regs.IRQ_STAT, idle=0)
        await self.wr(regs.CTRL, regs.RX_EN, idle=0)
        # four received, the fifth lost: rx_avail_ev and rx_ovr
        await self.rx.send(kind="burst", frames=[{"byte": 0x20 + i} for i in range(5)])
        await wait_cycles(8)
        await self.rd(regs.IRQ_STAT, idle=0)
        await self.rd(regs.STATUS, idle=0)
        # and a bad frame into a full FIFO: discarded, but perr_ev and ferr_ev still set
        await self.wr(regs.CTRL, regs.RX_EN | regs.PAR_EN, idle=0)
        await self.rx.send(kind="frame", byte=0x77, parity="even", bad_parity=True, bad_stop=True)
        await wait_cycles(12)
        await self.rd(regs.IRQ_STAT, idle=0)              # all six bits, irq still low
        await self.rd(regs.STATUS, idle=0)
        await self.wr(regs.CTRL, 0, idle=0)               # stop listening to the line

        # Each source in turn: enabling it alone raises irq, writing its bit clears it.
        for bit in range(len(regs.IRQ_NAMES)):
            await self.wr(regs.IRQ_EN, 1 << bit, idle=0)
            await self.rd(regs.IRQ_STAT, idle=0)
            await self.wr(regs.IRQ_STAT, 1 << bit, idle=0)
            await self.rd(regs.IRQ_STAT, idle=0)
        await self.wr(regs.IRQ_EN, 0, idle=0)

        # Write-1-to-clear of a subset leaves the rest alone.
        await self.wr(regs.CTRL, 0, idle=0)
        for byte in (0x31, 0x32, 0x33, 0x34, 0x35):
            await self.wr(regs.TXDATA, byte, idle=0)      # tx_ovf
        await self.wr(regs.CTRL, regs.RX_EN, idle=0)
        await self.rx.send(kind="frame", byte=0x88, bad_stop=True)   # rx_avail_ev, ferr_ev
        await wait_cycles(frame_cycles(0) + 12)
        await self.wr(regs.CTRL, 0, idle=0)
        await self.rd(regs.IRQ_STAT, idle=0)
        await self.wr(regs.IRQ_STAT, regs.IRQ_FERR, idle=0)
        await self.rd(regs.IRQ_STAT, idle=0)              # tx_ovf and rx_avail_ev remain
        await self.wr(regs.IRQ_STAT, regs.IRQ_TX_OVF | regs.IRQ_RX_AVAIL, idle=0)
        await self.rd(regs.IRQ_STAT, idle=0)

        # Set wins over clear: a write clearing tx_empty_ev stepped across the edge that
        # sets it. With the bit enabled, irq in the following cycle says which won.
        for d in sweep(9):
            await self.reset_cb()
            await self.wr(regs.IRQ_EN, regs.IRQ_TX_EMPTY)
            await self.wr(regs.TXDATA, 0x5A, idle=0)
            await self.wr(regs.TXDATA, 0xA5, idle=0)
            await self.wr(regs.CTRL, regs.TX_EN, idle=0)  # completes at m: frame 2 at m+11
            await wait_cycles(d)
            await self.wr(regs.IRQ_STAT, regs.IRQ_TX_EMPTY, idle=0)   # aimed at m + 11
            await self.rd(regs.IRQ_STAT, idle=0)
            await self.rd(regs.STATUS, idle=0)
            await wait_cycles(26 - d)
            await self.rd(regs.IRQ_STAT, idle=0)


class dir_irq(BaseTest):
    async def main_seq(self):
        rx = start_rx(self)
        await IrqSeq("irq", self.reset, rx).start(self.env.apb.seqr)


# --------------------------------------------------------------------------------------
# Reset in the middle of a frame, in both directions
# --------------------------------------------------------------------------------------

class ResetMidFrameSeq(DirSeq):
    async def body(self):
        # Mid transmit frame: txd back to 1 in the next cycle, FIFO gone with it.
        await self.wr(regs.BAUD, 3)
        await self.wr(regs.CTRL, regs.TX_EN)
        await self.wr(regs.IRQ_EN, ALL_ONES, idle=0)
        await self.wr(regs.TXDATA, 0x6C, idle=0)
        await self.wr(regs.TXDATA, 0x93, idle=0)
        await wait_cycles(16)
        await self.rd(regs.STATUS, idle=0)                # tx_busy, one byte still queued
        await self.reset_cb()
        await self.rd(regs.STATUS, idle=0)                # 0x5
        await self.rd(regs.IRQ_STAT, idle=0)
        await self.rd(regs.CTRL, idle=0)
        # and the transmitter still works afterwards
        await self.wr(regs.CTRL, regs.TX_EN, idle=0)
        await self.wr(regs.TXDATA, 0x3A, idle=0)
        await wait_cycles(frame_cycles(0) + 8)
        await self.rd(regs.STATUS, idle=0)
        await self.rd(regs.IRQ_STAT, idle=0)

        # Mid receive frame: the synchroniser resets high, so the rest of the frame on the
        # line must not be mistaken for anything now that rx_en is 0 again.
        await self.wr(regs.BAUD, 3)
        await self.wr(regs.CTRL, regs.RX_EN)
        self.rx.post(kind="frame", byte=0xB4, period=4)
        await wait_cycles(20)
        await self.rd(regs.STATUS, idle=0)                # rx_busy
        await self.reset_cb()
        await self.rd(regs.STATUS, idle=0)                # 0x5
        await self.rd(regs.IRQ_STAT, idle=0)
        await self.rx.wait_ack()
        await wait_cycles(8)
        await self.rd(regs.STATUS, idle=0)
        await self.rd(regs.RXDATA, idle=0)
        # and the receiver still works afterwards
        await self.wr(regs.BAUD, 0, idle=0)
        await self.wr(regs.CTRL, regs.RX_EN, idle=0)
        await self.rx.send(kind="frame", byte=0x2D)
        await wait_cycles(8)
        await self.rd(regs.STATUS, idle=0)
        await self.rd(regs.RXDATA, idle=0)
        await self.rd(regs.IRQ_STAT, idle=0)


class dir_reset_midframe(BaseTest):
    async def main_seq(self):
        rx = start_rx(self)
        await ResetMidFrameSeq("reset_midframe", self.reset, rx).start(self.env.apb.seqr)


# --------------------------------------------------------------------------------------
# Realistic and large divisors: the upper bits of div are real logic
# --------------------------------------------------------------------------------------

class BaudSeq(DirSeq):
    """One transmitted and one received frame at a single divisor, with STATUS sampled
    inside both frames. div = 15 is a plausible rate; div = 137 is odd and sets bit 7, so
    P = 138 and h = 68 exercise the top of the counter and the halving together."""

    def __init__(self, name, reset_cb, rx, div, parity):
        super().__init__(name, reset_cb, rx)
        self.div, self.parity = div, parity

    async def body(self):
        div, parity = self.div, self.parity
        ctrl = regs.TX_EN | regs.RX_EN | (regs.PAR_EN if parity else 0)
        await self.wr(regs.BAUD, div)
        await self.wr(regs.CTRL, ctrl, idle=0)
        await self.wr(regs.IRQ_EN, ALL_ONES, idle=0)
        await self.wr(regs.TXDATA, 0xA5, idle=0)
        for _ in range(4):
            await self.rd(regs.STATUS, idle=div)          # tx_busy across the frame
        await wait_cycles(frame_cycles(div, parity is not None) + 8)
        await self.rd(regs.STATUS, idle=0)
        await self.rd(regs.IRQ_STAT, idle=0)
        await self.wr(regs.IRQ_STAT, ALL_ONES, idle=0)

        self.rx.post(kind="frame", byte=0x5A, period=div + 1, parity=parity)
        for _ in range(4):
            await self.rd(regs.STATUS, idle=div)          # rx_busy across the frame
        await self.rx.wait_ack()
        await wait_cycles(8)
        await self.rd(regs.STATUS, idle=0)
        await self.rd(regs.RXDATA, idle=0)
        await self.rd(regs.IRQ_STAT, idle=0)
        await self.rd(regs.STATUS, idle=0)


class dir_baud_realistic(BaseTest):
    async def main_seq(self):
        rx = start_rx(self)
        await BaudSeq("baud15", self.reset, rx, 15, "even").start(self.env.apb.seqr)


class dir_baud_large(BaseTest):
    async def main_seq(self):
        rx = start_rx(self)
        await BaudSeq("baud137", self.reset, rx, 137, None).start(self.env.apb.seqr)


DIRECTED = [
    "dir_reset_and_regs",
    "dir_error_access",
    "dir_tx_formats",
    "dir_tx_fifo_and_enable",
    "dir_tx_same_edge",
    "dir_midframe_config",
    "dir_rx_basic",
    "dir_rx_errors_and_enable",
    "dir_rx_false_start",
    "dir_rx_fifo",
    "dir_rx_same_edge",
    "dir_loopback",
    "dir_irq",
    "dir_reset_midframe",
    "dir_baud_realistic",
    "dir_baud_large",
]
