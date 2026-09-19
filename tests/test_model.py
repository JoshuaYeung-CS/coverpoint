"""Cycle-exact tests for the ``cp_uart`` reference model.

Every expectation here is hand-computed from ``docs/SPEC.md``, not from the
model. The ``Sim`` harness below keeps a per-cycle log so that assertions name
exact cycles rather than eventual outcomes.

Cycle / edge indexing used throughout:

* Cycle ``t`` is the clock period that ends at edge ``t``.
* ``log[t]`` is the sample taken during cycle ``t``: the combinational outputs
  for the inputs driven in that cycle, plus ``txd`` / ``irq`` / STATUS fields,
  all of which reflect the state left by edge ``t - 1``.
* ``events[t]`` is ``model.last_events`` after edge ``t``.
* The SPEC phrase "the cycle after edge ``e``" is therefore ``log[e + 1]``.

Run from the repo root:
    .venv/bin/python -m pytest tests/test_model.py -q
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bench.model import (  # noqa: E402
    ADDR_BAUD,
    ADDR_CTRL,
    ADDR_IRQ_EN,
    ADDR_IRQ_STAT,
    ADDR_RXDATA,
    ADDR_STATUS,
    ADDR_TXDATA,
    EV_APB_ERROR,
    EV_APB_READ,
    EV_APB_WRITE,
    EV_IRQ_CLEAR_LOST_TO_SET,
    EV_RX_FALSE_START,
    EV_RX_FERR,
    EV_RX_OVERRUN,
    EV_RX_PERR,
    EV_RX_POP,
    EV_RX_POP_EMPTY,
    EV_RX_PUSH,
    EV_RX_START,
    EV_TX_FRAME_BACK_TO_BACK,
    EV_TX_FRAME_START,
    EV_TX_POP,
    EV_TX_PUSH,
    EV_TX_PUSH_DROPPED,
    IRQ_FERR_EV,
    IRQ_PERR_EV,
    IRQ_RX_AVAIL_EV,
    IRQ_RX_OVR,
    IRQ_TX_EMPTY_EV,
    IRQ_TX_OVF,
    UartModel,
)

# CTRL bit values, spelled out so the tests never import model helpers for them.
TX_EN = 1 << 0
RX_EN = 1 << 1
PAR_EN = 1 << 2
PAR_ODD = 1 << 3
LOOPBACK = 1 << 4
STOP2 = 1 << 5


def xor8(byte):
    """XOR of the eight bits of ``byte`` — recomputed here, independent of the model."""
    acc = 0
    for index in range(8):
        acc ^= (byte >> index) & 1
    return acc


def expected_tx_waveform(byte, div, par_en, par_odd, stop2):
    """Expected ``txd`` values for the cycles after edges ``s`` … ``s + NP - 1``.

    Built straight from the SPEC 5 frame-layout table: start, eight data bits LSB
    first, optional parity, one or two stop bits, each held for ``P`` cycles.
    """
    period = div + 1
    slots = [0]
    slots += [(byte >> k) & 1 for k in range(8)]
    if par_en:
        slots.append(xor8(byte) ^ (1 if par_odd else 0))
    slots.append(1)
    if stop2:
        slots.append(1)
    return [value for value in slots for _ in range(period)]


class Sample:
    """One cycle's worth of observable outputs."""

    __slots__ = (
        "cycle",
        "txd",
        "irq",
        "prdata",
        "pready",
        "pslverr",
        "tx_count",
        "rx_count",
        "tx_busy",
        "rx_busy",
        "ctrl",
        "baud",
        "irq_en",
        "irq_stat",
    )

    def __init__(self, **kwargs):
        for name, value in kwargs.items():
            setattr(self, name, value)

    def __repr__(self):
        return (
            "Sample(cycle={0.cycle}, txd={0.txd}, irq={0.irq}, prdata={0.prdata:#x}, "
            "pslverr={0.pslverr}, tx_count={0.tx_count}, rx_count={0.rx_count}, "
            "tx_busy={0.tx_busy}, rx_busy={0.rx_busy})".format(self)
        )


class Sim:
    """Drives :class:`UartModel` one cycle at a time and records every cycle."""

    def __init__(self):
        self.model = UartModel()
        self.t = 0
        self.log = []
        self.events = []
        self.rx_queue = []
        self.rxd_idle = 1

    # -- low level ------------------------------------------------------

    def tick(self, presetn=1, psel=0, penable=0, pwrite=0, paddr=0, pwdata=0, rxd=None):
        """Sample the current cycle, then apply one edge. Returns the sample."""
        if rxd is None:
            rxd = self.rx_queue.pop(0) if self.rx_queue else self.rxd_idle
        prdata, pready, pslverr = self.model.comb(psel, penable, pwrite, paddr, pwdata)
        sample = Sample(
            cycle=self.t,
            txd=self.model.txd,
            irq=self.model.irq,
            prdata=prdata,
            pready=pready,
            pslverr=pslverr,
            tx_count=self.model.tx_count,
            rx_count=self.model.rx_count,
            tx_busy=self.model.tx_busy,
            rx_busy=self.model.rx_busy,
            ctrl=self.model.ctrl,
            baud=self.model.baud,
            irq_en=self.model.irq_en,
            irq_stat=self.model.irq_stat,
        )
        self.log.append(sample)
        self.model.step(presetn, psel, penable, pwrite, paddr, pwdata, rxd)
        self.events.append(set(self.model.last_events))
        self.t += 1
        return sample

    def idle(self, cycles=1):
        """Tick ``cycles`` times with no APB activity."""
        for _ in range(cycles):
            self.tick()

    def run_until(self, cycle):
        """Tick (idle) until the next cycle to be driven is ``cycle``."""
        assert cycle >= self.t, "cannot rewind: already at cycle %d" % self.t
        while self.t < cycle:
            self.tick()

    # -- APB helpers ----------------------------------------------------

    def apb_write(self, addr, data):
        """Two-cycle APB write. Returns the index of the access edge."""
        self.tick(psel=1, penable=0, pwrite=1, paddr=addr, pwdata=data)
        access = self.t
        self.tick(psel=1, penable=1, pwrite=1, paddr=addr, pwdata=data)
        return access

    def apb_read(self, addr):
        """Two-cycle APB read. Returns ``(access_edge, prdata, pslverr)``."""
        self.tick(psel=1, penable=0, pwrite=0, paddr=addr)
        access = self.t
        sample = self.tick(psel=1, penable=1, pwrite=0, paddr=addr)
        return access, sample.prdata, sample.pslverr

    # -- serial stimulus ------------------------------------------------

    def queue_rx_bits(self, bits):
        """Queue raw ``rxd`` levels, one per cycle."""
        self.rx_queue.extend(bits)

    def queue_rx_frame(
        self, byte, div, par_en=0, par_odd=0, parity_override=None, stop_value=1
    ):
        """Queue one serial frame on ``rxd``: start, data LSB first, parity, stop."""
        period = div + 1
        bits = [0]
        bits += [(byte >> k) & 1 for k in range(8)]
        if par_en:
            parity = xor8(byte) ^ (1 if par_odd else 0)
            if parity_override is not None:
                parity = parity_override
            bits.append(parity)
        bits.append(stop_value)
        self.queue_rx_bits([value for value in bits for _ in range(period)])


# ----------------------------------------------------------------------
# Reset and register access
# ----------------------------------------------------------------------


def test_reset_values():
    """SPEC 8 / 4.3: a fresh model reads STATUS = 0x5 and idles txd high."""
    model = UartModel()
    assert model.txd == 1
    assert model.irq == 0
    assert model.tx_count == 0
    assert model.rx_count == 0
    assert model.tx_busy == 0
    assert model.rx_busy == 0
    assert model.ctrl == 0
    assert model.baud == 0
    assert model.irq_en == 0
    assert model.irq_stat == 0
    assert model.comb(1, 0, 0, ADDR_STATUS, 0) == (0x00000005, 1, 0)

    sim = Sim()
    _, value, err = sim.apb_read(ADDR_STATUS)
    assert value == 0x00000005
    assert err == 0


def test_pready_is_always_one():
    """SPEC 2: pready is constant 1, selected or not."""
    model = UartModel()
    for psel in (0, 1):
        for penable in (0, 1):
            for addr in (ADDR_CTRL, 0x01, ADDR_STATUS):
                assert model.comb(psel, penable, 1, addr, 0)[1] == 1


