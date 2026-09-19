"""The functional coverage model (cocotb-coverage).

Coverage is sampled from the reference model, which is stepped with the device's real
pin values, so it records what the stimulus made the specified behaviour do. It is
collected on the unmutated design only: it measures the stimulus, not the device.

Every bin is a behaviour docs/SPEC.md singles out. The list is part of the
pre-registration: it was fixed before any confirmatory mutant was scored.
"""
from cocotb_coverage.coverage import CoverPoint, coverage_db

from bench import model as M

from . import regs

REG_BINS = [(a, w) for a in regs.MAPPED for w in (0, 1)]
PARITY = ("none", "even", "odd")
DIV_BINS = ("0", "1", "2-3", "4-15", "16-255")
BYTE_BINS = ("00", "ff", "55", "aa", "other")
CORNERS = ("tx_push_and_pop", "rx_push_and_pop", "tx_overflow_and_pop", "rx_overrun_and_pop",
           "rx_pop_empty_and_push", "irq_set_wins_over_clear")
MIDFRAME = ("ctrl_write_tx_busy", "ctrl_write_rx_busy", "baud_write_tx_busy", "baud_write_rx_busy",
            "tx_en_cleared_tx_busy", "rx_en_cleared_rx_busy", "reset_tx_busy", "reset_rx_busy")


def div_bin(div):
    return "0" if div == 0 else "1" if div == 1 else "2-3" if div <= 3 else "4-15" if div <= 15 else "16-255"


def byte_bin(b):
    return {0x00: "00", 0xFF: "ff", 0x55: "55", 0xAA: "aa"}.get(b, "other")


def parity_of(ctrl):
    if not ctrl & regs.PAR_EN:
        return "none"
    return "odd" if ctrl & regs.PAR_ODD else "even"


@CoverPoint("cp.apb.access", xf=lambda a, w: (a, w), bins=REG_BINS)
def s_apb_access(a, w): pass


@CoverPoint("cp.apb.unmapped", xf=lambda w: w, bins=[0, 1])
def s_apb_unmapped(w): pass


@CoverPoint("cp.apb.gap", xf=lambda g: "0" if g == 0 else "1" if g == 1 else "2-5" if g <= 5 else "6+",
            bins=["0", "1", "2-5", "6+"])
def s_apb_gap(g): pass


@CoverPoint("cp.tx.level_at_write", xf=lambda n: n, bins=[0, 1, 2, 3, 4])
def s_tx_level(n): pass


@CoverPoint("cp.rx.level_at_frame_end", xf=lambda n: n, bins=[0, 1, 2, 3, 4])
def s_rx_level(n): pass


@CoverPoint("cp.tx.format", xf=lambda p, s2: (p, s2), bins=[(p, s) for p in PARITY for s in (0, 1)])
def s_tx_format(p, s2): pass


@CoverPoint("cp.tx.div", xf=lambda d: d, bins=list(DIV_BINS))
def s_tx_div(d): pass


@CoverPoint("cp.tx.byte", xf=lambda b: b, bins=list(BYTE_BINS))
def s_tx_byte(b): pass


@CoverPoint("cp.tx.start", xf=lambda k: k, bins=["from_idle", "back_to_back"])
def s_tx_start(k): pass


@CoverPoint("cp.rx.outcome", xf=lambda p, o: (p, o),
            bins=[(p, o) for p in PARITY for o in ("ok", "perr", "ferr", "both") if not (p == "none" and o in ("perr", "both"))])
def s_rx_outcome(p, o): pass


@CoverPoint("cp.rx.div", xf=lambda d: d, bins=list(DIV_BINS))
def s_rx_div(d): pass


@CoverPoint("cp.rx.byte", xf=lambda b: b, bins=list(BYTE_BINS))
def s_rx_byte(b): pass


@CoverPoint("cp.rx.source", xf=lambda s: s, bins=["pin", "loopback"])
def s_rx_source(s): pass


@CoverPoint("cp.rx.false_start", xf=lambda x: x, bins=[1])
def s_rx_false_start(x): pass


@CoverPoint("cp.rx.read_empty", xf=lambda x: x, bins=[1])
def s_rx_read_empty(x): pass


@CoverPoint("cp.irq.raised", xf=lambda n: n, bins=list(regs.IRQ_NAMES))
def s_irq_raised(n): pass


@CoverPoint("cp.irq.cleared", xf=lambda n: n, bins=list(regs.IRQ_NAMES))
def s_irq_cleared(n): pass


@CoverPoint("cp.corner", xf=lambda n: n, bins=list(CORNERS))
def s_corner(n): pass


@CoverPoint("cp.midframe", xf=lambda n: n, bins=list(MIDFRAME))
def s_midframe(n): pass


