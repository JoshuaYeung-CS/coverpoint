# cp_uart — device specification

This is the contract. The RTL (`rtl/`) and the Python reference model (`bench/model.py`)
are each written from this document and not from each other. Where the two disagree, this
document decides, and if it cannot, that is a specification defect and is logged in
`notes/INTEGRATION.md`.

`cp_uart` is a UART with a transmit FIFO and a receive FIFO behind an AMBA APB3 register
interface, with one interrupt output. It is deliberately small, fully synchronous and
fully specified at the clock-cycle level, because every observable output is compared
against the reference model on every cycle.

## 1. Conventions

- One clock, `pclk`. All state changes at the rising edge. "Edge" always means a rising
  edge of `pclk`.
- "Pre-edge value" of a signal at an edge is the value the flip-flops see at that edge:
  inputs as driven during the preceding cycle, state as it was after the previous edge.
- Reset is `presetn`, active low and **synchronous**: at any edge whose pre-edge `presetn`
  is 0, every state element takes its reset value (section 8) and nothing else in this
  document happens at that edge. Every state element has a reset value.
- Bit 0 is the least significant bit. Register bits not named here read as 0 and ignore
  writes.
- `FIFO_DEPTH` is 4 for both FIFOs.

## 2. Ports

| port | dir | width | meaning |
|---|---|---|---|
| `pclk` | in | 1 | clock |
| `presetn` | in | 1 | synchronous reset, active low |
| `psel` | in | 1 | APB select |
| `penable` | in | 1 | APB enable |
| `pwrite` | in | 1 | APB direction, 1 = write |
| `paddr` | in | 8 | APB byte address |
| `pwdata` | in | 32 | APB write data |
| `prdata` | out | 32 | APB read data, combinational |
| `pready` | out | 1 | constant 1 (no wait states) |
| `pslverr` | out | 1 | APB error, combinational |
| `rxd` | in | 1 | serial receive line, idles at 1 |
| `txd` | out | 1 | serial transmit line, registered, idles at 1 |
| `irq` | out | 1 | interrupt, active high |

## 3. APB behaviour

A transfer **completes** at an edge whose pre-edge values have `psel = 1` and
`penable = 1` (`pready` is always 1). All register side effects happen at that edge and
only at that edge. The setup phase (`psel = 1`, `penable = 0`) has no side effects.

The stimulus is required to follow the APB protocol: `penable` is only 1 in the cycle
directly after a cycle with `psel = 1, penable = 0`, and `paddr`, `pwrite`, `pwdata` are
held stable across the two cycles of a transfer. Behaviour under protocol violations is
not specified and is never exercised.

- `prdata` is combinational. When `psel = 1` and `pwrite = 0` it is the read value of the
  register selected by `paddr` (section 4), computed from the current state; a read that
  is an error returns 0. When `psel = 0` or `pwrite = 1` it is 0.
- `pslverr` is combinational: 1 exactly when `psel = 1`, `penable = 1` and the access is
  an error. An access is an error when `paddr` is not one of the seven mapped addresses
  (all eight bits are decoded, so `0x01` is unmapped), or when it is a write to a
  read-only register (`STATUS`, `RXDATA`). A read of `TXDATA` is not an error.
- An error access has no side effects at all.

## 4. Register map

| addr | name | access | reset |
|---|---|---|---|
| `0x00` | `CTRL` | read/write | 0 |
| `0x04` | `BAUD` | read/write | 0 |
| `0x08` | `STATUS` | read-only | see 4.3 |
| `0x0C` | `TXDATA` | write-only, reads 0 | — |
| `0x10` | `RXDATA` | read-only, read pops | — |
| `0x14` | `IRQ_EN` | read/write | 0 |
| `0x18` | `IRQ_STAT` | read, write-1-to-clear | 0 |

### 4.1 CTRL (`0x00`)

| bit | name | meaning |
|---|---|---|
| 0 | `tx_en` | transmitter may start new frames |
| 1 | `rx_en` | receiver may detect new start bits |
| 2 | `par_en` | frames carry a parity bit |
| 3 | `par_odd` | 1 = odd parity, 0 = even (only meaningful with `par_en`) |
| 4 | `loopback` | receiver listens to `txd` instead of `rxd` |
| 5 | `stop2` | transmitter sends two stop bits (the receiver always checks one) |

### 4.2 BAUD (`0x04`)

Bits 7:0 are `div`. One serial bit lasts `P = div + 1` clock cycles, so `div = 0` is one
clock per bit.

