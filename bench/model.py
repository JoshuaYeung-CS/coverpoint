"""Cycle-accurate reference model of the ``cp_uart`` device.

This module is written from ``docs/SPEC.md`` alone. Every method docstring names
the section of the specification it implements. The model is pure Python 3.11
standard library: integer arithmetic only, all masks explicit.

Usage contract (the bench relies on it):

    for each clock cycle:
        prdata, pready, pslverr = m.comb(psel, penable, pwrite, paddr, pwdata)
        txd, irq = m.txd, m.irq          # expected outputs *during* this cycle
        m.step(presetn, psel, penable, pwrite, paddr, pwdata, rxd)

``comb`` never changes state. ``step`` applies one rising edge: every condition
is evaluated against the pre-edge state and the pre-edge inputs, all next-state
values are computed, and only then is anything committed. Events at one edge
therefore never see each other (SPEC section 7).
"""

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

FIFO_DEPTH = 4  # SPEC 1: depth of both FIFOs.

# Register addresses (SPEC 4). All eight address bits are decoded.
ADDR_CTRL = 0x00
ADDR_BAUD = 0x04
ADDR_STATUS = 0x08
ADDR_TXDATA = 0x0C
ADDR_RXDATA = 0x10
ADDR_IRQ_EN = 0x14
ADDR_IRQ_STAT = 0x18

MAPPED_ADDRS = frozenset(
    (ADDR_CTRL, ADDR_BAUD, ADDR_STATUS, ADDR_TXDATA, ADDR_RXDATA, ADDR_IRQ_EN, ADDR_IRQ_STAT)
)
READ_ONLY_ADDRS = frozenset((ADDR_STATUS, ADDR_RXDATA))

# Write masks: bits not named in SPEC 4 read as 0 and ignore writes.
CTRL_MASK = 0x3F
BAUD_MASK = 0xFF
IRQ_MASK = 0x3F

# CTRL bit positions (SPEC 4.1).
CTRL_TX_EN = 0
CTRL_RX_EN = 1
CTRL_PAR_EN = 2
CTRL_PAR_ODD = 3
CTRL_LOOPBACK = 4
CTRL_STOP2 = 5

# IRQ_EN / IRQ_STAT bit masks (SPEC 4.6).
IRQ_TX_EMPTY_EV = 1 << 0
IRQ_RX_AVAIL_EV = 1 << 1
IRQ_RX_OVR = 1 << 2
IRQ_PERR_EV = 1 << 3
IRQ_FERR_EV = 1 << 4
IRQ_TX_OVF = 1 << 5

# RX FIFO entry layout (SPEC 4.5).
RX_ENTRY_PERR = 1 << 8
RX_ENTRY_FERR = 1 << 9

# --------------------------------------------------------------------------
# Event names recorded in ``UartModel.last_events`` (one per line, documented)
# --------------------------------------------------------------------------

EV_TX_PUSH = "tx_push"
"""A completed TXDATA write was accepted onto the TX FIFO."""

EV_TX_PUSH_DROPPED = "tx_push_dropped"
"""A completed TXDATA write was discarded because the pre-edge TX count was 4."""

EV_TX_POP = "tx_pop"
"""The transmitter popped the head of the TX FIFO to begin a frame."""

EV_TX_FRAME_START = "tx_frame_start"
"""A transmit frame began at this edge (this edge is `s` of SPEC 5)."""

EV_TX_FRAME_BACK_TO_BACK = "tx_frame_back_to_back"
"""The frame that began at this edge started at the previous frame's `s + NP`."""

EV_RX_START = "rx_start"
"""The receiver detected a start bit at this edge (this edge is `c` of SPEC 6)."""

EV_RX_FALSE_START = "rx_false_start"
"""The start check at edge `c + h` saw s2 = 1, so the frame was abandoned."""

EV_RX_PUSH = "rx_push"
"""A completed receive frame was pushed onto the RX FIFO."""

EV_RX_OVERRUN = "rx_overrun"
"""A completed receive frame was discarded because the pre-edge RX count was 4."""

EV_RX_PERR = "rx_perr"
"""A frame finished reception with a parity error (whether or not it was pushed)."""

EV_RX_FERR = "rx_ferr"
"""A frame finished reception with a framing error (whether or not it was pushed)."""

EV_RX_POP = "rx_pop"
"""A completed RXDATA read popped the head of the RX FIFO."""

