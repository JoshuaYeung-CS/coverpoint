# Defense

Fifteen questions an interviewer for a design-verification role would ask, answered from
the code and the results. Numbers are from `results/confirmatory/` unless marked.

## 1. What does your mutation score measure, and what does it not?

It measures how much of the design's logic the verification would notice if it were
wrong. Yosys `mutate` makes single-point changes to the elaborated netlist: invert a bit,
tie it to 0 or 1, or invert it when a neighbouring bit is set. A mutant is killed when a
checker fires on it while the same stimulus passes on the original. 1,000 mutants, 56
proved equivalent, 944 scored.

It is not a bug-finding rate. Real bugs are usually a misread spec implemented
faithfully, and no single-point mutation models that. And because every arm here shares a
complete checker, the score says nothing about checker quality: it measures stimulus
reach (question 2).

## 2. Your scoreboard is a cycle-exact model of your own design. Isn't that writing the design twice and checking it against itself?

It is writing the *spec* three times, by design. `bench/model.py` was written from
`docs/SPEC.md` by someone who never saw the RTL, and the RTL by someone who never saw the
model (`notes/INTEGRATION.md`). They agreed on every output of every cycle at first
contact, and both authors independently flagged the same four ambiguous sentences.

The reason for a cycle-exact model rather than per-test checks is experimental control.
I wanted to compare *stimulus* techniques. If directed tests had hand-written checks and
random had a transaction scoreboard, a difference in score could come from either the
stimulus or the checker, and the checker differences would have been my choices. With one
oracle on every port every cycle, a bug is detected exactly when it reaches a port, in
every arm. The price, which the README states: every arm is an upper bound on the real
technique. In industry the checker is the usual weak point and this project deliberately
says nothing about it.

## 3. Directed and constrained-random tied. So is one of them pointless?

They tied on count, 97.2% against 96.9% at the same 11,690 cycles, and the plan said in
advance that a difference inside the seed spread (907 to 924 killed, against 918) would be
reported as no measurable difference. But they did not kill the same mutants: per seed, 3
to 17 are directed-only and 5 to 9 random-only, and together the simulation arms reach
99.3%.

What each misses is characteristic. The directed suite misses what its author's habits
hide: it only ever sends frames at divisors 0 to 7, 15 and 137, so twelve baud-counter
mutants survive; it always writes `IRQ_EN` just before relying on it, so a mutant where
writing any other register clears `IRQ_EN[3]` survives; its 14 unmapped addresses do not
include `0x84` or `0x88`. Random finds all of those on most seeds. Random in turn misses
exact alignments the directed suite constructs on purpose. That is the textbook argument
for doing both, with numbers on it.

## 4. Formal is supposed to be exhaustive. Why did it score lowest, 85.0%?

Because what I ran on the mutants is a *bounded* search: every legal input sequence, but
only 25 cycles deep, and only with baud divisor 0 or 1 so that a frame fits in the bound.
Inside that box it is exhaustive, and it shows: every one of its 802 kills is a real
counterexample from reset, the median one 7 cycles long, found in well under a second.
Outside the box it is blind, and I said so before drawing the sample: 49 of its misses
need a divisor above 1, and 89 need more than 25 cycles to reach a port (the third and
fourth receive FIFO entries, overruns, long frames). `docs/SURVIVORS.md` classifies them
mechanically, from an unrestricted search that every killed mutant also got.

The unbounded result is separate and is about the original design, not the mutants
(question 5).

## 5. Explain k-induction, why a proof can come back UNKNOWN, and what a strengthening invariant is.

To prove a property P holds forever: show it holds for the first k cycles from reset (the
base case, which is just bounded model checking), and show that *any* k consecutive
states satisfying P are followed by a state satisfying P (the step). If both pass, P holds
forever.

The catch is "any". The step does not start from reset; it starts from whatever states
the solver likes, reachable or not, as long as P holds in them. If P is "the outputs match
the spec", the solver picks a device state and a spec state that agree right now and
disagree next cycle, and the step fails. That is not a bug, and SymbiYosys says so: base
case pass, induction fail, status UNKNOWN. On this design that is exactly what happens
without the invariants (`results/proof.json`), and raising k to 12 did not help after 15
minutes (*measured once*), because no amount of history fixes a wrong starting state.