def test_ctrl_baud_irq_en_readback_masks_unused_bits():
    """SPEC 1 / 4: bits not named read as 0 and ignore writes."""
    sim = Sim()
    sim.apb_write(ADDR_CTRL, 0xFFFFFFFF)
    _, ctrl, _ = sim.apb_read(ADDR_CTRL)
    assert ctrl == 0x3F

    sim.apb_write(ADDR_BAUD, 0xFFFFFFFF)
    _, baud, _ = sim.apb_read(ADDR_BAUD)
    assert baud == 0xFF

    sim.apb_write(ADDR_IRQ_EN, 0xFFFFFFFF)
    _, irq_en, _ = sim.apb_read(ADDR_IRQ_EN)
    assert irq_en == 0x3F

    # And a mid-range value comes back exactly.
    sim.apb_write(ADDR_CTRL, 0x2A)
    _, ctrl, _ = sim.apb_read(ADDR_CTRL)
    assert ctrl == 0x2A
    sim.apb_write(ADDR_BAUD, 0x07)
    _, baud, _ = sim.apb_read(ADDR_BAUD)
    assert baud == 0x07


def test_register_writes_take_effect_at_the_access_edge_only():
    """SPEC 3: side effects happen at the access edge and only there."""
    sim = Sim()
    sim.run_until(5)
    access = sim.apb_write(ADDR_BAUD, 0x12)
    assert access == 6
    sim.idle(3)
    assert sim.log[access].baud == 0x00  # setup phase had no effect
    assert sim.log[access + 1].baud == 0x12
    assert EV_APB_WRITE in sim.events[access]
    assert sim.events[access - 1] == set()  # the setup edge does nothing


def test_txdata_reads_zero_and_is_not_an_error():
    """SPEC 3 / 4.4: TXDATA is write-only, reads 0, and a read is not an error."""
    sim = Sim()
    sim.apb_write(ADDR_TXDATA, 0xAB)
    access, value, err = sim.apb_read(ADDR_TXDATA)
    assert value == 0
    assert err == 0
    assert EV_APB_READ in sim.events[access]


def test_prdata_zero_when_not_selected_or_writing():
    """SPEC 3: prdata is 0 when psel = 0 or pwrite = 1."""
    sim = Sim()
    sim.apb_write(ADDR_BAUD, 0x33)
    model = sim.model
    assert model.comb(1, 1, 0, ADDR_BAUD, 0)[0] == 0x33
    assert model.comb(0, 0, 0, ADDR_BAUD, 0)[0] == 0
    assert model.comb(0, 1, 0, ADDR_BAUD, 0)[0] == 0
    assert model.comb(1, 1, 1, ADDR_BAUD, 0)[0] == 0


# ----------------------------------------------------------------------
# PSLVERR
# ----------------------------------------------------------------------


def test_pslverr_on_unmapped_addresses():
    """SPEC 3: all eight address bits are decoded, so 0x01 / 0x1C / 0xFF are errors."""
    sim = Sim()
    for addr in (0x01, 0x1C, 0xFF):
        access, value, err = sim.apb_read(addr)
        assert err == 1, "read of %#04x should be an error" % addr
        assert value == 0, "an error read returns 0"
        assert EV_APB_ERROR in sim.events[access]
        assert EV_APB_READ not in sim.events[access]

        access = sim.apb_write(addr, 0xFF)
        assert sim.log[access].pslverr == 1
        assert EV_APB_ERROR in sim.events[access]
        assert EV_APB_WRITE not in sim.events[access]


def test_pslverr_on_writes_to_read_only_registers():
    """SPEC 3: writes to STATUS and RXDATA are errors; reads of them are not."""
    sim = Sim()
    for addr in (ADDR_STATUS, ADDR_RXDATA):
        access = sim.apb_write(addr, 0xFFFF)
        assert sim.log[access].pslverr == 1
        assert EV_APB_ERROR in sim.events[access]
        access, _, err = sim.apb_read(addr)
        assert err == 0
        assert EV_APB_READ in sim.events[access]


def test_pslverr_needs_psel_and_penable():
    """SPEC 3: pslverr is 1 exactly when psel = 1, penable = 1 and it is an error."""
    model = UartModel()
    assert model.comb(1, 1, 0, 0x01, 0)[2] == 1
    assert model.comb(1, 0, 0, 0x01, 0)[2] == 0  # setup phase
    assert model.comb(0, 1, 0, 0x01, 0)[2] == 0
    assert model.comb(0, 0, 0, 0x01, 0)[2] == 0
    assert model.comb(1, 1, 0, ADDR_CTRL, 0)[2] == 0


def test_error_access_has_no_side_effects():
    """SPEC 3: an error access has no side effects at all."""
    sim = Sim()
    # A write to STATUS must not disturb CTRL/BAUD or push anything.
    sim.apb_write(ADDR_CTRL, 0x15)
    sim.apb_write(ADDR_BAUD, 0x09)
    before_ctrl, before_baud = sim.model.ctrl, sim.model.baud
    access = sim.apb_write(ADDR_STATUS, 0xFFFFFFFF)
    sim.idle(1)
    assert sim.log[access + 1].ctrl == before_ctrl
    assert sim.log[access + 1].baud == before_baud
    assert sim.log[access + 1].tx_count == sim.log[access].tx_count

    # An unmapped write does not push onto the TX FIFO.
    count_before = sim.model.tx_count
    access = sim.apb_write(0x0D, 0x77)
    sim.idle(1)
    assert sim.log[access + 1].tx_count == count_before
    assert EV_TX_PUSH not in sim.events[access]

    # An erroneous *write* to RXDATA must not pop the RX FIFO.
    sim = Sim()
    sim.apb_write(ADDR_CTRL, RX_EN)
    sim.run_until(20)
    sim.queue_rx_frame(0x5A, div=0)
    sim.run_until(40)
    assert sim.model.rx_count == 1
    access = sim.apb_write(ADDR_RXDATA, 0x1)
    sim.idle(1)
    assert sim.log[access + 1].rx_count == 1
    assert EV_RX_POP not in sim.events[access]


# ----------------------------------------------------------------------
# Transmitter waveform
# ----------------------------------------------------------------------


def _start_one_tx_frame(sim, byte, ctrl, baud):
    """Configure, push one byte, and return the frame-start edge ``s``.

    ``tx_en`` is enabled *after* the byte is queued, so the frame start edge is
    the edge right after the CTRL access edge and is exactly predictable.
    """
    sim.apb_write(ADDR_BAUD, baud)
    sim.apb_write(ADDR_TXDATA, byte)
    ctrl_edge = sim.apb_write(ADDR_CTRL, ctrl | TX_EN)
    return ctrl_edge + 1


def test_tx_waveform_div0_no_parity_literal():
    """SPEC 5: hand-written waveform for 0xA5 at div = 0, no parity, one stop bit."""
    sim = Sim()
    start = _start_one_tx_frame(sim, 0xA5, ctrl=0, baud=0)
    sim.run_until(start + 20)

    # N = 10, P = 1, so NP = 10.
    expected = [0, 1, 0, 1, 0, 0, 1, 0, 1, 1]
    assert sim.log[start].txd == 1, "txd still idle in the cycle before the frame"
    for offset, value in enumerate(expected):
        assert sim.log[start + 1 + offset].txd == value, "cycle s+%d" % (offset + 1)
    assert sim.log[start + 11].txd == 1, "idle again after the frame"
    assert EV_TX_FRAME_START in sim.events[start]
    assert EV_TX_POP in sim.events[start]


def test_txd_falls_exactly_one_edge_after_the_txdata_write():
    """SPEC 5: no write-through — a byte written at edge n makes txd fall at edge n+1."""
    sim = Sim()
    sim.apb_write(ADDR_CTRL, TX_EN)  # tx_en already on, FIFO empty
    sim.run_until(10)
    write_edge = sim.apb_write(ADDR_TXDATA, 0x01)
    sim.run_until(write_edge + 20)
    assert sim.log[write_edge].txd == 1
    assert sim.log[write_edge + 1].txd == 1, "still idle in the cycle after the write edge"
    assert sim.log[write_edge + 2].txd == 0, "start bit in the cycle after edge n+1"
    assert EV_TX_FRAME_START in sim.events[write_edge + 1]
    assert EV_TX_FRAME_START not in sim.events[write_edge]