EV_RX_POP_EMPTY = "rx_pop_empty"
"""A completed RXDATA read found the pre-edge RX count at 0, so nothing was popped."""

EV_APB_WRITE = "apb_write"
"""A non-error APB write transfer completed at this edge."""

EV_APB_READ = "apb_read"
"""A non-error APB read transfer completed at this edge."""

EV_APB_ERROR = "apb_error"
"""An APB transfer completed at this edge and was an error (no side effects)."""

EV_IRQ_CLEAR_LOST_TO_SET = "irq_clear_lost_to_set"
"""An IRQ_STAT write-1-to-clear and a hardware set hit the same bit at this edge."""

ALL_EVENTS = frozenset(
    (
        EV_TX_PUSH,
        EV_TX_PUSH_DROPPED,
        EV_TX_POP,
        EV_TX_FRAME_START,
        EV_TX_FRAME_BACK_TO_BACK,
        EV_RX_START,
        EV_RX_FALSE_START,
        EV_RX_PUSH,
        EV_RX_OVERRUN,
        EV_RX_PERR,
        EV_RX_FERR,
        EV_RX_POP,
        EV_RX_POP_EMPTY,
        EV_APB_WRITE,
        EV_APB_READ,
        EV_APB_ERROR,
        EV_IRQ_CLEAR_LOST_TO_SET,
    )
)


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def _xor8(byte: int) -> int:
    """XOR of the eight bits of ``byte`` (SPEC 5 parity slot, SPEC 6 perr)."""
    value = byte & 0xFF
    acc = 0
    for index in range(8):
        acc ^= (value >> index) & 1
    return acc


def _frame_bit(slot: int, byte: int, par_en: int, par_odd: int) -> int:
    """Value of ``txd`` in transmit frame slot ``slot`` (SPEC 5, frame layout).

    Slot 0 is the start bit, slots 1..8 are data bits 0..7 (LSB first), slot 9 is
    the parity bit when ``par_en`` is set, and every remaining slot is a stop bit.
    """
    if slot == 0:
        return 0
    if 1 <= slot <= 8:
        return (byte >> (slot - 1)) & 1
    if par_en and slot == 9:
        # Even parity is the XOR of the eight data bits; odd parity is its inverse.
        return _xor8(byte) ^ (par_odd & 1)
    return 1


# --------------------------------------------------------------------------
# The model
# --------------------------------------------------------------------------