A strengthening invariant is an extra property, true of all reachable states, that you
prove alongside P to rule the bad starting states out. Here they are a refinement map
(`formal/invariants.svh`): the device's registers equal the spec shadow's, the frame
position corresponds, the FIFO pointers are consistent with the count, entry i from the
read pointer equals entry i of the shadow's queue. With those, one step of induction is
enough, because both sides are deterministic functions of corresponding state and the same
inputs. PASS in about five seconds, for all 256 divisors.

The best single example is the one the first attempt failed on. The device's receive
parity-error flag can only be set on a frame with parity, and the RTL relies on that: it
does not gate the flag again when it builds the FIFO entry. The shadow does gate it. From
reset they agree forever. From the solver's chosen state, with the flag set and parity
off, they differ in one cycle. The fix is one line: `rx_par_en || !rx_perr`. True, not
what I set out to prove, and the proof does not go through without it.

## 6. How do you know the proof is not vacuous?

Three ways. The environment assumptions (`formal/env.svh`: reset in the first cycle,
legal APB) are the same file for the proof and for the mutant runs, and under them ABC
produces 802 concrete counterexamples on mutants, so they are satisfiable and do not
constrain the interesting behaviour away. The base case and the bounded search of the
unmutated design pass, while mutants of the same netlist fail the same assertions. And the
proof without the invariants fails its induction step on a named assertion
(`a_rd_status`), which it could not do if the assertions were trivially true.

## 7. What is an equivalent mutant, how did you classify them, and what about the ones you could not?

A mutation that changes no behaviour at the ports, such as a bit that is only ever loaded
with the value it is stuck at. Counting those as missed punishes every technique equally
and hides the real gap, so every unkilled mutant goes to a miter against the unmutated
design, under the same environment assumptions: ABC signal correspondence, a bounded
search, then PDR. 56 were proved equivalent, each in under three seconds, and leave every
denominator.

Four were neither killed nor proved. They stay in and count against every arm, which is
the conservative direction. I have an argument that each is unobservable from reset (for
example `rx_slot == 10` with bit 2 ignored is also true for 14, which the receiver never
reaches), but an argument is not a proof, and `docs/SURVIVORS.md` labels them "argued, not
proved". The reason PDR does not close them is the same as question 5: they are
equivalent only on reachable states, so the proof needs an invariant the engine has to
discover.

Safety net: every *killed* mutant also gets the bounded half of the miter. One coming
back "equivalent" would mean simulation and formal disagree about the same netlist, and
halts the run. It fired zero times.

## 8. Why budgets in cycles, and why is the union over seeds not your headline?

Random stimulus with unlimited time beats anything, so the budget has to be fixed before
the run and equal across arms. Cycles are the natural unit for simulation and are
machine-independent. Random gets exactly the directed suite's 11,690 cycles. For formal
the budget is a search depth, not seconds: I first used 60 seconds per mutant and the same
run reached depth 27 to 29 depending on what else the laptop was doing, so the score
would have drifted between runs.

The union over ten seeds has ten times the budget. At equal cycles the union kills 927,
which would put random ahead of directed's 918; the honest per-seed mean is 914.3, just
behind. Both numbers are in the results; only one is the headline.

## 9. Yosys mutates the elaborated netlist and renames everything. How does the bench survive that?

It only touches top-level ports, and it never rebuilds per mutant. `mutate -ctrl` puts
every mutant of a sample into one netlist behind a 16-bit `mutsel` input; 0 is the
original design. One Verilator build per sample, one simulator process per (mutant, test,
seed), `mutsel` from an environment variable, so no state leaks between runs. The formal
property file is port-only for the same reason, which is also why the white-box invariants
live in a separate file used only on the original RTL. Two details that mattered:
`pmuxtree` before mutating, so the simulator and the solver cannot disagree about a mutant
that makes two selects hot; and `memory_map`, so FIFO storage is flops that
`write_verilog` can emit.

## 10. What is your functional coverage model and what did closure tell you?

98 bins, each a behaviour the spec singles out: every register access and error access,
FIFO level at each push, frame formats, divisor ranges, data patterns, every interrupt
source raised and cleared, six same-edge corner cases, eight mid-frame events
(`bench/tb/coverage.py`). It is sampled from the reference model's event record, on the
unmutated design, because it measures the stimulus and not the device.

Random closes all 98 bins on every seed, between cycle 7,412 and cycle 76,926, and at the
equal budget seeds have 90 to 98. The lesson is what closure does *not* tell you: the
directed suite has all 98 bins and 100% line coverage and still misses 26 mutants; random
keeps killing new mutants after it has closed; and the three reset bugs that only formal
found correspond to a bin nobody wrote ("bus transfer in flight as reset is released").
Coverage tells you what you thought of. The smoke test has 71% line coverage and a 48.2%
mutation score, which is the usual argument against reading line coverage as a quality
number.

