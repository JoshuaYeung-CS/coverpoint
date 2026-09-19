# Directed test plan

Written from `docs/SPEC.md` before the suite was run, and not changed afterwards except
to fill in measured cycle counts in `notes/DIRECTED-NOTES.md`. Nothing in here comes from
the RTL, the reference model, or any mutant: the plan is a reading of the specification,
section by section, and an argument that each rule is *reached* by some stimulus.

## How to read it

Checking is not the directed tests' job. Every test, directed or random, is compared
against the reference model on `prdata`, `pready`, `pslverr`, `txd` and `irq` in every
cycle. So a directed test only has to drive the device into the behaviour a rule
describes; a wrong implementation then differs at a port and the scoreboard stops.

That gives two rules of thumb the whole suite follows:

1. `txd`, `irq`, `pready` and `pslverr` are free — they are compared every cycle whether
   or not anyone looks at them. Any rule whose effect reaches one of those pins is
   covered as soon as the stimulus provokes it.
2. Everything else is only visible through a register read, so STATUS and IRQ_STAT are
   read after every interesting event (and often *during* one, back to back, so the
   busy flags are sampled inside their window), and every register written is read back.

The "how it would show at the ports" column names the port the rule reaches, on the
assumption that an implementation which gets the rule wrong is still compared cycle by
cycle against one that gets it right.

Alignment-sensitive rules (section 7 above all) cannot be hit by a single well-aimed
access, because the sequencer's hand-off to the driver has a one-cycle slack. Those rows
say "swept": the scenario is repeated with the delay before one access stepped across a
window that brackets the computed edge, so one iteration lands on it. The functional
coverage bins `cp.corner:*` confirm after the fact which same-edge behaviours the
stimulus actually reached.

## Section 1 — conventions

| Rule | Test(s) | How it would show at the ports |
|---|---|---|
| One clock, every state change at a rising edge, pre-edge evaluation | all | The model is stepped from the same pin values on the same edges; any off-by-one-cycle behaviour is a `txd`/`irq`/`prdata` mismatch in the cycle it happens. |
| Reset is synchronous, active low, and *nothing else* happens at a reset edge | `dir_reset_and_regs`, `dir_reset_midframe` | Reset is asserted while a TX frame and while an RX frame are in flight, and (in the sweeps) between iterations with the FIFOs loaded: `txd` must return to 1 and STATUS to `0x5` immediately, with no residual frame on `txd`. |
| Every state element has a reset value (section 8) | `dir_reset_and_regs`, `dir_reset_midframe` | Read CTRL, BAUD, STATUS, IRQ_EN, IRQ_STAT and RXDATA straight after a mid-test reset; each returns its reset value on `prdata`. |
| Bits not named read 0 and ignore writes | `dir_reset_and_regs` | All-ones, `0x55555555`, `0xAAAAAAAA` and walking ones (including bits 15, 16, 31) into CTRL, BAUD and IRQ_EN, each read back: a register that stored an unused bit returns it on `prdata`. |
| `FIFO_DEPTH` is 4 for both FIFOs | `dir_tx_fifo_and_enable`, `dir_rx_fifo` | Fill each FIFO to 4 and one past it; STATUS `tx_count`/`rx_count` and the full flags on `prdata`, plus the discarded byte never appearing on `txd`. |

## Section 2 — ports

| Rule | Test(s) | How it would show at the ports |
|---|---|---|
| `pready` is constant 1 | all | Compared every cycle. |
| `prdata` is 0 when `psel = 0` or `pwrite = 1` | all | Compared every cycle, including every idle cycle and every write. |
| `txd` registered, idles at 1 | all | Compared every cycle; the suite spends most of its cycles with the transmitter idle. |
| `rxd` idles at 1 | all (driver-held) | The rxd driver leaves the line high between frames. |
| `irq` active high | `dir_irq` | Compared every cycle. |

## Section 3 — APB behaviour