def test_tx_waveform_div3_no_parity():
    """SPEC 5: at div = 3 every slot lasts P = 4 cycles and NP = 40."""
    sim = Sim()
    byte = 0x3C
    start = _start_one_tx_frame(sim, byte, ctrl=0, baud=3)
    sim.run_until(start + 60)

    expected = expected_tx_waveform(byte, div=3, par_en=0, par_odd=0, stop2=0)
    assert len(expected) == 40
    for offset, value in enumerate(expected):
        assert sim.log[start + 1 + offset].txd == value, "cycle s+%d" % (offset + 1)
    assert sim.log[start + 1].txd == 0
    assert sim.log[start + 4].txd == 0, "start bit still low at s+P"
    assert sim.log[start + 5].txd == (byte >> 0) & 1, "data bit 0 begins at s+P+1"
    assert sim.log[start + 41].txd == 1, "idle in the cycle after edge s+NP"


def test_tx_waveform_even_parity():
    """SPEC 5: with par_en and even parity the parity slot is the XOR of the data bits."""
    sim = Sim()
    start = _start_one_tx_frame(sim, 0xA5, ctrl=PAR_EN, baud=0)
    sim.run_until(start + 20)
    # xor8(0xA5) = 0, so the parity slot is 0 and N = 11.
    expected = [0, 1, 0, 1, 0, 0, 1, 0, 1, 0, 1]
    for offset, value in enumerate(expected):
        assert sim.log[start + 1 + offset].txd == value, "cycle s+%d" % (offset + 1)
    assert sim.log[start + 11].txd == 1, "busy at the last frame cycle s+NP"
    assert sim.log[start + 11].tx_busy == 1
    assert sim.log[start + 12].tx_busy == 0


def test_tx_waveform_odd_parity():
    """SPEC 5: odd parity is the inverse of the even parity bit."""
    sim = Sim()
    start = _start_one_tx_frame(sim, 0xA5, ctrl=PAR_EN | PAR_ODD, baud=0)
    sim.run_until(start + 20)
    expected = [0, 1, 0, 1, 0, 0, 1, 0, 1, 1, 1]
    for offset, value in enumerate(expected):
        assert sim.log[start + 1 + offset].txd == value, "cycle s+%d" % (offset + 1)
    assert sim.log[start + 12].tx_busy == 0


def test_tx_waveform_stop2():
    """SPEC 5: stop2 adds one slot, so N = 11 with no parity."""
    sim = Sim()
    start = _start_one_tx_frame(sim, 0xA5, ctrl=STOP2, baud=0)
    sim.run_until(start + 20)
    expected = [0, 1, 0, 1, 0, 0, 1, 0, 1, 1, 1]
    for offset, value in enumerate(expected):
        assert sim.log[start + 1 + offset].txd == value, "cycle s+%d" % (offset + 1)
    assert sim.log[start + 11].tx_busy == 1, "frame runs to the cycle after edge s+NP-1"
    assert sim.log[start + 12].tx_busy == 0


def test_tx_waveform_parity_and_stop2_at_div2():
    """SPEC 5: N = 10 + par_en + stop2 = 12, P = 3, so the frame is 36 cycles."""
    sim = Sim()
    byte = 0x6B
    start = _start_one_tx_frame(sim, byte, ctrl=PAR_EN | STOP2, baud=2)
    sim.run_until(start + 50)
    expected = expected_tx_waveform(byte, div=2, par_en=1, par_odd=0, stop2=1)
    assert len(expected) == 36
    for offset, value in enumerate(expected):
        assert sim.log[start + 1 + offset].txd == value, "cycle s+%d" % (offset + 1)
    assert sim.log[start + 36].tx_busy == 1
    assert sim.log[start + 37].tx_busy == 0


def test_tx_busy_window():
    """SPEC 5: tx_busy is 1 in the cycles after edges s … s + NP - 1 and 0 otherwise."""
    sim = Sim()
    start = _start_one_tx_frame(sim, 0x00, ctrl=0, baud=0)
    sim.run_until(start + 25)
    assert sim.log[start].tx_busy == 0
    for offset in range(1, 11):
        assert sim.log[start + offset].tx_busy == 1, "cycle s+%d" % offset
    assert sim.log[start + 11].tx_busy == 0


def test_status_reflects_tx_busy_and_counts():
    """SPEC 4.3: STATUS bit 4 is tx_busy, bits 10:8 are tx_count."""
    sim = Sim()
    sim.apb_write(ADDR_TXDATA, 0x11)
    sim.apb_write(ADDR_TXDATA, 0x22)
    _, status, _ = sim.apb_read(ADDR_STATUS)
    assert status & 0x1 == 0, "tx_empty clear"
    assert (status >> 8) & 0x7 == 2
    assert (status >> 4) & 1 == 0, "not busy: tx_en is 0"
    sim.apb_write(ADDR_TXDATA, 0x33)
    sim.apb_write(ADDR_TXDATA, 0x44)
    _, status, _ = sim.apb_read(ADDR_STATUS)
    assert (status >> 8) & 0x7 == 4
    assert (status >> 1) & 1 == 1, "tx_full"


def test_status_busy_bits_track_the_engines_cycle_by_cycle():
    """SPEC 4.3: STATUS bit 4 is tx_busy and bit 5 is rx_busy, every cycle."""
    sim = Sim()
    sim.apb_write(ADDR_TXDATA, 0xA5)
    ctrl_edge = sim.apb_write(ADDR_CTRL, TX_EN | RX_EN | LOOPBACK)
    start = ctrl_edge + 1
    # Read STATUS combinationally in every cycle of the loopback frame and check
    # both busy bits against the introspection properties.
    for _ in range(30):
        status = sim.model.comb(1, 1, 0, ADDR_STATUS, 0)[0]
        assert (status >> 4) & 1 == sim.model.tx_busy, "cycle %d" % sim.t
        assert (status >> 5) & 1 == sim.model.rx_busy, "cycle %d" % sim.t
        sim.tick()
    assert sim.log[start + 1].tx_busy == 1
    assert sim.log[start + 4].rx_busy == 1, "rx_busy from the cycle after edge c = s+3"
    assert sim.log[start + 3].rx_busy == 0


def test_tx_en_gates_new_frames_only():
    """SPEC 4.1 / 5: with tx_en = 0 a queued byte never starts a frame."""
    sim = Sim()
    sim.apb_write(ADDR_TXDATA, 0x5A)
    sim.run_until(40)
    assert sim.model.tx_count == 1
    assert sim.model.tx_busy == 0
    for edge in range(sim.t):
        assert EV_TX_FRAME_START not in sim.events[edge]
    for cycle in range(sim.t):
        assert sim.log[cycle].txd == 1, "txd idles high the whole time"


def test_rx_en_gates_start_detection():
    """SPEC 4.1 / 6: with rx_en = 0 a start bit on the pin is ignored."""
    sim = Sim()
    sim.run_until(10)
    sim.queue_rx_frame(0x5A, div=0)
    sim.run_until(40)
    assert sim.model.rx_count == 0
    assert sim.model.rx_busy == 0
    for edge in range(sim.t):
        assert EV_RX_START not in sim.events[edge]


def test_clearing_rx_en_mid_frame_does_not_abort():
    """SPEC 6: clearing rx_en mid-frame does not abort the frame in flight."""
    sim = Sim()
    sim.apb_write(ADDR_CTRL, RX_EN)
    sim.run_until(20)
    _, detect, stop_edge = _receive_one(sim, 0x8E, div=0)
    sim.run_until(detect + 2)
    sim.apb_write(ADDR_CTRL, 0)  # clear rx_en mid-frame
    sim.run_until(stop_edge + 5)
    assert EV_RX_PUSH in sim.events[stop_edge]
    assert sim.log[stop_edge + 1].rx_count == 1
    _, value, _ = sim.apb_read(ADDR_RXDATA)
    assert value == 0x8E