class UartModel:
    """Reference model of ``cp_uart``.

    All public state is exposed through read-only properties so that a coverage
    collector never has to reach into private attributes.
    """

    def __init__(self) -> None:
        """Bring the model up in the reset state (SPEC 8)."""
        self.reset()

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Force every state element to its reset value (SPEC 8).

        ``CTRL = BAUD = IRQ_EN = IRQ_STAT = 0``, both FIFOs empty, ``txd = 1``,
        ``s1 = s2 = 1``, transmitter and receiver idle, all counters and captured
        frame parameters 0.
        """
        # Registers.
        self._ctrl = 0
        self._baud = 0
        self._irq_en = 0
        self._irq_stat = 0

        # FIFOs. The RX FIFO holds 10-bit entries {ferr, perr, data}.
        self._tx_fifo: list[int] = []
        self._rx_fifo: list[int] = []

        # Serial pins and the two-flop synchroniser (SPEC 6, input path).
        self._txd = 1
        self._s1 = 1
        self._s2 = 1

        # Transmitter (SPEC 5). ``_tx_t`` counts edges since the frame start edge
        # ``s``: it is 0 in the cycle after edge ``s`` and ``j`` after edge ``s+j``.
        self._tx_active = False
        self._tx_t = 0
        self._tx_byte = 0
        self._tx_p = 0
        self._tx_slots = 0
        self._tx_par_en = 0
        self._tx_par_odd = 0
        self._tx_stop2 = 0

        # Receiver (SPEC 6). ``_rx_off`` is the offset from the start-detect edge
        # ``c`` of the most recent edge: it is 0 in the cycle after edge ``c``.
        self._rx_active = False
        self._rx_off = 0
        self._rx_p = 0
        self._rx_h = 0
        self._rx_par_en = 0
        self._rx_par_odd = 0
        self._rx_data = 0
        self._rx_perr = 0

        self._last_events: set[str] = set()

    # ------------------------------------------------------------------
    # Combinational outputs
    # ------------------------------------------------------------------

    @staticmethod
    def _is_error(pwrite: int, addr: int) -> bool:
        """True when the access is an APB error (SPEC 3).

        An access is an error when ``paddr`` is not one of the seven mapped
        addresses (all eight bits decoded) or when it writes a read-only register
        (``STATUS``, ``RXDATA``). A read of ``TXDATA`` is not an error.
        """
        if addr not in MAPPED_ADDRS:
            return True
        return bool(pwrite) and addr in READ_ONLY_ADDRS

    def _read_value(self, addr: int) -> int:
        """Read value of the register at ``addr``, from the current state (SPEC 4)."""
        if addr == ADDR_CTRL:
            return self._ctrl & CTRL_MASK
        if addr == ADDR_BAUD:
            return self._baud & BAUD_MASK
        if addr == ADDR_STATUS:
            return self._status_value()
        if addr == ADDR_TXDATA:
            # Write-only, reads 0 — and a read of TXDATA is not an error.
            return 0
        if addr == ADDR_RXDATA:
            if not self._rx_fifo:
                return 0
            return self._rx_fifo[0] & 0x3FF
        if addr == ADDR_IRQ_EN:
            return self._irq_en & IRQ_MASK
        if addr == ADDR_IRQ_STAT:
            return self._irq_stat & IRQ_MASK
        return 0

    def _status_value(self) -> int:
        """Assemble the ``STATUS`` read value from the current state (SPEC 4.3)."""
        tx_count = len(self._tx_fifo)
        rx_count = len(self._rx_fifo)
        value = 0
        if tx_count == 0:
            value |= 1 << 0  # tx_empty
        if tx_count == FIFO_DEPTH:
            value |= 1 << 1  # tx_full
        if rx_count == 0:
            value |= 1 << 2  # rx_empty
        if rx_count == FIFO_DEPTH:
            value |= 1 << 3  # rx_full
        if self._tx_active:
            value |= 1 << 4  # tx_busy
        if self._rx_active:
            value |= 1 << 5  # rx_busy
        value |= (tx_count & 0x7) << 8
        value |= (rx_count & 0x7) << 12
        return value

    def comb(self, psel: int, penable: int, pwrite: int, paddr: int, pwdata: int):
        """Combinational APB outputs for these inputs and the current state (SPEC 3).

        Returns ``(prdata, pready, pslverr)``. ``pready`` is constant 1. ``prdata``
        is the selected register's read value when ``psel = 1`` and ``pwrite = 0``,
        and 0 when ``psel = 0``, ``pwrite = 1`` or the read is an error. ``pslverr``
        is 1 exactly when ``psel = 1``, ``penable = 1`` and the access is an error.

        This method must not change state.
        """
        psel = 1 if psel else 0
        penable = 1 if penable else 0
        pwrite = 1 if pwrite else 0
        addr = paddr & 0xFF

        error = self._is_error(pwrite, addr)
        pready = 1
        pslverr = 1 if (psel and penable and error) else 0

        if psel == 0 or pwrite == 1 or error:
            prdata = 0
        else:
            prdata = self._read_value(addr)

        return (prdata & 0xFFFFFFFF, pready, pslverr)

    # ------------------------------------------------------------------
    # Registered / state-only outputs
    # ------------------------------------------------------------------

    @property
    def txd(self) -> int:
        """Registered serial output for the current cycle (SPEC 5). Idles at 1."""
        return self._txd

    @property
    def irq(self) -> int:
        """``irq = 1`` exactly when ``(IRQ_STAT & IRQ_EN) != 0`` (SPEC 4.6)."""
        return 1 if (self._irq_stat & self._irq_en & IRQ_MASK) else 0

    # ------------------------------------------------------------------
    # Read-only introspection for the coverage collector
    # ------------------------------------------------------------------

    @property
    def tx_count(self) -> int:
        """Number of bytes in the TX FIFO, 0 to 4 (SPEC 4.3)."""
        return len(self._tx_fifo)

    @property
    def rx_count(self) -> int:
        """Number of entries in the RX FIFO, 0 to 4 (SPEC 4.3)."""
        return len(self._rx_fifo)

    @property
    def tx_busy(self) -> int:
        """1 in the cycles after edges ``s`` … ``s + NP - 1`` of any frame (SPEC 5)."""
        return 1 if self._tx_active else 0

    @property
    def rx_busy(self) -> int:
        """1 in the cycles after edges ``c`` … ``e - 1`` of a frame (SPEC 6)."""
        return 1 if self._rx_active else 0

    @property
    def ctrl(self) -> int:
        """Current ``CTRL`` register value (SPEC 4.1)."""
        return self._ctrl & CTRL_MASK

    @property
    def baud(self) -> int:
        """Current ``BAUD`` register value, i.e. ``div`` (SPEC 4.2)."""
        return self._baud & BAUD_MASK

    @property
    def irq_en(self) -> int:
        """Current ``IRQ_EN`` register value (SPEC 4.6)."""
        return self._irq_en & IRQ_MASK

    @property
    def irq_stat(self) -> int:
        """Current ``IRQ_STAT`` register value (SPEC 4.6)."""
        return self._irq_stat & IRQ_MASK

    @property
    def last_tx_byte(self) -> int:
        """Byte loaded by the most recent frame start (for coverage only)."""
        return self._tx_byte

    @property
    def last_rx_byte(self) -> int:
        """Data bits of the frame most recently received, pushed or not (for coverage only)."""
        return self._rx_data

    @property
    def last_events(self) -> frozenset:
        """Events recorded during the most recent :meth:`step` call."""
        return frozenset(self._last_events)

    # ------------------------------------------------------------------
    # The clock edge
    # ------------------------------------------------------------------

    def step(self, presetn, psel, penable, pwrite, paddr, pwdata, rxd) -> None:
        """Apply one rising edge of ``pclk``. All arguments are pre-edge values.

        SPEC 1: at an edge whose pre-edge ``presetn`` is 0 every state element
        takes its reset value and nothing else happens at that edge.

        SPEC 7: everything below is evaluated against the pre-edge snapshot taken
        at the top of the method, so events at this edge do not see each other.
        Next-state values are accumulated in locals and committed in one block at
        the end.
        """
        if not presetn:
            self.reset()
            # No events are recorded on a reset edge: SPEC 1 says nothing else in
            # the document happens at that edge.
            return

        events: set[str] = set()

        # ---------------- pre-edge snapshot (SPEC 1, SPEC 7) ----------------
        ctrl = self._ctrl
        baud = self._baud
        tx_en = (ctrl >> CTRL_TX_EN) & 1
        rx_en = (ctrl >> CTRL_RX_EN) & 1
        par_en = (ctrl >> CTRL_PAR_EN) & 1
        par_odd = (ctrl >> CTRL_PAR_ODD) & 1
        loopback = (ctrl >> CTRL_LOOPBACK) & 1
        stop2 = (ctrl >> CTRL_STOP2) & 1

        txd_pre = self._txd
        s1_pre = self._s1
        s2_pre = self._s2

        tx_fifo_pre = list(self._tx_fifo)
        rx_fifo_pre = list(self._rx_fifo)
        tx_count_pre = len(tx_fifo_pre)
        rx_count_pre = len(rx_fifo_pre)

        tx_active_pre = self._tx_active
        tx_t_pre = self._tx_t
        rx_active_pre = self._rx_active
        rx_off_pre = self._rx_off

        irq_stat_pre = self._irq_stat
        irq_en_pre = self._irq_en

        # ---------------- APB decode (SPEC 3) ----------------
        psel = 1 if psel else 0
        penable = 1 if penable else 0
        pwrite = 1 if pwrite else 0
        addr = paddr & 0xFF
        wdata = pwdata & 0xFFFFFFFF

        completed = psel == 1 and penable == 1
        error = self._is_error(pwrite, addr)
        if completed:
            if error:
                # SPEC 3: an error access has no side effects at all.
                events.add(EV_APB_ERROR)
            elif pwrite:
                events.add(EV_APB_WRITE)
            else:
                events.add(EV_APB_READ)

        do_write = completed and not error and pwrite == 1
        do_read = completed and not error and pwrite == 0

        ctrl_next = ctrl
        baud_next = baud
        irq_en_next = irq_en_pre
        clear_mask = 0
        tx_push_req = False
        tx_push_byte = 0
        rx_pop_req = False

        if do_write:
            if addr == ADDR_CTRL:
                ctrl_next = wdata & CTRL_MASK
            elif addr == ADDR_BAUD:
                baud_next = wdata & BAUD_MASK
            elif addr == ADDR_TXDATA:
                tx_push_req = True
                tx_push_byte = wdata & 0xFF
            elif addr == ADDR_IRQ_EN:
                irq_en_next = wdata & IRQ_MASK
            elif addr == ADDR_IRQ_STAT:
                clear_mask = wdata & IRQ_MASK
        if do_read and addr == ADDR_RXDATA:
            rx_pop_req = True

        # Bits that hardware sets in IRQ_STAT at this edge (SPEC 4.6).
        set_mask = 0

        # ---------------- TX FIFO push (SPEC 4.4) ----------------
        # Decided on the pre-edge count, even if the transmitter pops at this edge.
        tx_push_ok = False
        if tx_push_req:
            if tx_count_pre < FIFO_DEPTH:
                tx_push_ok = True
                events.add(EV_TX_PUSH)
            else:
                events.add(EV_TX_PUSH_DROPPED)
                set_mask |= IRQ_TX_OVF

        # ---------------- RX FIFO pop (SPEC 4.5) ----------------
        # Decided on the pre-edge count, even if the receiver pushes at this edge.
        rx_pop_ok = False
        if rx_pop_req:
            if rx_count_pre > 0:
                rx_pop_ok = True
                events.add(EV_RX_POP)
            else:
                events.add(EV_RX_POP_EMPTY)

        # ---------------- Transmitter (SPEC 5) ----------------
        tx_active_next = tx_active_pre
        tx_t_next = tx_t_pre
        tx_byte_next = self._tx_byte
        tx_p_next = self._tx_p
        tx_slots_next = self._tx_slots
        tx_par_en_next = self._tx_par_en
        tx_par_odd_next = self._tx_par_odd
        tx_stop2_next = self._tx_stop2

        # The frame occupies the cycles after edges s … s + NP - 1, so the edge at
        # which the transmitter becomes available again (s + NP) is the edge whose
        # pre-edge _tx_t is NP - 1.
        frame_edges = self._tx_slots * self._tx_p
        tx_ending = tx_active_pre and tx_t_pre == frame_edges - 1
        tx_available = (not tx_active_pre) or tx_ending

        tx_pop_ok = False
        if tx_available and tx_en and tx_count_pre > 0:
            # Frame start: pop the head and capture the frame parameters from their
            # pre-edge values (a CTRL/BAUD write at this edge is not seen).
            tx_pop_ok = True
            events.add(EV_TX_POP)
            events.add(EV_TX_FRAME_START)
            if tx_ending:
                events.add(EV_TX_FRAME_BACK_TO_BACK)
            tx_byte_next = tx_fifo_pre[0] & 0xFF
            tx_p_next = (baud & BAUD_MASK) + 1
            tx_par_en_next = par_en
            tx_par_odd_next = par_odd
            tx_stop2_next = stop2
            tx_slots_next = 10 + par_en + stop2
            tx_active_next = True
            tx_t_next = 0
            txd_next = _frame_bit(0, tx_byte_next, tx_par_en_next, tx_par_odd_next)
        elif tx_active_pre and not tx_ending:
            # Continue the frame in flight; parameters are fixed for the frame.
            tx_active_next = True
            tx_t_next = tx_t_pre + 1
            txd_next = _frame_bit(
                tx_t_next // self._tx_p, self._tx_byte, self._tx_par_en, self._tx_par_odd
            )
        else:
            # Idle (or the frame just ended and no new one starts): txd idles at 1.
            tx_active_next = False
            tx_t_next = 0
            txd_next = 1

        # tx_empty_ev: pre-edge count 1, the transmitter pops, no push accepted.
        if tx_pop_ok and tx_count_pre == 1 and not tx_push_ok:
            set_mask |= IRQ_TX_EMPTY_EV

        # ---------------- Receiver (SPEC 6) ----------------
        rx_active_next = rx_active_pre
        rx_off_next = rx_off_pre
        rx_p_next = self._rx_p
        rx_h_next = self._rx_h
        rx_par_en_next = self._rx_par_en
        rx_par_odd_next = self._rx_par_odd
        rx_data_next = self._rx_data
        rx_perr_next = self._rx_perr
        rx_push_entry = None

        if rx_active_pre:
            # This edge is c + m, where the pre-edge _rx_off is m - 1.
            offset = rx_off_pre + 1
            rx_off_next = offset
            period = self._rx_p
            half = self._rx_h
            frame_par_en = self._rx_par_en
            frame_par_odd = self._rx_par_odd
            stop_offset = half + (10 if frame_par_en else 9) * period

            if half > 0 and offset == half:
                # Start check. With h = 0 the check is edge c itself and always
                # passes, so there is nothing to do in that case.
                if s2_pre == 1:
                    events.add(EV_RX_FALSE_START)
                    rx_active_next = False
                    rx_off_next = 0
            elif half + period <= offset <= half + 8 * period and (offset - half) % period == 0:
                # Data bit k at edge c + h + (k+1)P, LSB first.
                bit_index = (offset - half) // period - 1
                rx_data_next = (self._rx_data | ((s2_pre & 1) << bit_index)) & 0xFF
            elif frame_par_en and offset == half + 9 * period:
                # perr = 1 when (XOR of the data bits) XOR (parity sample) differs
                # from par_odd.
                combined = (_xor8(self._rx_data) ^ (s2_pre & 1)) & 1
                rx_perr_next = 1 if combined != frame_par_odd else 0
            elif offset == stop_offset:
                # Stop sample: the frame completes at this edge (SPEC 6, completion).
                ferr = 0 if s2_pre else 1
                # perr was latched at the parity edge; without parity it is 0.
                perr = self._rx_perr if frame_par_en else 0
                entry = ((ferr & 1) * RX_ENTRY_FERR) | ((perr & 1) * RX_ENTRY_PERR)
                entry |= self._rx_data & 0xFF

                if rx_count_pre < FIFO_DEPTH:
                    rx_push_entry = entry
                    events.add(EV_RX_PUSH)
                    set_mask |= IRQ_RX_AVAIL_EV
                else:
                    events.add(EV_RX_OVERRUN)
                    set_mask |= IRQ_RX_OVR

                if perr:
                    events.add(EV_RX_PERR)
                    set_mask |= IRQ_PERR_EV
                if ferr:
                    events.add(EV_RX_FERR)
                    set_mask |= IRQ_FERR_EV

                # Idle from this edge on, so a new start can be detected at e + 1.
                rx_active_next = False
                rx_off_next = 0
        else:
            # Start detection: receiver idle, pre-edge rx_en = 1 and pre-edge s2 = 0.
            if rx_en and s2_pre == 0:
                events.add(EV_RX_START)
                div = baud & BAUD_MASK
                rx_active_next = True
                rx_off_next = 0
                rx_p_next = div + 1
                rx_h_next = div >> 1
                rx_par_en_next = par_en
                rx_par_odd_next = par_odd
                rx_data_next = 0
                rx_perr_next = 0

        # ---------------- FIFO updates (SPEC 4.4, 4.5, 7) ----------------
        tx_fifo_next = list(tx_fifo_pre)
        if tx_pop_ok:
            tx_fifo_next.pop(0)
        if tx_push_ok:
            tx_fifo_next.append(tx_push_byte)

        rx_fifo_next = list(rx_fifo_pre)
        if rx_pop_ok:
            rx_fifo_next.pop(0)
        if rx_push_entry is not None:
            rx_fifo_next.append(rx_push_entry)

        # ---------------- IRQ_STAT (SPEC 4.6, 7: set wins over W1C) -----------
        if clear_mask & set_mask:
            events.add(EV_IRQ_CLEAR_LOST_TO_SET)
        irq_stat_next = ((irq_stat_pre & ~clear_mask) | set_mask) & IRQ_MASK

        # ---------------- Input synchroniser (SPEC 6, input path) -------------
        # rx_in selects txd's pre-edge value in loopback, using the pre-edge
        # loopback bit; both synchroniser flops take pre-edge values.
        rx_in = txd_pre if loopback else (1 if rxd else 0)
        s1_next = rx_in & 1
        s2_next = s1_pre & 1

        # ---------------- Commit ----------------
        self._ctrl = ctrl_next
        self._baud = baud_next
        self._irq_en = irq_en_next
        self._irq_stat = irq_stat_next

        self._tx_fifo = tx_fifo_next
        self._rx_fifo = rx_fifo_next

        self._txd = txd_next
        self._s1 = s1_next
        self._s2 = s2_next

        self._tx_active = tx_active_next
        self._tx_t = tx_t_next
        self._tx_byte = tx_byte_next
        self._tx_p = tx_p_next
        self._tx_slots = tx_slots_next
        self._tx_par_en = tx_par_en_next
        self._tx_par_odd = tx_par_odd_next
        self._tx_stop2 = tx_stop2_next

        self._rx_active = rx_active_next
        self._rx_off = rx_off_next
        self._rx_p = rx_p_next
        self._rx_h = rx_h_next
        self._rx_par_en = rx_par_en_next
        self._rx_par_odd = rx_par_odd_next
        self._rx_data = rx_data_next
        self._rx_perr = rx_perr_next

        self._last_events = events