| Rule | Test(s) | How it would show at the ports |
|---|---|---|
| A transfer completes at the edge with `psel = 1, penable = 1`; side effects only there | all | Every side effect in the suite is timed from a completion edge; the same-edge tests fail by one cycle if the effect happens in the setup cycle instead. |
| The setup phase has no side effects | `dir_tx_same_edge`, `dir_rx_same_edge`, `dir_reset_and_regs` | A push or pop taken a cycle early moves the swept alignment by one, which shows as a wrong `txd` frame count / wrong `prdata` in the same iteration. |
| `prdata` is the selected register's read value when `psel = 1, pwrite = 0` | all | Every register is read back after every event; also checked in the *setup* cycle of each read, which is when a read's value must already be the pre-pop one. |
| An error read returns 0 | `dir_error_access` | Reads of 14 unmapped addresses return 0 on `prdata`. |
| `pslverr` is 1 exactly when `psel`, `penable` and the access is an error | `dir_error_access`, all | `pslverr` is compared every cycle: the error test drives 14 unmapped addresses (including `0x01`, `0x1C`, `0xFF`) read and written, both read-only registers written, and a TXDATA read that must *not* raise it. Every legal access in the rest of the suite is a negative case. |
| All eight address bits are decoded (`0x01` is unmapped) | `dir_error_access` | `0x01`, `0x02`, `0x03`, `0x05`, `0x07`, `0x0B`, `0x0D`, `0x11`, `0x15`, `0x19`, `0x1C`, `0x20`, `0x7F`, `0xFF` — every mapped address has at least one near neighbour, so a decoder that ignores low or high bits raises or drops `pslverr`. |
| Writes to STATUS and RXDATA are errors | `dir_error_access` | `pslverr` on those two writes, and the RXDATA write must not pop: the following RXDATA read returns the same head entry on `prdata`. |
| A TXDATA read is *not* an error | `dir_error_access`, `dir_reset_and_regs` | `pslverr` stays 0 and `prdata` is 0. |
| An error access has no side effects at all | `dir_error_access` | A full state snapshot (CTRL, BAUD, STATUS, IRQ_EN, IRQ_STAT) is read before and after a barrage of error accesses carrying all-ones data, with both FIFOs loaded and IRQ_STAT bits set; any side effect changes the second snapshot on `prdata`. |
| Protocol violations | **not covered, deliberately** | The spec says behaviour is unspecified and never exercised, and the driver cannot generate one. |
| Back-to-back transfers (`idle = 0`) and spaced ones | `dir_reset_and_regs` (idle 0/1/3 over the whole map), every sweep (idle 0 chains), `dir_baud_large` (long gaps) | A decoder or hold-time bug that needs an idle cycle shows as wrong `prdata`/`pslverr` in the back-to-back chains. |

## Section 4 — register map