def test_back_to_back_frames_have_no_idle_cycle():
    """SPEC 5: edge s + NP starts the next frame when tx_en and the FIFO allow."""
    sim = Sim()
    sim.apb_write(ADDR_TXDATA, 0xFF)
    sim.apb_write(ADDR_TXDATA, 0x00)
    ctrl_edge = sim.apb_write(ADDR_CTRL, TX_EN)
    first = ctrl_edge + 1
    second = first + 10  # NP = 10 at div = 0
    sim.run_until(second + 20)

    assert EV_TX_FRAME_START in sim.events[first]
    assert EV_TX_FRAME_BACK_TO_BACK not in sim.events[first]
    assert EV_TX_FRAME_START in sim.events[second]
    assert EV_TX_FRAME_BACK_TO_BACK in sim.events[second]

    # Frame 1 is 0xFF: start low then eight ones then stop.
    assert [sim.log[first + 1 + k].txd for k in range(10)] == [0, 1, 1, 1, 1, 1, 1, 1, 1, 1]
    # No idle cycle: the stop bit of frame 1 is immediately followed by the
    # start bit of frame 2.
    assert sim.log[second].txd == 1, "stop bit of frame 1"
    assert sim.log[second + 1].txd == 0, "start bit of frame 2, no idle cycle"
    # Frame 2 is 0x00: start low, eight zeros, stop high.
    assert [sim.log[second + 1 + k].txd for k in range(10)] == [0, 0, 0, 0, 0, 0, 0, 0, 0, 1]
    # tx_busy never drops between the two frames.
    for cycle in range(first + 1, second + 11):
        assert sim.log[cycle].tx_busy == 1, "cycle %d" % cycle
    assert sim.log[second + 11].tx_busy == 0


def test_clearing_tx_en_mid_frame_does_not_abort():
    """SPEC 5: tx_en only gates the start of new frames."""
    sim = Sim()
    sim.apb_write(ADDR_TXDATA, 0xA5)
    sim.apb_write(ADDR_TXDATA, 0x5A)
    ctrl_edge = sim.apb_write(ADDR_CTRL, TX_EN)
    start = ctrl_edge + 1
    sim.run_until(start + 2)
    sim.apb_write(ADDR_CTRL, 0)  # clear tx_en mid-frame
    sim.run_until(start + 30)
    assert [sim.log[start + 1 + k].txd for k in range(10)] == [0, 1, 0, 1, 0, 0, 1, 0, 1, 1]
    assert sim.log[start + 11].tx_busy == 0, "no second frame: tx_en was cleared"
    assert sim.log[start + 11].tx_count == 1, "the queued byte is still there"


# ----------------------------------------------------------------------
# TX FIFO: overflow and tx_empty_ev
# ----------------------------------------------------------------------


def test_tx_overflow_sets_tx_ovf_and_drops():
    """SPEC 4.4: a write with pre-edge count 4 is discarded and sets tx_ovf."""
    sim = Sim()
    for byte in (1, 2, 3, 4):
        sim.apb_write(ADDR_TXDATA, byte)
    assert sim.model.tx_count == 4
    access = sim.apb_write(ADDR_TXDATA, 5)
    sim.idle(1)
    assert EV_TX_PUSH_DROPPED in sim.events[access]
    assert EV_TX_PUSH not in sim.events[access]
    assert sim.log[access + 1].tx_count == 4
    assert sim.log[access].irq_stat == 0
    assert sim.log[access + 1].irq_stat == IRQ_TX_OVF


def test_tx_overflow_drops_even_when_the_transmitter_pops_at_the_same_edge():
    """SPEC 4.4 / 7: the drop is decided on the pre-edge count, pop or no pop."""
    sim = Sim()
    for byte in (0x10, 0x20, 0x30, 0x40):
        sim.apb_write(ADDR_TXDATA, byte)
    ctrl_edge = sim.apb_write(ADDR_CTRL, TX_EN)
    first = ctrl_edge + 1  # frame 1 starts here, count 4 -> 3
    sim.run_until(first + 2)
    sim.apb_write(ADDR_TXDATA, 0x50)  # back to 4
    assert sim.model.tx_count == 4

    # Frame 1 ends (and frame 2 starts) at edge first + 10 with div = 0.
    target = first + 10
    sim.run_until(target - 1)
    access = sim.apb_write(ADDR_TXDATA, 0x60)
    assert access == target
    sim.run_until(target + 15)

    assert EV_TX_FRAME_BACK_TO_BACK in sim.events[access], "a pop happens at this edge"
    assert EV_TX_PUSH_DROPPED in sim.events[access]
    assert EV_TX_PUSH not in sim.events[access]
    assert sim.log[access].tx_count == 4
    assert sim.log[access + 1].tx_count == 3, "pop happened, push was dropped"
    assert sim.log[access + 1].irq_stat & IRQ_TX_OVF == IRQ_TX_OVF


def test_simultaneous_tx_push_and_pop_leave_the_count_unchanged():
    """SPEC 4.4: a push and a pop at the same edge (count 1..3) keep the count."""
    sim = Sim()
    sim.apb_write(ADDR_TXDATA, 0x01)
    sim.apb_write(ADDR_TXDATA, 0x02)
    ctrl_edge = sim.apb_write(ADDR_CTRL, TX_EN)
    first = ctrl_edge + 1
    target = first + 10  # back-to-back start: pre-edge count is 1
    sim.run_until(target - 1)
    access = sim.apb_write(ADDR_TXDATA, 0x03)
    assert access == target
    sim.run_until(target + 5)
    assert sim.log[access].tx_count == 1
    assert EV_TX_PUSH in sim.events[access]
    assert EV_TX_POP in sim.events[access]
    assert sim.log[access + 1].tx_count == 1


def test_tx_empty_ev_set_when_the_last_byte_is_popped():
    """SPEC 4.6 / 7: pre-edge count 1, a pop, and no push accepted."""
    sim = Sim()
    sim.apb_write(ADDR_TXDATA, 0x7E)
    ctrl_edge = sim.apb_write(ADDR_CTRL, TX_EN)
    start = ctrl_edge + 1
    sim.run_until(start + 5)
    assert sim.log[start].tx_count == 1
    assert sim.log[start].irq_stat == 0
    assert sim.log[start + 1].irq_stat == IRQ_TX_EMPTY_EV
    assert sim.log[start + 1].tx_count == 0


def test_tx_empty_ev_not_set_when_a_push_lands_at_the_same_edge():
    """SPEC 7: tx_empty_ev requires that no push is accepted at that edge."""
    sim = Sim()
    sim.apb_write(ADDR_TXDATA, 0x01)
    sim.apb_write(ADDR_TXDATA, 0x02)
    ctrl_edge = sim.apb_write(ADDR_CTRL, TX_EN)
    first = ctrl_edge + 1
    target = first + 10  # pre-edge count 1 here
    sim.run_until(target - 1)
    assert sim.log[first].tx_count == 2
    access = sim.apb_write(ADDR_TXDATA, 0x03)
    assert access == target
    sim.run_until(target + 5)
    assert sim.log[access].tx_count == 1
    assert sim.log[access].irq_stat == 0
    assert sim.log[access + 1].irq_stat == 0, "a push landed, so no tx_empty_ev"

    # Same shape without the push: the event fires.
    sim2 = Sim()
    sim2.apb_write(ADDR_TXDATA, 0x01)
    sim2.apb_write(ADDR_TXDATA, 0x02)
    ctrl_edge2 = sim2.apb_write(ADDR_CTRL, TX_EN)
    first2 = ctrl_edge2 + 1
    target2 = first2 + 10
    sim2.run_until(target2 + 5)
    assert sim2.log[target2].tx_count == 1
    assert sim2.log[target2 + 1].irq_stat == IRQ_TX_EMPTY_EV


# ----------------------------------------------------------------------
# Receiver
# ----------------------------------------------------------------------
#
# Pin latency (SPEC 6, input path): if cycle x is the first cycle in which rxd
# is 0, then s1 takes it at edge x, s2 at edge x + 1, and the start is detected
# at edge c = x + 2.


def _receive_one(sim, byte, div, par_en=0, par_odd=0, parity_override=None, stop_value=1):
    """Queue a frame starting at the current cycle. Returns ``(x, c, e)``."""
    period = div + 1
    half = div >> 1
    start_cycle = sim.t
    sim.queue_rx_frame(
        byte, div, par_en=par_en, par_odd=par_odd,
        parity_override=parity_override, stop_value=stop_value,
    )
    detect = start_cycle + 2
    stop_edge = detect + half + (10 if par_en else 9) * period
    return start_cycle, detect, stop_edge