## 11. How did you keep yourself from tuning the tests to the bugs?

Two samples and a frozen plan. 200 development mutants were fair game while the bench was
built. The question, arms, budgets, kill rule, treatment of equivalents, metric and seven
predictions were committed in `docs/PREREG.md`, and only then were the 1,000 confirmatory
mutants drawn, once. `harness/guard.py` refuses to draw them unless the plan is marked
frozen and every file the score depends on is committed; it records the commit and a hash
of each of those files, and `tests/test_guards.py` fails if any of them changes later. The
directed suite was written from the spec and a test plan by someone who had seen no
mutant, no mutant result and no RTL, and was closed to coverage before it met a mutant.

One prediction was wrong, and is reported as wrong: I predicted formal would kill nothing
that simulation missed, and it killed three. Everything done after the sample was opened
(the survivor analysis, a longer proof attempt, structural coverage) is in
`docs/DEVIATIONS.md`, labelled post-hoc.

## 12. Walk me through the bench. Is it UVM?

It is UVM-style, in Python: pyuvm on cocotb, Verilator underneath. `ApbItem` and
`RxFrameItem` are sequence items. An APB agent (sequencer, driver, monitor) and a UART
agent (a driver for `rxd`, a monitor decoding `txd`) sit in an environment with a
scoreboard; tests derive from a base test that resets, starts sequences on the sequencers
and ends at the first mismatch or the budget; the harness picks the test by name. Directed
stimulus is sequences built on small helper bases; the random test runs an APB sequence
(weighted operations from one reviewable table of knobs) alongside a sequence playing the
far end of the serial line, sharing what the device was last programmed with. Timing rule
throughout: drive on the falling edge, sample after ReadOnly, never assign after ReadOnly.

It is not SystemVerilog UVM and I do not call it that: no virtual interfaces or config
database, no factory overrides, no register layer, no constraint solver, and a two-state
simulator. No free simulator on my machine runs SystemVerilog UVM. What transfers is the
architecture and the discipline, not the library.

## 13. What did the surviving mutants teach you?

That each technique's misses look like its author. The directed suite's 26: twelve in the
baud counters, because I, or rather the test plan, thought "small divisors plus one
realistic and one large" was enough, and no divisor used has bit 4, 5 or 6 set. One of
those I checked by hand: it scrambles the order the counter visits its values, and at
divisor 137 the scrambled walk still takes exactly 138 cycles, so even the large-divisor
test cannot see it. Two address aliases outside my list of unmapped addresses. Two
cross-register interference bugs hidden by always writing a register just before using
it. Random's misses are alignments it did not happen to hit in the budget; ten times the
cycles takes it from 96.9% to 99.0%. Formal's misses are all depth and divisor. And the
three formal-only kills are a hole in the *environment* every test shared: nobody resets
the device while the bus is busy.

## 14. How did the spec and the RTL make this verifiable?

The spec is written at the clock edge: every rule is about pre-edge values, and one
section lists every same-edge ordering (push when full while popping, set against
write-one-to-clear, a config write at a frame start). That is what let two people
implement it independently and agree, and what lets a scoreboard compare every cycle.
Synchronous reset with a reset value on every flop keeps the two-state simulator and the
solver honest about initial state. A bit period of `div + 1` clocks, so divisor 0 is one
clock per bit, keeps a whole loopback round trip near 20 cycles, inside a depth-25
search; a 16x oversampling UART would have needed hundreds. In the RTL the FIFO is
deliberately dumb and the top level decides legality on pre-edge counts, which makes the
same-edge rules structural instead of case-by-case.

## 15. What would a professional bench have that this one does not?

The full list is `docs/GAPS.md`. The ones that matter most: a commercial four-state
simulator and real SystemVerilog UVM with a constraint solver; concurrent assertions and
`bind`; checkers that are transaction-level and therefore imperfect, which is where real
escapes come from and which this project deliberately does not study; a richer fault
model than single-point netlist mutations; more than one clock domain, asynchronous
inputs and gate-level timing; regression infrastructure; and a verification plan reviewed
by someone who did not write the design. And scale: an unbounded proof against a complete
specification shadow is only practical because the block has 184 flops.
