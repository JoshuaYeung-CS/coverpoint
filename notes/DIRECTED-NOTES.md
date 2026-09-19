# Directed suite — build notes

Sixteen tests in `bench/tb/directed.py`, listed in run order in `DIRECTED`.
`docs/TESTPLAN.md` is the rule-by-rule mapping and was written from the specification
before the suite was run; nothing in it was changed afterwards.

## What was and was not read

Written from `docs/SPEC.md` and the bench it extends (`seqlib.py`, `items.py`, `regs.py`,
`agents.py`, `env.py`, `scoreboard.py`, `tests.py`, `coverage.py`, `entry.py`).
Deliberately not opened: `rtl/`, `bench/model.py`, `notes/RTL-NOTES.md`,
`notes/MODEL-NOTES.md`, `results/`, `formal/`, `scratch/`, and anything to do with
mutants. Of `build/`, only the unmutated `*_s0_m0` run directories were looked at, for
the simulator log and the result record; nothing with `mutsel != 0`. The only thing ever
run was the unmutated design.

## Cycles

| test | cycles | |
|---|---:|---|
| `dir_reset_and_regs` | 388 | reset values, bit masking, walking ones, APB spacing, mid-test reset |
| `dir_error_access` | 201 | 14 unmapped addresses read and written, both read-only registers written, TXDATA read, before/after state snapshot |
| `dir_tx_formats` | 704 | 6 parity/stop combinations × 3 bytes, plus walking ones out of a full FIFO |
| `dir_tx_fifo_and_enable` | 256 | fill, full, two overflows, back-to-back drain, `tx_en` gating both ways |
| `dir_tx_same_edge` | 812 | two swept scenarios, 7 alignments each |
| `dir_midframe_config` | 761 | CTRL/BAUD under a TX and an RX frame, plus two swept frame-start-edge cases |
| `dir_rx_basic` | 328 | 6 (divisor, parity, byte) cases from the pin |
| `dir_rx_errors_and_enable` | 754 | `rx_en` gate, 7 error combinations, `rx_en` cleared mid-frame |
| `dir_rx_false_start` | 748 | start check from both sides at `h` = 2, 3, 7 and 0 |
| `dir_rx_fifo` | 216 | fill, overrun, order, reads past empty, gap-free burst |
| `dir_rx_same_edge` | 1596 | one swept scenario at three FIFO levels, 7 alignments each |
| `dir_loopback` | 195 | three parity settings with the pin driven against it |
| `dir_irq` | 640 | all six sources masked, then enabled one at a time, subset W1C, swept set-wins |
| `dir_reset_midframe` | 193 | reset inside a TX frame and inside an RX frame |
| `dir_baud_realistic` | 501 | div = 15, one frame each way |
| `dir_baud_large` | 3397 | div = 137, one frame each way |
| **total** | **11690** | |

Every test finishes `killed == False`, `stimulus_finished == True` on the unmutated
design. No disagreement between the device and the reference model was found.

## Design choices

**Stimulus, not assertions.** Every test is checked by the lockstep scoreboard, so none
of these sequences assert anything. What they do instead is make internal state reach a
port: STATUS and IRQ_STAT are read after every event, back-to-back reads (`idle = 0`)
are used *inside* frames so `tx_busy`/`rx_busy` are sampled within their window rather
than after it, and every register written is read back. The RX sweeps drain one read past
empty every iteration, because a mishandled simultaneous push and pop shows up in the
*order* bytes come out, not in the count.

**Same-edge cases are swept, not aimed.** Two APB transfers can never complete on
adjacent edges (an item posted at falling edge `x` completes at `x + idle + 1`), so the
first frame start — one edge after the write that filled the FIFO — is out of reach of a
second access by construction. Every same-edge scenario is therefore aimed at a
*back-to-back* frame start (`s + NP`) or at an RX stop-sample edge, and repeated with the
delay before the aimed access stepped across seven alignments so one of them lands on the
edge whatever slack the sequencer adds.

**The alignment was calibrated from port-visible values, not guessed.** Each sweep was
run once with the discriminating readback recorded per iteration, and the boundary in
those values pins the edge exactly:

| scenario | readback that moves | boundary | conclusion |
|---|---|---|---|
| push on the pop that empties the FIFO | IRQ_STAT `tx_empty_ev` read two cycles later | 0 up to d = 9, 1 from d = 10 | the write completes at `m + d + 2`; d = 9 is the pop edge, and at d = 9 the event is suppressed |
| push when full on a pop edge | IRQ_STAT `tx_ovf` | set up to d = 7, clear from d = 8 | d = 7 is the pop edge; the push is dropped *and* the pop happens |
| RXDATA read on the stop-sample edge, FIFO empty | RXDATA, then `rx_count` | returns 0 with count 1 at d = 10, returns the byte at d = 11 | the stop sample is at `a + 12`; at d = 10 the read pops nothing and the entry survives |
| same, FIFO full | `rx_count` after | 4 at d = 9, 3 at d = 10 | at d = 10 the push is an overrun *and* a pop happens at that edge |

So `W = anchor + d + 2` holds exactly, with no slack in practice, and all five reachable
FIFO corners are hit inside the swept windows. The same arithmetic justifies the two
sweeps whose outcome no readback distinguishes (a CTRL write on a back-to-back TX frame
start, d = 9; a BAUD write on the RX start-detect edge, d = 1): they use the same anchor
structure, and the windows contain those values. The instrumentation was removed again —
the readbacks themselves were kept, since they are worth checking anyway.

**Divisors.** Most tests run at `div` 0–3 so cycles go on behaviour rather than waiting.
`div = 15` and `div = 137` each send and receive a frame: 137 is odd and sets bit 7, so
`P = 138` and `h = 68` exercise the top of the period counter and the halving together.
Those two tests are 3,898 of the 11,690 cycles, which is the price of covering the upper
divisor bits at all.

**Reset between sweep iterations** instead of unwinding state by hand: it is three cycles,
it makes iterations independent, and it adds a reset with both FIFOs loaded to the suite
for free.

## Awkward corners of the bench

- **`coverage.py` silently drops two coverpoints.** `Coverage._points()` keeps only names
  with two dots (`n.count(".") == 2`), so `cp.corner` and `cp.midframe` — one dot each —
  never appear in `bins`, `hit` or `missed`. The reported total is 84 bins; the model
  actually declares 98. The fourteen excluded bins are precisely the hardest ones: all six
  same-edge corners and all eight mid-frame cases. They are sampled, so they exist in the
  `coverage_db`, they just do not reach the result record. Directed coverage of those
  behaviours had to be demonstrated through readbacks instead (the table above). Worth
  fixing in `coverage.py`, which is outside this change.
- **Two APB accesses cannot land on adjacent edges**, which quietly removes a whole class
  of same-edge scenarios (anything aimed at the *first* frame start after a write). It is
  a property of the driver, not the device, and it is why the sweeps target back-to-back
  frame boundaries.
- **The rxd driver holds the line low into the next item after `bad_stop`**, apart from a
  single recovery cycle. That is realistic and spec-legal — section 6 says `s2` may still
  be 0 at `e + 1` and that is a new start like any other — but it means a framing-error
  frame is usually followed by a second, spurious frame of `0xFF`. Each error case drains
  three entries rather than one for that reason.
- **`TxMonitor.line`** is never wired to anything by the bench, so the transmit monitor
  decodes every frame at period 1 with no parity. Nothing consumes its analysis port, so
  it is harmless, but its transaction log is meaningless at any other divisor.
- **cocotb's Python log does not reach `build/*/runs/*/sim.log`** (only the GPI lines do),
  so `self.logger.info` is not a usable debugging channel here; the calibration above had
  to go through the result record instead.

## Coverage

Combined over the suite, the sixteen tests hit **84 of the 84 reported bins** — the
intersection of the per-test `missed` sets is empty, i.e. every reported bin is reached by
at least one directed test. (A literal *union* of the missed sets is 79 bins and means
nothing as a suite figure: it just counts bins that some individual test did not reach.
Per test the range is 19 to 44 bins.) No attempt was made to reach every bin from any
single test.

The three bins that no test reached on the first run were `cp.rx.outcome` for
`(even, ferr)`, `(odd, ferr)` and `(odd, both)` — framing errors on parity-enabled frames,
where the stop bit is sampled a period later than in the no-parity case. Three cases were
added to `RX_ERROR_CASES` to cover them; the test-plan mapping did not change, since those
rows already named `dir_rx_errors_and_enable`.