class Coverage:
    """Listens to the scoreboard's model after every step and samples the coverpoints."""

    def __init__(self, env):
        self.prev = None                 # model state before the edge just taken
        self.rx_cfg = (0, 0)             # (ctrl, baud) captured when the frame in flight started
        self.last_access_cycle = None
        self.timeline = []               # (cycle, bins hit) each time the count rises
        self.hit = 0
        env.sb.listeners.append(self.sample)

    @staticmethod
    def snapshot(m):
        return {"ctrl": m.ctrl, "baud": m.baud, "tx_count": m.tx_count, "rx_count": m.rx_count,
                "tx_busy": m.tx_busy, "rx_busy": m.rx_busy, "irq_en": m.irq_en, "irq_stat": m.irq_stat}

    def sample(self, m, ins, cycle):
        presetn, psel, penable, pwrite, paddr, pwdata, _rxd = ins
        prev, ev = self.prev, m.last_events
        self.prev = self.snapshot(m)
        if prev is None:
            return
        if not presetn:
            if prev["tx_busy"]:
                s_midframe("reset_tx_busy")
            if prev["rx_busy"]:
                s_midframe("reset_rx_busy")
            return

        if psel and penable:
            if paddr in regs.MAPPED:
                s_apb_access(paddr, pwrite)
            else:
                s_apb_unmapped(pwrite)
            if self.last_access_cycle is not None:
                s_apb_gap(cycle - self.last_access_cycle - 2)
            self.last_access_cycle = cycle
            if pwrite and paddr == regs.TXDATA:
                s_tx_level(prev["tx_count"])
            if pwrite and paddr in (regs.CTRL, regs.BAUD):
                which = "ctrl" if paddr == regs.CTRL else "baud"
                if prev["tx_busy"]:
                    s_midframe(f"{which}_write_tx_busy")
                if prev["rx_busy"]:
                    s_midframe(f"{which}_write_rx_busy")
                if paddr == regs.CTRL:
                    if prev["tx_busy"] and prev["ctrl"] & regs.TX_EN and not pwdata & regs.TX_EN:
                        s_midframe("tx_en_cleared_tx_busy")
                    if prev["rx_busy"] and prev["ctrl"] & regs.RX_EN and not pwdata & regs.RX_EN:
                        s_midframe("rx_en_cleared_rx_busy")
            if pwrite and paddr == regs.IRQ_STAT:
                for i, name in enumerate(regs.IRQ_NAMES):
                    if (prev["irq_stat"] >> i) & 1 and (pwdata >> i) & 1 and not (m.irq_stat >> i) & 1:
                        s_irq_cleared(name)

        if M.EV_TX_FRAME_START in ev:
            s_tx_format(parity_of(prev["ctrl"]), 1 if prev["ctrl"] & regs.STOP2 else 0)
            s_tx_div(div_bin(prev["baud"]))
            s_tx_byte(byte_bin(m.last_tx_byte))
            s_tx_start("back_to_back" if M.EV_TX_FRAME_BACK_TO_BACK in ev else "from_idle")
        if M.EV_RX_START in ev:
            self.rx_cfg = (prev["ctrl"], prev["baud"])
        if M.EV_RX_FALSE_START in ev:
            s_rx_false_start(1)
        if M.EV_RX_PUSH in ev or M.EV_RX_OVERRUN in ev:
            ctrl, baud = self.rx_cfg
            perr, ferr = M.EV_RX_PERR in ev, M.EV_RX_FERR in ev
            s_rx_outcome(parity_of(ctrl), "both" if perr and ferr else "perr" if perr else "ferr" if ferr else "ok")
            s_rx_div(div_bin(baud))
            s_rx_byte(byte_bin(m.last_rx_byte))
            s_rx_source("loopback" if ctrl & regs.LOOPBACK else "pin")
            s_rx_level(prev["rx_count"])
        if M.EV_RX_POP_EMPTY in ev:
            s_rx_read_empty(1)

        raised = (m.irq_stat & m.irq_en) & ~(prev["irq_stat"] & prev["irq_en"])
        for i, name in enumerate(regs.IRQ_NAMES):
            if (raised >> i) & 1:
                s_irq_raised(name)

        if M.EV_TX_PUSH in ev and M.EV_TX_POP in ev:
            s_corner("tx_push_and_pop")
        if M.EV_RX_PUSH in ev and M.EV_RX_POP in ev:
            s_corner("rx_push_and_pop")
        if M.EV_TX_PUSH_DROPPED in ev and M.EV_TX_POP in ev:
            s_corner("tx_overflow_and_pop")
        if M.EV_RX_OVERRUN in ev and M.EV_RX_POP in ev:
            s_corner("rx_overrun_and_pop")
        if M.EV_RX_POP_EMPTY in ev and M.EV_RX_PUSH in ev:
            s_corner("rx_pop_empty_and_push")
        if M.EV_IRQ_CLEAR_LOST_TO_SET in ev:
            s_corner("irq_set_wins_over_clear")

        hit = self.bins_hit()
        if hit > self.hit:
            self.hit = hit
            self.timeline.append((cycle, hit))

    @staticmethod
    def _points():
        # Leaf coverpoints only: the database also holds their parent scopes ("cp", "cp.tx").
        return [coverage_db[n] for n in coverage_db if n.startswith("cp.") and isinstance(coverage_db[n], CoverPoint)]

    def bins_hit(self):
        return sum(p.coverage for p in self._points())

    def report(self):
        points = self._points()
        return {
            "bins": sum(p.size for p in points), "hit": sum(p.coverage for p in points),
            "timeline": self.timeline,
            "missed": sorted(f"{p._name}:{b}" for p in points for b, n in p.detailed_coverage.items() if n == 0),
        }
