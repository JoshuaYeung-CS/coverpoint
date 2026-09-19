# cp_uart RTL notes

Design notes and every place I had to make a call while implementing
`docs/SPEC.md`. Written before the RTL was compared against anything.

## Shape of the design

- `rtl/cp_uart.sv` holds all of the behaviour; `rtl/cp_fifo.sv` is a 4-deep,
  width-parameterised FIFO instanced twice (8-bit for TX, 10-bit for RX so the
  entry carries `{ferr, perr, data}`).
- The FIFO is deliberately dumb: it never decides whether a push or pop is
  legal. The top evaluates full/empty against the **pre-edge** count and only
  asserts `push`/`pop` when the operation is actually accepted. That is what
  makes section 7 fall out for free — a push into a full FIFO is dropped even
  though a pop happens at the same edge, and a simultaneous push/pop leaves the
  count alone.
- Every decision is an `assign`/`always_comb` over register state and inputs,
  and a single `always_ff` commits them. Because nothing combinational reads a
  next-state value, "all conditions are evaluated on pre-edge values" is
  structural rather than something I had to be careful about per rule.
- Two if-chain orderings are load bearing and are commented as such in the RTL:
  `tx_pop → tx_end_edge → tx_active` (a start at the frame-end edge is a
  back-to-back frame and must beat the go-idle arm), and
  `rx_start_det → rx_sample → rx_active` (start detection only runs while idle,
  so a frame completing at edge `e` cannot also start one there).

## Spec readings I had to choose

1. **"Available … at the last edge of the final stop bit"** (§5, starting a
   frame) versus **"Edge `s + NP` is the first edge at which the transmitter is
   available again"** (§5, ending a frame). I took the second, unambiguous
   sentence: available at edge `s + NP`, implemented as pre-edge
   `tx_slot == N-1 && tx_phase == P-1`. The two sentences describe the same
   edge — `s + NP` is the edge that terminates the final stop bit's last cycle.

2. **`h == 0` start check.** §6 says the detection edge is itself the start
   check and always passes. I handle that inside the start-detect branch, so
   with `h == 0` the receiver never occupies the "awaiting start check" slot at
   all: at edge `c` it goes straight to waiting for data bit 0 at `c + P`. A
   false start is therefore impossible when `h == 0`, which also makes §6's
   "`rx_busy` is 1 in the cycles after edges `c … c + h − 1`" vacuous there.

3. **Slot 9 with `par_en = 0`** is the first stop bit, not a suppressed parity
   slot. The TX frame image is `{2'b11, par_en ? parity : 1'b1, byte, 1'b0}`,
   and `N − 1 = 9 + par_en + stop2`, so all four parameter combinations land on
   the slot table in §5 without a special case.

4. **`prdata` has no `penable` term.** §3 says `prdata` is the read value
   whenever `psel = 1` and `pwrite = 0`, so it is already presented during the
   *setup* cycle. I flag this because gating it on `penable` would be an easy
   and invisible model/RTL divergence.

5. **`RXDATA` when empty.** The count gate, not the storage, is what makes the
   read return 0 — the head cell may still hold a previously popped entry.

6. **`TXDATA` read** is legal (§3), returns 0 and has no side effect; there is
   no "read pops" language for it, so it does not touch the TX FIFO.

7. **Unnamed register bits** (§1). Writes ignore `CTRL[31:6]`, `BAUD[31:8]`,
   `IRQ_EN[31:6]` and `IRQ_STAT[31:6]`; those positions read 0, as do
   `STATUS[7:6]`, `STATUS[11]` and `STATUS[31:15]`. Write-1-to-clear on
   `IRQ_STAT` therefore only looks at `pwdata[5:0]`.

8. **`rx_avail_ev` and `rx_ovr` are mutually exclusive** — §6 pushes *and* sets
   `rx_avail_ev`, or discards *and* sets `rx_ovr`. `perr_ev`/`ferr_ev` are set
   in both cases, as §4.6 states explicitly.

9. **Reset value of the captured parameters.** §8 says captured parameters are
   0, so `tx_last_slot` resets to 0 even though that is not a legal frame
   length. `tx_active = 0` means it is never used before being loaded. Same for
   `rx_slot`/`rx_timer`, which are left untouched when a frame completes and
   are reloaded at the next start.

10. **Capture representation.** Rather than registering `par_en`, `par_odd` and
    `stop2` for the transmitter, I capture the derived 12-bit frame image plus
    `tx_last_slot` at the start edge. This is equivalent — the spec fixes all of
    those at that edge, and the parity bit depends only on the popped byte and
    `par_odd`, both known there. The receiver does capture `div`, `par_en` and
    `par_odd` raw, and deliberately does *not* capture `stop2` (§4.1: the
    receiver always checks one stop bit).

## The number most likely to differ from an independent model

**Loopback latency is three edges, not two.** `s2` in cycle `n` is `s1` in
cycle `n−1`, which is `rx_in` in cycle `n−2`; start detection at edge `c` reads
the *pre-edge* `s2`, i.e. `s2` in cycle `c−1`, which is `txd` in cycle `c−3`.
`txd` first goes low in the cycle after the frame-start edge `s`, so the
receiver detects at **`c = s + 3`**. I got this wrong by one on my first pass at
the smoke test (the RTL was right, my expected value was not), which is exactly
the kind of off-by-one the cycle-by-cycle comparison exists to catch. The smoke
test now pins it at both `div = 0` (stop sample `s + 12`) and `div = 3`
(`s + 40`).

## Other things worth a second pair of eyes

- `STATUS.tx_busy` stays continuously 1 across a back-to-back frame boundary —
  there is no zero cycle at edge `s + NP` when the next frame starts there.
  That follows from applying §5's `tx_busy` definition to both frames, but it is
  a plausible place for a model to blink.
- At the stop-sample edge the receiver goes idle and the earliest new start is
  `e + 1`; after a framing error `s2` may still be 0 there and that counts as a
  real start (§6). The RTL gets this from the if-chain order rather than an
  explicit rule.
- The `rx_data` byte is assembled by shifting right (LSB first), so slot 9 must
  not shift — the parity check reads the finished byte. Guarded explicitly.
