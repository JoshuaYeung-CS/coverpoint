"""The two agents: APB (driver + monitor) and UART (rxd driver + txd monitor).

Timing rule for every coroutine that touches a pin: drive on the falling edge, sample
after ReadOnly in that same half-cycle. By then the combinational outputs have settled on
exactly what the device will see at the coming rising edge. Nothing is ever assigned
after ReadOnly.
"""
import cocotb
from cocotb.triggers import FallingEdge, ReadOnly
from pyuvm import uvm_agent, uvm_analysis_port, uvm_driver, uvm_monitor, uvm_sequencer

from . import regs


class ApbDriver(uvm_driver):
    """Drives one transfer per item. The loop is per clock cycle, so an item with
    idle == 0 that is already waiting starts its setup phase in the cycle right after the
    previous access phase (a back-to-back transfer); otherwise the bus goes idle."""

    def build_phase(self):
        self.dut = cocotb.top

    async def run_phase(self):
        d = self.dut
        item, idle_left = None, 0
        while True:
            await FallingEdge(d.pclk)
            if item is None:
                ok, item = self.seq_item_port.try_next_item()
                if not ok:
                    item = None
                else:
                    idle_left = item.idle
            if item is None or idle_left > 0:
                d.psel.value = 0
                d.penable.value = 0
                idle_left -= 1
                continue
            d.psel.value = 1                               # setup phase
            d.penable.value = 0
            d.pwrite.value = int(item.write)
            d.paddr.value = item.addr
            d.pwdata.value = item.data
            await FallingEdge(d.pclk)                      # access phase
            d.penable.value = 1
            await ReadOnly()
            item.rdata = int(d.prdata.value)
            item.slverr = int(d.pslverr.value)
            self.seq_item_port.item_done()
            item = None


class ApbMonitor(uvm_monitor):
    """Publishes every completed transfer as (cycle, write, addr, wdata, rdata, slverr)."""

    def build_phase(self):
        self.dut = cocotb.top
        self.ap = uvm_analysis_port("ap", self)

    async def run_phase(self):
        d = self.dut
        cycle = 0
        while True:
            await FallingEdge(d.pclk)
            await ReadOnly()
            if int(d.psel.value) and int(d.penable.value):
                self.ap.write((cycle, int(d.pwrite.value), int(d.paddr.value), int(d.pwdata.value),
                               int(d.prdata.value), int(d.pslverr.value)))
            cycle += 1


class ApbAgent(uvm_agent):
    def build_phase(self):
        self.seqr = uvm_sequencer("seqr", self)
        self.driver = ApbDriver("driver", self)
        self.monitor = ApbMonitor("monitor", self)

    def connect_phase(self):
        self.driver.seq_item_port.connect(self.seqr.seq_item_export)


class RxDriver(uvm_driver):
    """Drives frames (or glitches) onto rxd. The line idles at 1."""

    def build_phase(self):
        self.dut = cocotb.top

    async def run_phase(self):
        d = self.dut
        while True:
            item = await self.seq_item_port.get_next_item()
            for _ in range(item.gap):
                await FallingEdge(d.pclk)
                d.rxd.value = 1
            width = item.glitch if item.glitch else item.period
            for bit in item.bits():
                for _ in range(width):
                    await FallingEdge(d.pclk)
                    d.rxd.value = bit
            if item.glitch or item.bad_stop:
                await FallingEdge(d.pclk)
                d.rxd.value = 1
            self.seq_item_port.item_done()


class TxMonitor(uvm_monitor):
    """Decodes frames off txd for the transaction log and for coverage. It is told the
    line settings by whoever programs the device (the `line` dict in the config db), the
    way a real UART monitor is. It makes no pass/fail decision: the scoreboard does."""

    def build_phase(self):
        self.dut = cocotb.top
        self.ap = uvm_analysis_port("ap", self)
        self.line = {"period": 1, "parity": None}

    async def run_phase(self):
        d = self.dut
        while True:
            await FallingEdge(d.pclk)
            await ReadOnly()
            if int(d.txd.value) == 1:
                continue
            period, parity = self.line["period"], self.line["parity"]
            nbits = 9 + (parity is not None)
            samples = []
            for _ in range(nbits):
                for _ in range(period):
                    await FallingEdge(d.pclk)
                await ReadOnly()
                samples.append(int(d.txd.value))
            byte = sum(b << k for k, b in enumerate(samples[:8]))
            self.ap.write({"byte": byte, "parity_bit": samples[8] if parity else None, "stop": samples[-1]})


class UartAgent(uvm_agent):
    def build_phase(self):
        self.seqr = uvm_sequencer("seqr", self)
        self.driver = RxDriver("driver", self)
        self.monitor = TxMonitor("monitor", self)

    def connect_phase(self):
        self.driver.seq_item_port.connect(self.seqr.seq_item_export)


__all__ = ["ApbAgent", "UartAgent", "regs"]
