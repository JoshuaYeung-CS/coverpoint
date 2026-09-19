# Reference model notes

Every place where `docs/SPEC.md` left room to read it two ways, what the model
(`bench/model.py`) does, and why. In each case the most literal reading of the
spec was taken. Written without sight of the RTL.

## 1. "Available" transmitter — edge `s + NP`

SPEC 5 describes the start condition as "idle, or at the last edge of the final
stop bit of the previous frame", and then says "Edge `s + NP` is the first edge
at which the transmitter is available again". Read against the frame-layout
table (the frame occupies the cycles *after* edges `s` … `s + NP − 1`), the
final stop bit's last cycle is the one after edge `s + NP − 1`, and the edge
that terminates it is `s + NP`. **Chosen:** the transmitter is available at edge
`s + NP` and at every edge while idle. A back-to-back frame therefore starts at
`s + NP` with no idle cycle, and `tx_busy` never drops between the two.

## 2. No events are recorded on a reset edge

SPEC 1 says that at a reset edge "nothing else in this document happens".
**Chosen:** `step()` with pre-edge `presetn = 0` restores the reset state and
leaves `last_events` empty — no `apb_write`, no `apb_error`, nothing, even if
`psel & penable` were 1 at that edge. The spec does not define event records at
all, so this is a model-only decision.

## 3. Event names for APB transfers

The event vocabulary is not in the spec. **Chosen:** a completed transfer emits
exactly one of `apb_write`, `apb_read` or `apb_error`. `apb_error` alone is
emitted for an error access — it is not accompanied by `apb_write`/`apb_read`,
matching "an error access has no side effects at all" (SPEC 3). Setup-phase
cycles emit nothing.

## 4. `irq_clear_lost_to_set`

**Chosen:** recorded when `(clear_mask & set_mask) != 0` at an edge, i.e. a
write-1-to-clear bit and a hardware set land on the same bit — regardless of
whether that bit was already 1 before the edge. The alternative reading (only
when a clear was genuinely lost, i.e. the bit was previously 1) was rejected as
less literal: the brief describes it as "a W1C and a set hit the same bit at the
same edge". The `IRQ_STAT` value itself is unaffected by this choice; set always
wins (SPEC 4.6, 7).

## 5. `h = 0` means no false start is possible

SPEC 6 says the start check at `c + h` "When `h = 0` … is edge `c` itself and
always passes". **Chosen:** at `div = 0` and `div = 1` (both give `h = 0`) the
model performs no start check at all, so a one-cycle glitch on `rxd` always
starts a full frame. Consequently the "false start" `rx_busy` window of SPEC 6
("cycles after edges `c` … `c + h − 1`", which would be empty for `h = 0`) is
unreachable.

## 6. `rx_busy` drops *at* the terminating edge

SPEC 6 gives `rx_busy = 1` in the cycles after edges `c` … `e − 1` and 0 in the
cycle after `e`; for a false start, 1 in the cycles after `c` … `c + h − 1`.
**Chosen:** `rx_busy` is exactly "the receiver is active", set at edge `c` and
cleared at the stop edge `e` (or at the false-start edge `c + h`). The same
holds for `tx_busy`, which is 1 in the cycles after `s` … `s + NP − 1` and stays
1 across a back-to-back boundary.

## 7. A framing error can be followed immediately by a new start

SPEC 6 sanctions this explicitly ("After a framing error `s2` may still be 0 at
`e + 1`; that is a new start like any other"). The model does exactly that: the
receiver goes idle *at* edge `e`, cannot start at `e` (start detection requires
a pre-edge idle receiver), and can start at `e + 1`. Both behaviours are
covered by tests, so a re-start after a framing error is not a model bug.

## 8. `prdata` is driven in the setup phase too

SPEC 3 conditions `prdata` on `psel` and `pwrite` only — `penable` appears in
the `pslverr` rule but not the `prdata` rule. **Chosen:** a read value is
presented in both cycles of a read transfer. For `RXDATA` this means the head
entry is visible during the setup cycle as well, while the pop still happens
only at the access edge. An empty `RXDATA` read returns 0 in all ten bits, and
an error read returns 0.

## 9. Captured frame parameters are not re-zeroed when a frame ends

SPEC 8 gives the reset value of the captured parameters as 0, but says nothing
about what they hold once a frame finishes. **Chosen:** they keep the last
frame's values until the next capture or a reset. They are not observable
through any port or through the introspection properties, so this cannot make
the model disagree with the RTL on an output.

## 10. Smaller literal readings, recorded for completeness

- **Address decode.** All eight `paddr` bits are compared, so `0x01`, `0x0D`,
  `0x1C` and `0xFF` are all unmapped errors (SPEC 3).
- **Unused bits.** `CTRL`, `IRQ_EN` and `IRQ_STAT` are masked to 6 bits on both
  write and read; `BAUD` to 8 bits; a `TXDATA` write takes `pwdata[7:0]`
  (SPEC 1, 4).
- **`stop2` is transmit-only.** The transmitter captures it; the receiver always
  checks exactly one stop bit and never captures it (SPEC 4.1, 6).
- **`tx_empty_ev` has one source.** The TX count can only reach 0 through a
  transmitter pop, so the SPEC 4.6 wording ("goes from non-zero to 0") and the
  SPEC 7 wording ("pre-edge count 1, the transmitter pops, no push accepted")
  describe the same edge. The SPEC 7 form is implemented.
- **The synchroniser always runs.** `s1`/`s2` take new values at every non-reset
  edge, whether or not `rx_en` is set and whether or not a frame is in flight
  (SPEC 6). The loopback select uses the *pre-edge* `CTRL.loopback` bit and the
  *pre-edge* `txd`, so a `CTRL` write at an edge cannot change what that edge
  samples; in loopback `txd` still drives the pin and `rxd` is ignored.
- **Protocol violations.** SPEC 3 declares them unspecified and never
  exercised, so the model simply treats any edge with pre-edge
  `psel = penable = 1` as a completed transfer and does not police the setup
  phase, address stability or `pwdata` stability.

## Not verified against anything else

The model has only been checked against `docs/SPEC.md` and the hand-computed
cycle numbers in `tests/test_model.py`. Nothing here has been compared to the
RTL; that comparison is the point of the exercise and has not been started.
