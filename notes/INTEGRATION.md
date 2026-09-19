# Integration: three implementations of one spec

`docs/SPEC.md` was written first. Three things were then written from it in separate passes, each
from the spec alone and before the others were opened:

| what | where | written from |
|---|---|---|
| the design | `rtl/cp_uart.sv`, `rtl/cp_fifo.sv` | the spec only (`notes/RTL-NOTES.md`) |
| the simulation checker | `bench/model.py`, cycle-accurate Python | the spec only (`notes/MODEL-NOTES.md`) |
| the formal checker | `formal/shadow.svh`, a specification shadow in Verilog | the spec only, before the RTL was read |

## What happened when they met

- First lockstep run of the RTL against the Python model (the smoke test, then six
  random seeds of 20,000 cycles, then the 16 directed tests): **zero mismatches**.
- The RTL against the Verilog shadow: **proved equal on every output for all time**, by
  induction, once the refinement invariants were written (`formal/invariants.svh`).
  The first induction attempt failed on exactly one missing fact, which is recorded in
  DECISIONS.md because it is the clearest example in the project of why induction needs
  strengthening.

Zero disagreements is a statement about the spec as much as about the implementations:
the notes kept during the RTL pass and the model pass (`notes/RTL-NOTES.md`,
`notes/MODEL-NOTES.md`) list the same ambiguous sentences, resolved the same way. The ones that would have produced a port-visible difference had they been read the
other way:

1. **When the transmitter is available again.** Section 5 says both "at the last edge of
   the final stop bit" and "edge `s + NP`". Both took `s + NP`. The other reading is a
   one-cycle difference on every back-to-back frame.
2. **`prdata` during the setup phase.** Section 3 gives `prdata` no `penable` term, so
   read data is live in both cycles of a read. An implementation that gated it would
   mismatch on the setup cycle of every read.
3. **Loopback latency is three edges, not two.** `s2` is `txd` delayed by two flops and
   start detection reads the pre-edge `s2`, so `c = s + 3`. The first smoke-test
   expectation written for the RTL had this wrong; the RTL was right.
4. **`h = 0`** (divisors 0 and 1): the detection edge is the start check, so no false
   start is possible and a one-cycle glitch starts a full frame.

## Bench bugs found along the way

Found while using the bench, not by the bench:

- `coverage.py` dropped two coverpoints (14 of 98 bins, the same-edge and mid-frame ones)
  from its report because of a name filter. Found while writing the directed suite,
  when the denominator came out as 84. Fixed before anything was scored for the record.
- `TxMonitor.line` is never updated from register writes, so the transaction log it
  publishes decodes every frame as 8N1 at divisor 0. It makes no pass/fail decision and
  feeds nothing that is scored. Left as is and listed in the README under what a
  professional bench would have.