| Rule | Test(s) | How it would show at the ports |
|---|---|---|
| Seven addresses, access types and reset values | `dir_reset_and_regs` | Read every register out of reset; write and read back the three read/write ones. |
| 4.1 CTRL bit assignment (`tx_en`, `rx_en`, `par_en`, `par_odd`, `loopback`, `stop2`) | `dir_tx_fifo_and_enable` (bit 0), `dir_rx_errors_and_enable` (bit 1), `dir_tx_formats` + `dir_rx_basic` (bits 2, 3), `dir_loopback` (bit 4), `dir_tx_formats` (bit 5) | Each bit is set alone and in combination; a swapped or stuck bit changes the frame on `txd` or stops a frame being received (RXDATA on `prdata`). |
| 4.2 BAUD: `P = div + 1`, `div = 0` is one clock per bit | `dir_tx_formats` (div 0, 1), `dir_rx_basic` (div 0–3), `dir_baud_realistic` (div 15), `dir_baud_large` (div 137) | Bit period on `txd` directly; on RX a wrong period samples the wrong bits and shows as a wrong byte or a framing error on `prdata`. The two large divisors exercise the upper divisor bits, which nothing else reaches. |
| 4.3 STATUS field positions; `0x5` after reset | `dir_reset_and_regs` and every test | STATUS is read after every event, and during frames (back-to-back reads) so `tx_busy`/`rx_busy` are sampled inside their windows. |
| 4.4 TXDATA push when the pre-edge count is < 4 | `dir_tx_fifo_and_enable` | `tx_count` climbs on `prdata`; every pushed byte appears on `txd` in order. |
| 4.4 A write when the count is 4 is discarded and sets `tx_ovf` | `dir_tx_fifo_and_enable` | STATUS stays at 4, IRQ_STAT bit 5 on `prdata`, and the discarded byte never appears on `txd`. |
| 4.4 …even if the transmitter pops at the same edge | `dir_tx_same_edge` (swept) | The write is aimed at the back-to-back frame-start edge with the FIFO full. If the device accepted it, one extra frame appears on `txd` and `tx_ovf` is absent from IRQ_STAT. Confirmed by `cp.corner:tx_overflow_and_pop`. |
| 4.4 Push and pop at the same edge (count 1–3) leave the count unchanged | `dir_tx_same_edge` (swept) | STATUS `tx_count` read two cycles later, and the frame sequence on `txd`. Confirmed by `cp.corner:tx_push_and_pop`. |
| 4.5 RXDATA returns data, `perr` in bit 8, `ferr` in bit 9 | `dir_rx_errors_and_enable`, `dir_rx_basic` | Read back on `prdata` after clean, parity-error, framing-error and both-error frames. |
| 4.5 A completed read pops when the pre-edge count > 0 | `dir_rx_fifo` | Four entries are read out in order; a missing or double pop changes the next `prdata` and `rx_count`. |
| 4.5 A read when the count is 0 returns 0 and pops nothing | `dir_rx_fifo`, `dir_rx_same_edge` (every iteration drains one past empty) | `prdata` is 0 and `rx_count` stays 0. |
| 4.5 …even if the receiver pushes at that edge | `dir_rx_same_edge` (swept, empty FIFO) | The read is aimed at the stop-sample edge with the FIFO empty: the entry must still be there afterwards, so the *next* read returns it on `prdata`. Confirmed by `cp.corner:rx_pop_empty_and_push`. |
| 4.5 Push and pop at the same edge (count 1–3) leave the count unchanged | `dir_rx_same_edge` (swept, two entries preloaded) | `rx_count` on `prdata`, and the drain afterwards must return the entries in order — a mishandled simultaneous push/pop shows in the order, not the count. Confirmed by `cp.corner:rx_push_and_pop`. |
| 4.5 A push when the pre-edge count is 4 is an overrun even if a pop happens at that edge | `dir_rx_same_edge` (swept, four entries preloaded) | IRQ_STAT `rx_ovr` on `prdata`, and the drained entries are the original four, not the new byte. Confirmed by `cp.corner:rx_overrun_and_pop`. |
| 4.6 Six IRQ bits, same assignment in both registers | `dir_irq` | Each source is generated and the bit read back; IRQ_EN is written walking-ones in `dir_reset_and_regs`. |
| 4.6 Set conditions for all six sources | `dir_irq` (all six in one pass), `dir_tx_fifo_and_enable` (`tx_empty_ev`, `tx_ovf`), `dir_rx_fifo` (`rx_avail_ev`, `rx_ovr`), `dir_rx_errors_and_enable` (`perr_ev`, `ferr_ev`) | IRQ_STAT on `prdata`; with the matching IRQ_EN bit set, also the exact cycle `irq` rises. |
| 4.6 `tx_empty_ev` is the non-zero → zero transition | `dir_tx_fifo_and_enable`, `dir_tx_same_edge` | Set at the *pop* edge that empties the FIFO, not at the end of the frame: IRQ_STAT read a few cycles after that edge, and `irq` with the bit enabled. |
| 4.6 IRQ_STAT bits are sticky | `dir_irq` | Six sources are set with IRQ_EN = 0 and left alone for ~150 cycles; all six must still be set when IRQ_STAT is read. |
| 4.6 A write clears every bit whose data bit is 1 (W1C), and only those | `dir_irq` | A subset write with three bits set, then IRQ_STAT read: the untouched bits must remain on `prdata`. |
| 4.6 Set wins over clear at the same edge | `dir_irq` (swept) | An IRQ_STAT write clearing `tx_empty_ev` is stepped across the back-to-back frame-start edge that sets it, with the bit enabled so `irq` shows the outcome in the cycle after. Confirmed by `cp.corner:irq_set_wins_over_clear`. |
| 4.6 `perr_ev`/`ferr_ev` are set even when the frame is discarded by an overrun | `dir_irq` | The last frame of the IRQ pass arrives with a parity *and* framing error into a full RX FIFO: IRQ_STAT must show `rx_ovr`, `perr_ev` and `ferr_ev` together. |
| 4.6 `irq = 1` exactly when `(IRQ_STAT & IRQ_EN) != 0`, state only | `dir_irq` | `irq` is compared every cycle: all six bits are set with IRQ_EN = 0 (masked, `irq` must stay 0), then each bit is enabled alone (`irq` rises) and cleared (`irq` falls). |