def test_rx_frame_div0_exact_edges():
    """SPEC 6: at div = 0 (P = 1, h = 0) the stop edge is c + 9."""
    sim = Sim()
    sim.apb_write(ADDR_CTRL, RX_EN)
    sim.run_until(20)
    start_cycle, detect, stop_edge = _receive_one(sim, 0x96, div=0)
    assert (start_cycle, detect, stop_edge) == (20, 22, 31)
    sim.run_until(stop_edge + 10)

    assert EV_RX_START in sim.events[detect]
    assert EV_RX_START not in sim.events[detect - 1]
    assert sim.log[detect].rx_busy == 0
    assert sim.log[detect + 1].rx_busy == 1
    assert sim.log[stop_edge].rx_busy == 1, "busy through the cycle after edge e-1"
    assert sim.log[stop_edge + 1].rx_busy == 0

    assert EV_RX_PUSH in sim.events[stop_edge]
    assert sim.log[stop_edge].rx_count == 0
    assert sim.log[stop_edge + 1].rx_count == 1
    assert sim.log[stop_edge + 1].irq_stat == IRQ_RX_AVAIL_EV

    _, value, _ = sim.apb_read(ADDR_RXDATA)
    assert value == 0x96, "data byte, perr = ferr = 0"


def test_rx_frame_div1_exact_edges():
    """SPEC 6: at div = 1, P = 2 and h = 0, so e = c + 18."""
    sim = Sim()
    sim.apb_write(ADDR_BAUD, 1)
    sim.apb_write(ADDR_CTRL, RX_EN)
    sim.run_until(30)
    start_cycle, detect, stop_edge = _receive_one(sim, 0xC3, div=1)
    assert (start_cycle, detect, stop_edge) == (30, 32, 50)
    sim.run_until(stop_edge + 10)
    assert EV_RX_START in sim.events[detect]
    assert sim.log[stop_edge].rx_count == 0
    assert sim.log[stop_edge + 1].rx_count == 1
    assert EV_RX_PUSH in sim.events[stop_edge]
    _, value, _ = sim.apb_read(ADDR_RXDATA)
    assert value == 0xC3


def test_rx_frame_div5_exact_edges():
    """SPEC 6: at div = 5, P = 6 and h = 2, so e = c + 2 + 54."""
    sim = Sim()
    sim.apb_write(ADDR_BAUD, 5)
    sim.apb_write(ADDR_CTRL, RX_EN)
    sim.run_until(40)
    start_cycle, detect, stop_edge = _receive_one(sim, 0x7D, div=5)
    assert (start_cycle, detect, stop_edge) == (40, 42, 98)
    sim.run_until(stop_edge + 10)
    assert EV_RX_START in sim.events[detect]
    assert sim.log[detect + 1].rx_busy == 1
    assert sim.log[stop_edge].rx_count == 0
    assert sim.log[stop_edge + 1].rx_count == 1
    assert sim.log[stop_edge + 1].rx_busy == 0
    _, value, _ = sim.apb_read(ADDR_RXDATA)
    assert value == 0x7D


def test_rx_false_start_at_div6():
    """SPEC 6: at div = 6, h = 3, so a glitch shorter than 3 cycles is a false start."""
    sim = Sim()
    sim.apb_write(ADDR_BAUD, 6)
    sim.apb_write(ADDR_CTRL, RX_EN)
    sim.run_until(20)
    start_cycle = sim.t
    sim.queue_rx_bits([0, 0, 0])  # low for cycles 20, 21, 22 only
    sim.run_until(start_cycle + 20)

    detect = start_cycle + 2  # edge 22
    check = detect + 3  # edge c + h = 25
    assert EV_RX_START in sim.events[detect]
    assert EV_RX_FALSE_START in sim.events[check]
    assert sim.log[detect + 1].rx_busy == 1
    assert sim.log[check].rx_busy == 1, "busy through the cycle after edge c+h-1"
    assert sim.log[check + 1].rx_busy == 0
    assert sim.model.rx_count == 0
    assert sim.model.irq_stat == 0
    # No further start is detected from the same glitch.
    for edge in range(check + 1, start_cycle + 20):
        assert EV_RX_START not in sim.events[edge], "edge %d" % edge


def test_rx_parity_error():
    """SPEC 6: perr when (XOR of data) XOR (parity sample) differs from par_odd."""
    sim = Sim()
    sim.apb_write(ADDR_CTRL, RX_EN | PAR_EN)
    sim.run_until(20)
    good_parity = xor8(0x3B)
    _, detect, stop_edge = _receive_one(
        sim, 0x3B, div=0, par_en=1, par_odd=0, parity_override=good_parity ^ 1
    )
    assert stop_edge == detect + 10
    sim.run_until(stop_edge + 10)
    assert EV_RX_PERR in sim.events[stop_edge]
    assert EV_RX_FERR not in sim.events[stop_edge]
    assert EV_RX_PUSH in sim.events[stop_edge]
    assert sim.log[stop_edge + 1].irq_stat == IRQ_RX_AVAIL_EV | IRQ_PERR_EV
    _, value, _ = sim.apb_read(ADDR_RXDATA)
    assert value == (1 << 8) | 0x3B, "perr in bit 8"


def test_rx_parity_ok_even_and_odd():
    """SPEC 6: a correctly parity-coded frame sets no perr, for both polarities."""
    for par_odd in (0, 1):
        sim = Sim()
        sim.apb_write(ADDR_CTRL, RX_EN | PAR_EN | (PAR_ODD if par_odd else 0))
        sim.run_until(20)
        _, _, stop_edge = _receive_one(sim, 0x3B, div=0, par_en=1, par_odd=par_odd)
        sim.run_until(stop_edge + 10)
        assert EV_RX_PERR not in sim.events[stop_edge]
        assert sim.log[stop_edge + 1].irq_stat == IRQ_RX_AVAIL_EV
        _, value, _ = sim.apb_read(ADDR_RXDATA)
        assert value == 0x3B


def test_rx_framing_error():
    """SPEC 6: ferr when the stop sample is 0; the entry is still pushed."""
    sim = Sim()
    sim.apb_write(ADDR_CTRL, RX_EN)
    sim.run_until(20)
    # div = 0, h = 0: the stop sample at edge e reflects rxd in cycle e - 2, which
    # is the single stop-bit cycle. rxd returns high straight afterwards, so no
    # new start is detected at e + 1.
    _, detect, stop_edge = _receive_one(sim, 0x5C, div=0, stop_value=0)
    sim.run_until(stop_edge + 10)
    assert EV_RX_FERR in sim.events[stop_edge]
    assert EV_RX_PUSH in sim.events[stop_edge]
    assert sim.log[stop_edge + 1].irq_stat == IRQ_RX_AVAIL_EV | IRQ_FERR_EV
    assert EV_RX_START not in sim.events[stop_edge + 1], "rxd is high again by then"
    _, value, _ = sim.apb_read(ADDR_RXDATA)
    assert value == (1 << 9) | 0x5C, "ferr in bit 9"


def test_rx_framing_error_followed_by_a_new_start():
    """SPEC 6: after a framing error a still-low line is a new start like any other."""
    sim = Sim()
    sim.apb_write(ADDR_CTRL, RX_EN)
    sim.run_until(20)
    _, _, stop_edge = _receive_one(sim, 0x00, div=0, stop_value=0)
    sim.queue_rx_bits([0, 0])  # hold the line low past the stop bit
    sim.run_until(stop_edge + 6)
    assert EV_RX_FERR in sim.events[stop_edge]
    assert EV_RX_START in sim.events[stop_edge + 1], "idle from edge e, detects at e+1"