### 4.3 STATUS (`0x08`)

| bits | name | meaning |
|---|---|---|
| 0 | `tx_empty` | TX FIFO count is 0 |
| 1 | `tx_full` | TX FIFO count is 4 |
| 2 | `rx_empty` | RX FIFO count is 0 |
| 3 | `rx_full` | RX FIFO count is 4 |
| 4 | `tx_busy` | transmitter is sending a frame (section 5) |
| 5 | `rx_busy` | receiver is inside a frame (section 6) |
| 10:8 | `tx_count` | TX FIFO count, 0 to 4 |
| 14:12 | `rx_count` | RX FIFO count, 0 to 4 |

After reset `STATUS` reads `0x00000005`.

### 4.4 TXDATA (`0x0C`)

A completed write pushes `pwdata[7:0]` onto the TX FIFO if the pre-edge TX count is less
than 4. If the pre-edge count is 4 the byte is discarded and `IRQ_STAT.tx_ovf` is set,
**even if the transmitter pops the FIFO at the same edge**. A push and a pop at the same
edge (count 1 to 3) leave the count unchanged.

### 4.5 RXDATA (`0x10`)

Reads return the entry at the head of the RX FIFO: bits 7:0 the data byte, bit 8
`perr` (parity error on this byte), bit 9 `ferr` (framing error on this byte). A
completed read pops that entry if the pre-edge RX count is greater than 0. If the pre-edge
count is 0 the read returns 0 and nothing is popped, **even if the receiver pushes at the
same edge**. A push and a pop at the same edge (count 1 to 3) leave the count unchanged;
a push at an edge where the pre-edge count is 4 is an overrun (section 6) even if a pop
happens at that same edge.

### 4.6 IRQ_EN (`0x14`) and IRQ_STAT (`0x18`)

Both are six bits wide with the same bit assignment:

| bit | name | set at the edge where |
|---|---|---|
| 0 | `tx_empty_ev` | the TX FIFO count goes from non-zero to 0 |
| 1 | `rx_avail_ev` | an entry is pushed onto the RX FIFO |
| 2 | `rx_ovr` | a received frame is discarded because the RX FIFO was full |
| 3 | `perr_ev` | a frame finishes reception with a parity error |
| 4 | `ferr_ev` | a frame finishes reception with a framing error |
| 5 | `tx_ovf` | a `TXDATA` write is discarded because the TX FIFO was full |

`IRQ_STAT` bits are sticky. A completed write to `IRQ_STAT` clears every bit whose
`pwdata` bit is 1. If a bit is set and cleared at the same edge, **set wins**.
`perr_ev` and `ferr_ev` are set whether or not the frame was discarded by an overrun.

`irq = 1` exactly when `(IRQ_STAT & IRQ_EN) != 0`. It depends on state only.

## 5. Transmitter

`txd` is a registered output and is 1 whenever the transmitter is idle.

**Starting a frame.** At an edge where the transmitter is *available* (idle, or at the
last edge of the final stop bit of the previous frame — see below), pre-edge `tx_en = 1`
and the pre-edge TX FIFO count is greater than 0, the transmitter pops the head of the
TX FIFO and the frame begins: `txd` is 0 from that edge on. There is no write-through: a
byte written to an empty FIFO at edge `n` is first visible to the transmitter at edge
`n + 1`, so `txd` falls at edge `n + 1` at the earliest.

**Frame parameters** `div`, `par_en`, `par_odd` and `stop2` are captured from their
pre-edge values at the edge where the frame starts and are fixed for that frame. Changing
`CTRL` or `BAUD` during a frame does not affect the frame in flight. Clearing `tx_en`
during a frame does not abort it; `tx_en` only gates the start of new frames.

**Frame layout.** With `P` the captured bit period and the frame starting at edge `s`
(so `txd` is 0 in the cycle after edge `s`):

| slot | cycles after edge | `txd` |
|---|---|---|
| start | `s` … `s + P − 1` | 0 |
| data bit `k`, `k` = 0…7 | `s + (k+1)P` … `s + (k+2)P − 1` | bit `k` of the byte (LSB first) |
| parity (only if `par_en`) | next `P` cycles | even: XOR of the eight data bits; odd: its inverse |
| stop | next `P` cycles, or `2P` if `stop2` | 1 |

"Cycle after edge `e`" means the clock period that follows edge `e`. The frame has
`N = 10 + par_en + stop2` slots and occupies the cycles after edges `s` … `s + NP − 1`.