## Section 5 — transmitter

| Rule | Test(s) | How it would show at the ports |
|---|---|---|
| `txd` is 1 whenever the transmitter is idle | all | Compared every cycle. |
| A frame starts at an edge where the transmitter is available, `tx_en = 1` and count > 0 | `dir_tx_formats`, `dir_tx_fifo_and_enable` | The first falling edge of `txd`. |
| No write-through: `txd` falls at `n + 1` at the earliest | `dir_tx_formats` and every TXDATA write into an empty FIFO | A write-through implementation starts the frame one cycle early — a `txd` mismatch at the start bit. |
| `tx_en` gates only the *start* of frames | `dir_tx_fifo_and_enable` | Four bytes are queued with `tx_en = 0` (nothing on `txd`, `tx_count` = 4 on `prdata`), then `tx_en` is set and all four frames appear. |
| Clearing `tx_en` mid-frame does not abort the frame | `dir_tx_fifo_and_enable` | CTRL is written mid-frame: the frame must finish on `txd`, and the queued second byte must *not* start. |
| `div`, `par_en`, `par_odd`, `stop2` are captured at the frame-start edge and fixed | `dir_midframe_config` | CTRL and BAUD are rewritten mid-frame with a very different format (parity + two stops, `div` 3 → 0): the frame in flight must be unchanged on `txd`, and the *next* frame must use the new values. |
| Frame layout: start / 8 data LSB-first / optional parity (even = XOR, odd = its inverse) / 1 or 2 stop bits, each `P` cycles | `dir_tx_formats` (six format combinations × bytes `0x00`, `0xFF`, `0x55`), `dir_baud_realistic`, `dir_baud_large` | Bit-for-bit on `txd`. `0x00`/`0xFF` pin the parity polarity, `0x55`/`0xAA` and walking ones pin the bit order. |
| `N = 10 + par_en + stop2` slots | `dir_tx_formats` | The length of the frame on `txd`; a wrong `N` shifts every following frame. |
| The next frame starts at `s + NP` with no idle cycle | `dir_tx_formats` (walking-ones batches out of a full FIFO), `dir_tx_fifo_and_enable` | Four frames run back to back on `txd`; a one-cycle idle between them is a mismatch. |
| `tx_busy` is 1 in the cycles after `s … s + NP − 1` | `dir_tx_formats`, `dir_tx_fifo_and_enable`, `dir_baud_*` | Back-to-back STATUS reads inside the frame and immediately after it, on `prdata`. |

## Section 6 — receiver