def test_rx_overrun_when_the_fifo_is_full():
    """SPEC 6 / 4.5: a fifth frame is discarded and sets rx_ovr."""
    sim = Sim()
    sim.apb_write(ADDR_CTRL, RX_EN)
    sim.run_until(20)
    start_cycle = sim.t
    for byte in (0x01, 0x02, 0x03, 0x04, 0x05):
        sim.queue_rx_frame(byte, div=0)
    # Back-to-back frames at div = 0 occupy 10 cycles each; frame i is detected
    # at start_cycle + 10i + 2 and completes at start_cycle + 10i + 11.
    stops = [start_cycle + 10 * i + 11 for i in range(5)]
    sim.run_until(stops[-1] + 10)

    for index in range(5):
        detect = start_cycle + 10 * index + 2
        assert EV_RX_START in sim.events[detect], "frame %d detected at c" % index
    for index in range(4):
        assert EV_RX_PUSH in sim.events[stops[index]], "frame %d" % index
        assert sim.log[stops[index] + 1].rx_count == index + 1
    assert sim.log[stops[4]].rx_count == 4
    assert EV_RX_OVERRUN in sim.events[stops[4]]
    assert EV_RX_PUSH not in sim.events[stops[4]]
    assert sim.log[stops[4] + 1].rx_count == 4
    assert sim.log[stops[4] + 1].irq_stat & IRQ_RX_OVR == IRQ_RX_OVR


def test_rx_overrun_even_when_a_pop_happens_at_the_same_edge():
    """SPEC 4.5 / 7: a push at pre-edge count 4 is an overrun even with a pop."""
    sim = Sim()
    sim.apb_write(ADDR_CTRL, RX_EN)
    sim.run_until(20)
    start_cycle = sim.t
    for byte in (0x01, 0x02, 0x03, 0x04, 0x05):
        sim.queue_rx_frame(byte, div=0)
    stops = [start_cycle + 10 * i + 11 for i in range(5)]

    sim.run_until(stops[4] - 1)
    access, value, _ = sim.apb_read(ADDR_RXDATA)
    assert access == stops[4]
    assert value == 0x01, "the pop returns the head, read combinationally"
    sim.run_until(stops[4] + 10)

    assert EV_RX_POP in sim.events[access]
    assert EV_RX_OVERRUN in sim.events[access]
    assert EV_RX_PUSH not in sim.events[access]
    assert sim.log[access].rx_count == 4
    assert sim.log[access + 1].rx_count == 3, "popped, and the new frame discarded"
    assert sim.log[access + 1].irq_stat & IRQ_RX_OVR == IRQ_RX_OVR


def test_rxdata_pop_when_empty_with_a_push_at_the_same_edge():
    """SPEC 4.5 / 7: a read at pre-edge count 0 returns 0 and pops nothing."""
    sim = Sim()
    sim.apb_write(ADDR_CTRL, RX_EN)
    sim.run_until(20)
    _, _, stop_edge = _receive_one(sim, 0xE1, div=0)
    sim.run_until(stop_edge - 1)
    access, value, err = sim.apb_read(ADDR_RXDATA)
    assert access == stop_edge
    assert value == 0, "pre-edge count is 0, so the read returns 0"
    assert err == 0
    sim.run_until(stop_edge + 5)
    assert EV_RX_POP_EMPTY in sim.events[access]
    assert EV_RX_POP not in sim.events[access]
    assert EV_RX_PUSH in sim.events[access]
    assert sim.log[access].rx_count == 0
    assert sim.log[access + 1].rx_count == 1, "the push landed, nothing was popped"
    _, value, _ = sim.apb_read(ADDR_RXDATA)
    assert value == 0xE1


def test_rxdata_read_pops_exactly_at_the_access_edge():
    """SPEC 4.5: the pop happens at the access edge, not the setup edge."""
    sim = Sim()
    sim.apb_write(ADDR_CTRL, RX_EN)
    sim.run_until(20)
    _, _, stop_edge = _receive_one(sim, 0x42, div=0)
    sim.run_until(stop_edge + 3)
    access, value, _ = sim.apb_read(ADDR_RXDATA)
    sim.idle(2)
    assert value == 0x42
    assert sim.log[access - 1].rx_count == 1, "setup cycle: still there"
    assert sim.log[access].rx_count == 1
    assert sim.log[access + 1].rx_count == 0
    assert EV_RX_POP in sim.events[access]


# ----------------------------------------------------------------------
# Loopback
# ----------------------------------------------------------------------


def test_loopback_one_byte_with_exact_latency():
    """SPEC 6: in loopback rx_in is txd, so the start is detected at edge s + 3."""
    sim = Sim()
    byte = 0xB4
    sim.apb_write(ADDR_TXDATA, byte)
    ctrl_edge = sim.apb_write(ADDR_CTRL, TX_EN | RX_EN | LOOPBACK)
    start = ctrl_edge + 1  # txd falls: 0 in the cycle after this edge
    detect = start + 3  # txd at s+1 -> s1 at s+1 -> s2 at s+2 -> detect at s+3
    stop_edge = detect + 9  # div = 0, no parity
    sim.run_until(stop_edge + 10)

    assert sim.log[start + 1].txd == 0
    assert EV_RX_START in sim.events[detect]
    assert EV_RX_START not in sim.events[detect - 1]
    assert EV_RX_PUSH in sim.events[stop_edge]
    assert sim.log[stop_edge].rx_count == 0
    assert sim.log[stop_edge + 1].rx_count == 1
    _, value, _ = sim.apb_read(ADDR_RXDATA)
    assert value == byte, "no parity or framing error in loopback"


def test_loopback_ignores_the_rxd_pin():
    """SPEC 6: in loopback the rxd pin is ignored."""
    sim = Sim()
    sim.apb_write(ADDR_CTRL, RX_EN | LOOPBACK)
    sim.run_until(20)
    for _ in range(40):
        sim.tick(rxd=0)  # a long low on the pin, which must be ignored
    assert sim.model.rx_count == 0
    assert sim.model.rx_busy == 0
    for edge in range(20, sim.t):
        assert EV_RX_START not in sim.events[edge]


# ----------------------------------------------------------------------
# Interrupts
# ----------------------------------------------------------------------


def test_irq_stat_write_one_to_clear():
    """SPEC 4.6: a write to IRQ_STAT clears every bit whose pwdata bit is 1."""
    sim = Sim()
    for byte in (1, 2, 3, 4):
        sim.apb_write(ADDR_TXDATA, byte)
    sim.apb_write(ADDR_TXDATA, 5)  # overflow -> tx_ovf
    _, value, _ = sim.apb_read(ADDR_IRQ_STAT)
    assert value == IRQ_TX_OVF

    access = sim.apb_write(ADDR_IRQ_STAT, 0x01)  # wrong bit: no change
    sim.idle(1)
    assert sim.log[access + 1].irq_stat == IRQ_TX_OVF
    access = sim.apb_write(ADDR_IRQ_STAT, IRQ_TX_OVF)
    sim.idle(1)
    assert sim.log[access].irq_stat == IRQ_TX_OVF
    assert sim.log[access + 1].irq_stat == 0


def test_irq_stat_set_wins_over_write_one_to_clear():
    """SPEC 4.6 / 7: if a bit is set and cleared at the same edge, set wins."""
    sim = Sim()
    sim.apb_write(ADDR_CTRL, RX_EN)
    sim.run_until(20)
    start_cycle = sim.t
    sim.queue_rx_frame(0x11, div=0)
    sim.queue_rx_frame(0x22, div=0)
    first_stop = start_cycle + 11
    second_stop = start_cycle + 21
    sim.run_until(first_stop + 2)
    assert sim.model.irq_stat == IRQ_RX_AVAIL_EV

    sim.run_until(second_stop - 1)
    access = sim.apb_write(ADDR_IRQ_STAT, IRQ_RX_AVAIL_EV)
    assert access == second_stop
    sim.run_until(second_stop + 5)
    assert EV_RX_PUSH in sim.events[access]
    assert EV_IRQ_CLEAR_LOST_TO_SET in sim.events[access]
    assert sim.log[access + 1].irq_stat & IRQ_RX_AVAIL_EV == IRQ_RX_AVAIL_EV, "set wins"


def test_irq_stat_set_wins_for_tx_empty_ev_too():
    """SPEC 7: set wins over W1C for a bit set by the transmitter, not the receiver."""
    sim = Sim()
    sim.apb_write(ADDR_TXDATA, 0x01)
    sim.apb_write(ADDR_TXDATA, 0x02)
    ctrl_edge = sim.apb_write(ADDR_CTRL, TX_EN)
    first = ctrl_edge + 1
    target = first + 10  # back-to-back start with pre-edge count 1 -> tx_empty_ev
    sim.run_until(target - 1)
    access = sim.apb_write(ADDR_IRQ_STAT, IRQ_TX_EMPTY_EV)
    assert access == target
    sim.run_until(target + 5)
    assert EV_TX_POP in sim.events[access]
    assert EV_IRQ_CLEAR_LOST_TO_SET in sim.events[access]
    assert sim.log[access].irq_stat == 0
    assert sim.log[access + 1].irq_stat == IRQ_TX_EMPTY_EV, "set wins over the W1C"