**Ending a frame.** Edge `s + NP` is the first edge at which the transmitter is
available again. If at that edge `tx_en = 1` and the TX FIFO is non-empty, the next frame
starts right there (back to back, no idle cycle); otherwise the transmitter is idle from
that edge on.

`STATUS.tx_busy` is 1 in the cycles after edges `s` … `s + NP − 1` of any frame and 0
otherwise.

## 6. Receiver

**Input path.** `rx_in` is `txd` when `CTRL.loopback = 1` (pre-edge value of the
register bit, combinational select) and the `rxd` pin otherwise. `rx_in` passes through
a two-flop synchroniser: at every edge `s1 ← rx_in`, `s2 ← s1`. Both reset to 1. The
receiver only ever looks at `s2`. In loopback `txd` still drives the pin as normal and
the `rxd` pin is ignored.

**Start detection.** At an edge `c` where the receiver is idle, pre-edge `rx_en = 1`
and pre-edge `s2 = 0`, a frame begins. The receiver captures `div`, `par_en` and
`par_odd` from their pre-edge values at edge `c`; they are fixed for the frame. Clearing
`rx_en` mid-frame does not abort it. Let `P = div + 1` and `h = div >> 1` (integer
halving) from the captured `div`.

**Sampling.** All samples are the pre-edge value of `s2` at the named edge.

| what | edge | action |
|---|---|---|
| start check | `c + h` | if `s2 = 1` this was a false start: the receiver is idle again from this edge on (it can detect a new start at edge `c + h + 1`). When `h = 0` this is edge `c` itself and always passes. |
| data bit `k`, `k` = 0…7 | `c + h + (k+1)P` | bit `k` of the byte |
| parity (only if `par_en`) | `c + h + 9P` | `perr = 1` when (XOR of the eight data bits) XOR (sampled parity bit) differs from `par_odd` |
| stop | `c + h + 9P` without parity, `c + h + 10P` with | `ferr = 1` when the sample is 0 |

Without parity `perr = 0`.

**Completion.** At the stop-sample edge `e`:
- if the pre-edge RX FIFO count is less than 4, the entry `{ferr, perr, data}` is pushed
  and `rx_avail_ev` is set; otherwise the entry is discarded and `rx_ovr` is set;
- `perr_ev` is set if `perr`, `ferr_ev` is set if `ferr`, in both cases;
- the receiver is idle from edge `e` on, so it can detect a new start at edge `e + 1`.
  (After a framing error `s2` may still be 0 at `e + 1`; that is a new start like any
  other.)

`STATUS.rx_busy` is 1 in the cycles after edges `c` … `e − 1` and 0 in the cycle after
edge `e`. For a false start it is 1 in the cycles after edges `c` … `c + h − 1`.

## 7. Same-edge ordering, in one place

All conditions are evaluated on pre-edge values, so events at one edge do not see each
other.

- TX push when full is dropped (and sets `tx_ovf`) even if the transmitter pops at that
  edge. TX pop with simultaneous push: both happen.
- `tx_empty_ev` is set when the pre-edge TX count is 1, the transmitter pops and no push
  is accepted at that edge.
- RX pop when empty does nothing even if the receiver pushes at that edge. RX push when
  full is an overrun even if a pop happens at that edge.
- `IRQ_STAT`: set wins over write-1-to-clear.
- A write to `CTRL` or `BAUD` at the same edge as a frame start: the frame captures the
  old (pre-edge) values.

## 8. Reset values

`CTRL = 0`, `BAUD = 0`, `IRQ_EN = 0`, `IRQ_STAT = 0`, both FIFOs empty with all storage
0, `txd = 1`, `s1 = s2 = 1`, transmitter and receiver idle, all counters and captured
parameters 0.

## 9. Implementation constraints on the RTL

These exist so that the design survives `yosys prep -flatten; memory_map; write_verilog`
and SymbiYosys without special handling.

- SystemVerilog, restricted to what `yowasp-yosys read_verilog -sv` accepts: `logic`,
  `always_ff`, `always_comb`, `typedef enum`, `localparam`, `parameter`. No interfaces,
  no classes, no packages, no `unique`/`priority`, no concurrent assertions, no
  `initial` blocks, no latches, no tristates, no asynchronous reset.
- One top-level module `cp_uart` with exactly the ports of section 2 and no parameters
  that change the port list.
- Verilator 5 must lint it with `-Wall` cleanly, or with waivers that are each justified
  in a comment.