| Rule | Test(s) | How it would show at the ports |
|---|---|---|
| `rx_in` is `txd` when `loopback`, the pin otherwise | `dir_loopback` | A different byte is driven on the pin *while* a loopback frame is in flight; RXDATA must return the transmitted byte and the FIFO must hold exactly one entry. |
| In loopback `txd` still drives the pin and `rxd` is ignored | `dir_loopback` | `txd` is compared every cycle during loopback; the ignored pin frame must not appear on `prdata`. |
| Two-flop synchroniser, both reset to 1 | `dir_rx_basic`, `dir_rx_false_start`, every RX test | Every RX timing in the suite is anchored two edges after the driver puts the start bit on the pin; one flop instead of two shifts every sample point, which shows as a wrong byte or a framing error on `prdata`. |
| Start detection at an edge with `rx_en = 1` and `s2 = 0` | `dir_rx_basic`, `dir_rx_errors_and_enable` | The received byte on `prdata`, and `rx_busy` in STATUS. |
| `rx_en = 0` ignores the line | `dir_rx_errors_and_enable` | A whole frame is driven with `rx_en = 0`: `rx_busy` and `rx_count` must stay 0 across six back-to-back STATUS reads. |
| Clearing `rx_en` mid-frame does not abort the frame | `dir_rx_errors_and_enable` | CTRL is written mid-frame; the frame must still complete and its byte must be readable. |
| `div`, `par_en`, `par_odd` captured at edge `c`, fixed for the frame | `dir_midframe_config` | BAUD and CTRL are rewritten mid-frame (`div` 3 → 0, parity added); the byte must still read back correctly. |
| `h = div >> 1` | `dir_rx_basic` (div 0–3), `dir_rx_false_start` (div 5, 7, 15), `dir_baud_*` (div 15, 137) | Both even and odd divisors are used, so a wrong halving samples off-centre; at the large divisors an off-by-one `h` still lands inside the bit, which is why the false-start tests pin `h` exactly. |
| Start check at `c + h`: `s2 = 1` is a false start, idle from that edge, new start possible at `c + h + 1` | `dir_rx_false_start` | Glitches of `h − 1` and `h` cycles (false) and `h + 1` cycles (accepted) at div 5, 7 and 15; a glitch of exactly `h` followed immediately by a real frame puts the new start on the first edge the spec allows. A wrong check point either swallows the frame (nothing on `prdata`) or accepts the glitch (a spurious entry). |
| When `h = 0` the start check is edge `c` itself and always passes | `dir_rx_false_start` (div 0, one-cycle glitch) | The one-cycle glitch must produce a full frame of ones (`0xFF`) in the FIFO. |
| Data bit `k` sampled at `c + h + (k+1)P`, LSB first | `dir_rx_basic` (bytes `0x55`, `0xAA`, `0x00`, `0xFF`, `0x3C`, `0x81`) | The byte on `prdata`. |
| Parity sampled at `c + h + 9P`; `perr` when the computed parity differs from `par_odd` | `dir_rx_basic` (even and odd, clean), `dir_rx_errors_and_enable` (deliberately wrong parity bit, even and odd) | Bit 8 of RXDATA and `perr_ev` in IRQ_STAT. |
| Without parity `perr = 0` | `dir_rx_basic`, `dir_rx_fifo` | Bit 8 clear on `prdata`. |
| Stop sampled at `c + h + 9P` (no parity) or `+ 10P`; `ferr` when it is 0 | `dir_rx_errors_and_enable` | Bit 9 of RXDATA, `ferr_ev` in IRQ_STAT. |
| At the stop edge: push and `rx_avail_ev` if count < 4, else discard and `rx_ovr` | `dir_rx_fifo` | Four frames fill the FIFO, the fifth is lost: `rx_count` stays 4, IRQ_STAT `rx_ovr`, and the four bytes read back are the first four. |
| `perr_ev`/`ferr_ev` set whether or not the frame was discarded | `dir_irq` | An error frame into a full FIFO sets all three bits on `prdata`. |
| Idle from edge `e`; a new start is possible at `e + 1`, including straight after a framing error | `dir_rx_fifo`, `dir_rx_same_edge` (gap-0 bursts), `dir_rx_errors_and_enable` (the frame the driver's recovery cycle starts after a framing error) | Back-to-back frames with no gap: the second byte must arrive. A receiver that needs an idle cycle loses it, which shows as a short `rx_count` and a missing entry on `prdata`. |
| `rx_busy` is 1 after edges `c … e − 1`, and after `c … c + h − 1` for a false start | `dir_rx_basic`, `dir_rx_false_start` | Back-to-back STATUS reads spanning the frame and the glitch window. |

## Section 7 — same-edge ordering, line by line

| Rule | Test(s) | How it would show at the ports |
|---|---|---|
| Conditions are evaluated on pre-edge values, so events at one edge do not see each other | all six rows below | — |
| TX push when full is dropped and sets `tx_ovf` even if the transmitter pops at that edge | `dir_tx_same_edge` (swept, aimed at the back-to-back start edge with the FIFO full) | An extra frame on `txd` and a missing `tx_ovf` on `prdata` if the device lets the push in. `cp.corner:tx_overflow_and_pop`. |
| TX pop with a simultaneous push: both happen | `dir_tx_same_edge` (swept, count 1) | `tx_count` unchanged on `prdata` and the pushed byte transmitted afterwards. `cp.corner:tx_push_and_pop`. |
| `tx_empty_ev` is set when the pre-edge count is 1, the transmitter pops, and no push is accepted at that edge | `dir_tx_same_edge` (swept) | With IRQ_EN bit 0 set, `irq` must stay low through that edge and IRQ_STAT (read two cycles later, before the following frame sets it anyway) must be clear. |
| RX pop when empty does nothing even if the receiver pushes at that edge | `dir_rx_same_edge` (swept, empty) | The entry survives: the next read returns it on `prdata`. `cp.corner:rx_pop_empty_and_push`. |
| RX push when full is an overrun even if a pop happens at that edge | `dir_rx_same_edge` (swept, four entries) | `rx_ovr` on `prdata` and the new byte absent from the drained entries. `cp.corner:rx_overrun_and_pop`. |
| IRQ_STAT: set wins over write-1-to-clear | `dir_irq` (swept) | `irq` stays high after the clearing write, and IRQ_STAT still reads the bit. `cp.corner:irq_set_wins_over_clear`. |
| A write to CTRL or BAUD at the same edge as a frame start: the frame captures the old values | `dir_midframe_config` (two sweeps: a CTRL write across a back-to-back TX start edge, a BAUD write across an RX start-detect edge) | TX: the frame on `txd` must keep the old format (a captured new value adds a parity bit and a second stop bit). RX: the frame must still read back correctly (a captured new `div` of 5 against a line running at period 2 produces a different byte and a framing error). No coverage bin distinguishes these, so both sweeps use the alignment calibrated by the confirmable sweeps above. |

## Section 8 — reset values

| Rule | Test(s) | How it would show at the ports |
|---|---|---|
| `CTRL = BAUD = IRQ_EN = IRQ_STAT = 0`, both FIFOs empty with zeroed storage, `txd = 1`, `s1 = s2 = 1`, transmitter and receiver idle, counters and captured parameters 0 | `dir_reset_and_regs` (out of reset and after a mid-test reset with every register non-zero, both FIFOs loaded and IRQ_STAT bits set), `dir_reset_midframe` (reset inside a TX frame and inside an RX frame), every sweep iteration | `prdata` on the register sweep after the reset; `txd` back to 1 in the next cycle with no residue of the aborted frame; `s2` reset to 1 means the receiver must not see a start from a line the reset interrupted. |

## Section 9 — implementation constraints on the RTL

**Not covered, deliberately.** These are constraints on the source (SystemVerilog subset,
lint, synthesisability), not behaviour at the ports, and are checked by the lint and
formal flows rather than by simulation.

## Deliberate gaps, in one place

- **Section 3 protocol violations** — the spec says behaviour is unspecified and never
  exercised; the APB driver is protocol-correct by construction.
- **Section 9** — not a simulable behaviour.
- **Divisors between 16 and 135, and between 138 and 255** — only two large divisors are
  used (15 and 137, chosen so that `div`, `P` and `h` each exercise low and high bits and
  an odd halving). A per-divisor sweep would cost tens of thousands of cycles for a
  behaviour that is linear in `div`.
- **All 256 data bytes** — the suite uses `0x00`, `0xFF`, `0x55`, `0xAA`, all eight
  walking ones, and a handful of asymmetric bytes (`0x3C`, `0x5A`, `0x81`, `0x96`, `0x9C`,
  `0xA5`, `0xC3`, `0x6B`). Together these pin bit order, parity polarity and every
  individual data-path bit.
- **Simultaneous events on both FIFOs at one edge** (a TX pop at the same edge as an RX
  push, say) are not aimed at individually; they occur incidentally in `dir_loopback`,
  which runs both engines at once, and are the random suite's job.

## Post-run addendum

Added after the suite was first run; the rule-to-test mapping above is unchanged.

The introduction and six rows of this plan say the `cp.corner:*` bins confirm which
same-edge behaviours the stimulus reached. They cannot: `Coverage._points()` in
`bench/tb/coverage.py` keeps only coverpoint names with two dots, and `cp.corner` and
`cp.midframe` have one, so those fourteen bins are sampled but never appear in the
result record's `bins`, `hit` or `missed`. The reported denominator is 84; the coverage
model declares 98.

Each swept scenario was therefore confirmed a different and stronger way: the run was
repeated with the discriminating register readback recorded per alignment, and the
boundary in those values pins the edge exactly and shows the specified behaviour at it,
rather than only showing that a bin incremented. The boundaries, and the arithmetic they
confirm, are in `notes/DIRECTED-NOTES.md`. All five reachable FIFO corners land inside
the swept windows at the computed alignments.