def test_rx_fifo_returns_entries_in_order_with_their_own_flags():
    """SPEC 4.5: RXDATA pops the head; each entry carries its own perr / ferr."""
    sim = Sim()
    sim.apb_write(ADDR_CTRL, RX_EN)
    sim.run_until(20)
    start_cycle = sim.t
    sim.queue_rx_frame(0x11, div=0)
    sim.queue_rx_frame(0x22, div=0, stop_value=0)  # framing error on the second
    sim.queue_rx_frame(0x33, div=0)
    sim.queue_rx_frame(0x44, div=0)
    stops = [start_cycle + 10 * i + 11 for i in range(4)]
    sim.run_until(stops[-1] + 5)

    assert sim.model.rx_count == 4
    status = sim.model.comb(1, 1, 0, ADDR_STATUS, 0)[0]
    assert (status >> 3) & 1 == 1, "rx_full"
    assert (status >> 2) & 1 == 0, "rx_empty clear"
    assert (status >> 12) & 0x7 == 4

    expected = [0x11, (1 << 9) | 0x22, 0x33, 0x44]
    for index, want in enumerate(expected):
        access, value, _ = sim.apb_read(ADDR_RXDATA)
        sim.idle(1)
        assert value == want, "entry %d" % index
        assert sim.log[access + 1].rx_count == 3 - index

    status = sim.model.comb(1, 1, 0, ADDR_STATUS, 0)[0]
    assert (status >> 2) & 1 == 1, "rx_empty"
    assert (status >> 3) & 1 == 0, "rx_full clear"
    assert (status >> 12) & 0x7 == 0
    # A further read returns 0 and pops nothing.
    access, value, err = sim.apb_read(ADDR_RXDATA)
    sim.idle(1)
    assert value == 0
    assert err == 0
    assert EV_RX_POP_EMPTY in sim.events[access]
    assert sim.log[access + 1].rx_count == 0


def test_irq_is_the_or_of_stat_and_en():
    """SPEC 4.6: irq = 1 exactly when (IRQ_STAT & IRQ_EN) != 0, from state only."""
    sim = Sim()
    sim.apb_write(ADDR_IRQ_EN, IRQ_RX_AVAIL_EV)
    sim.apb_write(ADDR_CTRL, RX_EN)
    sim.run_until(20)
    _, _, stop_edge = _receive_one(sim, 0x33, div=0)
    sim.run_until(stop_edge + 5)
    assert sim.log[stop_edge].irq == 0
    assert sim.log[stop_edge + 1].irq == 1, "irq rises in the cycle after the push edge"

    # Masking the bit off drops irq, without touching IRQ_STAT.
    access = sim.apb_write(ADDR_IRQ_EN, 0)
    sim.idle(2)
    assert sim.log[access + 1].irq == 0
    assert sim.log[access + 1].irq_stat == IRQ_RX_AVAIL_EV

    # An enabled-but-unset bit does not raise irq.
    access = sim.apb_write(ADDR_IRQ_EN, IRQ_FERR_EV)
    sim.idle(2)
    assert sim.log[access + 1].irq == 0


def test_perr_and_ferr_are_set_even_when_the_frame_is_discarded():
    """SPEC 6: perr_ev and ferr_ev are set whether or not an overrun discarded it."""
    sim = Sim()
    sim.apb_write(ADDR_CTRL, RX_EN | PAR_EN)
    sim.run_until(20)
    start_cycle = sim.t
    for _ in range(4):
        sim.queue_rx_frame(0x00, div=0, par_en=1, par_odd=0)
    # Fifth frame: wrong parity and a low stop bit, arriving into a full FIFO.
    sim.queue_rx_frame(0x00, div=0, par_en=1, par_odd=0, parity_override=1, stop_value=0)
    # Each frame is 11 cycles at div = 0 with parity; frame i completes at
    # start_cycle + 11i + 12.
    stops = [start_cycle + 11 * i + 12 for i in range(5)]
    sim.run_until(stops[-1] + 5)

    assert sim.log[stops[4]].rx_count == 4
    assert EV_RX_OVERRUN in sim.events[stops[4]]
    assert EV_RX_PERR in sim.events[stops[4]]
    assert EV_RX_FERR in sim.events[stops[4]]
    expected = IRQ_RX_AVAIL_EV | IRQ_RX_OVR | IRQ_PERR_EV | IRQ_FERR_EV
    assert sim.log[stops[4] + 1].irq_stat == expected


# ----------------------------------------------------------------------
# Frame parameter capture and reset
# ----------------------------------------------------------------------


def test_baud_write_mid_frame_does_not_change_the_frame_in_flight():
    """SPEC 5: div is captured at the frame start edge and fixed for the frame."""
    sim = Sim()
    byte = 0xA5
    start = _start_one_tx_frame(sim, byte, ctrl=0, baud=0)
    sim.run_until(start + 3)
    sim.apb_write(ADDR_BAUD, 7)  # P would be 8 if this were seen
    sim.run_until(start + 30)
    assert [sim.log[start + 1 + k].txd for k in range(10)] == [0, 1, 0, 1, 0, 0, 1, 0, 1, 1]
    assert sim.log[start + 10].tx_busy == 1
    assert sim.log[start + 11].tx_busy == 0, "still a 10-cycle frame"


def test_ctrl_write_mid_frame_does_not_change_the_frame_in_flight():
    """SPEC 5: par_en / stop2 are captured at the frame start edge."""
    sim = Sim()
    start = _start_one_tx_frame(sim, 0xA5, ctrl=0, baud=0)
    sim.run_until(start + 2)
    sim.apb_write(ADDR_CTRL, TX_EN | PAR_EN | STOP2)
    sim.run_until(start + 30)
    assert sim.log[start + 10].tx_busy == 1
    assert sim.log[start + 11].tx_busy == 0, "N is still 10, not 12"


def test_baud_write_at_the_frame_start_edge_is_not_seen_by_that_frame():
    """SPEC 7: a BAUD write at the same edge as a frame start leaves the old div."""
    sim = Sim()
    sim.apb_write(ADDR_TXDATA, 0xA5)
    sim.apb_write(ADDR_TXDATA, 0xA5)
    ctrl_edge = sim.apb_write(ADDR_CTRL, TX_EN)
    first = ctrl_edge + 1
    second = first + 10  # back-to-back start at div = 0
    sim.run_until(second - 1)
    access = sim.apb_write(ADDR_BAUD, 7)
    assert access == second
    sim.run_until(second + 30)

    assert EV_TX_FRAME_START in sim.events[access]
    assert sim.log[access + 1].baud == 7, "the register did take the write"
    # The second frame still runs at the old P = 1.
    assert [sim.log[second + 1 + k].txd for k in range(10)] == [0, 1, 0, 1, 0, 0, 1, 0, 1, 1]
    assert sim.log[second + 10].tx_busy == 1
    assert sim.log[second + 11].tx_busy == 0


def test_rx_captures_div_at_start_detection():
    """SPEC 6: the receiver captures div at edge c; a later BAUD write is ignored."""
    sim = Sim()
    sim.apb_write(ADDR_BAUD, 1)
    sim.apb_write(ADDR_CTRL, RX_EN)
    sim.run_until(30)
    _, detect, stop_edge = _receive_one(sim, 0x99, div=1)
    assert stop_edge == detect + 18
    sim.run_until(detect + 4)
    sim.apb_write(ADDR_BAUD, 0)  # would shorten the frame if it were seen
    sim.run_until(stop_edge + 5)
    assert sim.log[stop_edge].rx_count == 0
    assert sim.log[stop_edge + 1].rx_count == 1, "still a div = 1 frame"
    _, value, _ = sim.apb_read(ADDR_RXDATA)
    assert value == 0x99


def test_reset_in_the_middle_of_a_frame():
    """SPEC 1 / 8: a reset edge overrides everything and restores every reset value."""
    sim = Sim()
    sim.apb_write(ADDR_IRQ_EN, 0x3F)
    start = _start_one_tx_frame(sim, 0xA5, ctrl=0, baud=3)
    sim.run_until(start + 3)  # inside the start bit: P = 4, so slots 1..4 are low
    assert sim.model.tx_busy == 1
    assert sim.model.txd == 0

    reset_edge = sim.t
    # A TXDATA write completing at the same edge must also be ignored.
    sim.tick(presetn=0, psel=1, penable=1, pwrite=1, paddr=ADDR_TXDATA, pwdata=0x5A)
    sim.idle(3)

    assert sim.events[reset_edge] == set(), "no events are recorded on a reset edge"
    assert sim.log[reset_edge + 1].txd == 1
    assert sim.log[reset_edge + 1].tx_busy == 0
    assert sim.log[reset_edge + 1].rx_busy == 0
    assert sim.log[reset_edge + 1].tx_count == 0
    assert sim.log[reset_edge + 1].rx_count == 0
    assert sim.log[reset_edge + 1].ctrl == 0
    assert sim.log[reset_edge + 1].baud == 0
    assert sim.log[reset_edge + 1].irq_en == 0
    assert sim.log[reset_edge + 1].irq_stat == 0
    assert sim.model.comb(1, 1, 0, ADDR_STATUS, 0)[0] == 0x00000005


def test_reset_in_the_middle_of_a_receive_frame():
    """SPEC 1: the receiver is idle again after a reset edge."""
    sim = Sim()
    sim.apb_write(ADDR_CTRL, RX_EN)
    sim.run_until(20)
    _, detect, _ = _receive_one(sim, 0x5A, div=0)
    sim.run_until(detect + 3)
    assert sim.model.rx_busy == 1
    reset_edge = sim.t
    sim.tick(presetn=0)
    sim.idle(3)
    assert sim.log[reset_edge + 1].rx_busy == 0
    assert sim.log[reset_edge + 1].rx_count == 0


def test_explicit_reset_method_matches_a_fresh_model():
    """SPEC 8: reset() forces the reset state from anywhere."""
    sim = Sim()
    sim.apb_write(ADDR_CTRL, 0x3F)
    sim.apb_write(ADDR_BAUD, 0x44)
    sim.apb_write(ADDR_TXDATA, 0x99)
    sim.model.reset()
    fresh = UartModel()
    for name in ("txd", "irq", "tx_count", "rx_count", "tx_busy", "rx_busy",
                 "ctrl", "baud", "irq_en", "irq_stat"):
        assert getattr(sim.model, name) == getattr(fresh, name), name
    assert sim.model.last_events == frozenset()


def test_comb_does_not_change_state():
    """SPEC 3: comb() is purely combinational."""
    sim = Sim()
    sim.apb_write(ADDR_CTRL, RX_EN)
    sim.run_until(20)
    _, _, stop_edge = _receive_one(sim, 0x77, div=0)
    sim.run_until(stop_edge + 3)
    before = (sim.model.rx_count, sim.model.irq_stat, sim.model.txd, sim.model.ctrl)
    for _ in range(5):
        sim.model.comb(1, 1, 0, ADDR_RXDATA, 0)
        sim.model.comb(1, 1, 1, ADDR_CTRL, 0xFF)
        sim.model.comb(1, 1, 0, ADDR_STATUS, 0)
    after = (sim.model.rx_count, sim.model.irq_stat, sim.model.txd, sim.model.ctrl)
    assert before == after


# ----------------------------------------------------------------------
# Schedule sweeps — the same hand-derived formulas, over every parameter
# combination rather than the three or four spot checks above.
# ----------------------------------------------------------------------


@pytest.mark.parametrize("div", [0, 1, 2, 3, 4, 5, 6])
@pytest.mark.parametrize("par_en,par_odd", [(0, 0), (1, 0), (1, 1)])
@pytest.mark.parametrize("stop2", [0, 1])
@pytest.mark.parametrize("byte", [0x00, 0xFF, 0xA5])
def test_tx_schedule_sweep(div, par_en, par_odd, stop2, byte):
    """SPEC 5: the frame layout table and N = 10 + par_en + stop2, for every mix."""
    sim = Sim()
    ctrl = (PAR_EN if par_en else 0) | (PAR_ODD if par_odd else 0) | (STOP2 if stop2 else 0)
    start = _start_one_tx_frame(sim, byte, ctrl=ctrl, baud=div)
    period = div + 1
    slots = 10 + par_en + stop2
    length = slots * period
    sim.run_until(start + length + 6)

    expected = expected_tx_waveform(byte, div, par_en, par_odd, stop2)
    assert len(expected) == length
    assert [sim.log[start + 1 + k].txd for k in range(length)] == expected
    assert sim.log[start].tx_busy == 0
    assert sim.log[start + 1].tx_busy == 1
    assert sim.log[start + length].tx_busy == 1, "last frame cycle"
    assert sim.log[start + length + 1].tx_busy == 0, "cycle after edge s+NP"
    assert sim.log[start + length + 1].txd == 1


@pytest.mark.parametrize("div", [0, 1, 2, 3, 4, 5, 6, 7, 8])
@pytest.mark.parametrize("par_en,par_odd", [(0, 0), (1, 0), (1, 1)])
@pytest.mark.parametrize("byte", [0x00, 0xFF, 0xA5, 0x01])
def test_rx_schedule_sweep(div, par_en, par_odd, byte):
    """SPEC 6: e = c + h + 9P (no parity) or c + h + 10P, with h = div >> 1."""
    sim = Sim()
    sim.apb_write(ADDR_BAUD, div)
    ctrl = RX_EN | (PAR_EN if par_en else 0) | (PAR_ODD if par_odd else 0)
    sim.apb_write(ADDR_CTRL, ctrl)
    sim.run_until(30)
    _, detect, stop_edge = _receive_one(sim, byte, div, par_en=par_en, par_odd=par_odd)
    assert detect == 32
    assert stop_edge == detect + (div >> 1) + (10 if par_en else 9) * (div + 1)
    sim.run_until(stop_edge + 6)

    assert EV_RX_START in sim.events[detect]
    assert sim.log[detect].rx_busy == 0
    assert sim.log[detect + 1].rx_busy == 1
    assert sim.log[stop_edge].rx_busy == 1
    assert sim.log[stop_edge + 1].rx_busy == 0
    assert EV_RX_PUSH in sim.events[stop_edge]
    assert sim.log[stop_edge].rx_count == 0
    assert sim.log[stop_edge + 1].rx_count == 1
    _, value, _ = sim.apb_read(ADDR_RXDATA)
    assert value == byte, "no parity or framing error on a clean frame"


@pytest.mark.parametrize("div", [2, 3, 4, 5, 6, 7, 8, 9, 10, 11])
def test_false_start_boundary_is_exactly_h_cycles(div):
    """SPEC 6: a low of h cycles is a false start; h + 1 cycles passes the check.

    The check at edge c + h samples s2, which is rxd from two cycles earlier, i.e.
    rxd in cycle x + h where x is the first low cycle.
    """
    half = div >> 1
    for low_cycles, expect_false_start in ((half, True), (half + 1, False)):
        sim = Sim()
        sim.apb_write(ADDR_BAUD, div)
        sim.apb_write(ADDR_CTRL, RX_EN)
        sim.run_until(30)
        start_cycle = sim.t
        sim.queue_rx_bits([0] * low_cycles)
        detect = start_cycle + 2
        check = detect + half
        sim.run_until(check + 4)
        assert EV_RX_START in sim.events[detect]
        assert (EV_RX_FALSE_START in sim.events[check]) is expect_false_start, (
            "div=%d, %d low cycles" % (div, low_cycles)
        )
        assert sim.log[check].rx_busy == 1
        assert sim.log[check + 1].rx_busy == (0 if expect_false_start else 1)


def test_last_events_is_cleared_every_step():
    """The event record is per-step, not cumulative."""
    sim = Sim()
    access = sim.apb_write(ADDR_TXDATA, 0x01)
    assert EV_APB_WRITE in sim.events[access]
    assert EV_TX_PUSH in sim.events[access]
    sim.idle(2)
    assert sim.events[access + 1] == set()
    assert sim.model.last_events == frozenset()
