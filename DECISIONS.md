# Decisions

Each entry: what was chosen, what was rejected, and the number that decided it. Numbers
quoted from the scored samples are in `results/`; engineering measurements (timings taken
while the harness was built) are marked *measured once* and are not regenerated.

## 1. Write the device, rather than verify someone else's

**Chosen:** a small APB UART with two FIFOs, written here to a spec written first
(`docs/SPEC.md`). **Rejected:** verifying a permissively licensed open-source block. The
best candidate found (a Tiny Tapeout APB UART, Apache-2.0) already ships a cocotb suite
and SymbiYosys proofs and hides its APB port behind a pin adapter, so the work would have
been derivative and spent dodging its tests. **The number:** lines of hardware description
language in the project pool before this: 0.

The cost of this choice is that one desk wrote the spec, the design and the bench. Two
things push back on that: the bugs are mechanical (entry 2), and the design and both
checkers were written in separate passes from the spec alone (entry 6).

## 2. Mechanical bugs, not planted ones

**Chosen:** Yosys `mutate`, seeded, on the elaborated netlist, all five modes.
**Rejected:** hand-planted bugs, which measure whether the test author can find the bugs
the test author thought of. **The number:** 1,000 confirmatory mutants, none placed by
hand; the seed was committed before they were drawn.

## 3. One netlist for all mutants

**Chosen:** `mutate -ctrl mutsel 16 k`: every mutant sits behind a top-level select input,
`mutsel = 0` is the unmutated design. This is the method of YosysHQ's MCY; none of MCY's
code is used. **Rejected:** one netlist and one Verilator build per mutant. **The
number:** one build of about 20 seconds per sample instead of 1,000 of them (*measured
once*: roughly five and a half hours saved per confirmatory run).

Side benefit: the unmutated design inside the same netlist is the golden run, so "the
same test passes on the original" is checked on the very file the mutants live in.

## 4. `pmuxtree` before mutating

Yosys keeps parallel multiplexers whose behaviour is undefined when two selects are hot.
`write_verilog` renders them as a priority `casez`; the solver back end renders them its
own way. A mutation can make two selects hot. **Chosen:** lower them to ordinary mux
trees first, so simulation and formal cannot disagree about a mutant. **Rejected:**
trusting the two back ends to agree. **The number:** the consistency gate (a mutant both
killed in simulation and proved equivalent) fired 0 times.

## 5. One checker for every simulation arm

**Chosen:** a cycle-accurate reference model in lockstep, compared on every output every
cycle, identical for directed and random tests. **Rejected:** per-test expected values
for the directed suite and a transaction-level scoreboard for random. That would measure
two things at once (stimulus and checker) and the checker differences would be my own
choices. **The consequence, stated rather than hidden:** a bug is detected exactly when
it reaches a port, so every arm is an upper bound on its real-world counterpart, and the
"propagated but not detected" class that mutation tools report is empty by construction.

## 6. Three implementations of the spec, written apart

The RTL, the Python model and the Verilog specification shadow were written in separate
passes, each from `docs/SPEC.md` alone and before the others were opened
(`notes/INTEGRATION.md`). **The numbers:** 0
lockstep mismatches between RTL and model at first contact and since; the RTL is proved
equal to the shadow for all time. The notes from the RTL pass and the model pass flag the
same four ambiguous sentences, resolved the same way.

## 7. Equal cycles, mean over seeds

**Chosen:** the random arm gets exactly the directed suite's 11,690 cycles per seed, and
its reported score is the mean over ten seeds. **Rejected:** wall-clock budgets (machine
dependent), and the union over seeds (ten times the budget). **The number:** on dev the
union at equal budget kills 183 where the mean is 179.6; quoting the union would have
moved random from just behind directed (180) to ahead of it.

Each seed is run once to ten times the budget and stops at the first mismatch, so the
kill cycle answers "killed within B cycles?" for every B. That is where the curve comes
from, at no extra simulation cost.

## 8. A development sample and a confirmatory sample

**Chosen:** 200 mutants (seed 1) to build against and look at freely; 1,000 mutants
(seed 20260919) drawn once after `docs/PREREG.md` was frozen, guarded in code
(`harness/guard.py`) and by tests. **Rejected:** one sample, which would have let harness
and bench choices leak into the headline. **The number:** dev had every arm within a few
mutants of the ceiling (180, 179.6 and 184 of 186), so the confirmatory sample was made
five times larger to have enough hard mutants to tell arms apart.

## 9. Equivalent mutants are proved, not guessed, and the doubtful ones stay in

**Chosen:** a miter of each unkilled mutant against the unmutated design, ABC `scorr`
then bounded search then PDR. Proved-equivalent mutants leave every denominator;
unresolved ones stay in as survivors. **Rejected:** counting every survivor as a miss
(punishes all arms equally and hides the gap), or dropping unresolved ones (flatters all
arms). **The number:** 14 of 200 dev mutants are proved equivalent, so raw scores would
understate every arm by about 7 points. Every successful proof took under half a second.

## 10. ABC for the mutant runs, z3 only for the one proof

**Chosen:** build ABC from a pinned commit inside the project and drive it directly.
**Rejected:** z3 through SymbiYosys for everything, which is what the free toolchain
offers out of the box. **The numbers (*measured once*):** z3 reached depth 14 of the
equivalence miter in 15 minutes; ABC `bmc3` reaches depth 25 of the property check in
about 19 seconds and finds a typical counterexample in under a second.

## 11. Formal budgets are depths, not seconds

**Chosen:** `bmc3 -F 25`; the time limit is only a safety net that flags. **Rejected:**
"60 seconds per mutant", which I used first. It made the score depend on how busy the
laptop was: the same run reached depth 27 to 29 depending on load. **The number:** two
back-to-back runs at `-F 25` gave identical verdicts and identical frame numbers.

## 12. A complete property set

**Chosen:** a specification shadow that predicts every output every cycle, with one
assertion per output, port-only so it applies to mutants. **Rejected:** a hand-picked
list of partial properties, whose coverage of the spec would be one more thing I chose.
With a complete set the formal arm, like the simulation arms, varies only in how it
explores inputs. The shadow is a third statement of the spec, not a copy of the RTL:
queues shift instead of using pointers and the frame position is a (slot, cycle) pair.

## 13. The unbounded proof, and the invariant it needed

The original design is proved equal to the shadow on every output, for all time and all
256 divisors, by k-induction with refinement invariants (`formal/invariants.svh`).
**The numbers:** with the invariants, PASS in about 5 seconds. Without them, UNKNOWN at
induction depth 2, and still UNKNOWN at depth 12 after 15 minutes (*measured once*).

The first attempt with the correspondence invariants alone failed induction on
`IRQ_STAT`. The solver started from a state in which the receiver's parity-error flag was
set on a frame without parity. The design never gates that flag again when it builds the
FIFO entry, because it cannot be set without parity; the shadow does gate it. From reset
that state is unreachable, so both agree forever, but induction does not start from
reset. One line (`rx_par_en || !rx_perr`) closed the proof. That is the whole idea of a
strengthening invariant in one example: true, not what you set out to prove, and needed.

## 14. Divisor restricted to 0 and 1 in the mutant search, unrestricted in the proof

A frame lasts `10 * (div + 1)` cycles. At depth 25 only divisors 0 and 1 let a frame
finish, so allowing more would spend the search on sequences that cannot reach a port.
**The cost, known in advance:** the formal arm is blind to logic that only matters above
divisor 1 (the upper bits of the baud counters, the start-bit check). The proof of the
original has no such restriction, and the equivalence miter does not either.

## 15. Pin the pre-reset state for ABC

**Chosen:** `setundef -zero -init` before writing the AIGER file. Reset is assumed in the
first cycle and nothing is checked during it, so the pre-reset state cannot matter.
**Rejected:** leaving it free, which is SymbiYosys's default. **The numbers (*measured
once*):** with a free initial state `scorr` merged 1 of 413 registers of the miter and a
true equivalent was still undecided after 10 minutes; pinned, it merges them down to 171
for a real mutant and proves a true equivalent in 0.15 seconds.

## 16. Functional coverage is sampled from the reference model

**Chosen:** 98 bins, each a behaviour the spec singles out (register accesses, FIFO
levels at push, frame formats, divisor ranges, every interrupt source raised and cleared,
the six same-edge corners, eight mid-frame events), sampled from the model's event record
on the unmutated design. **Rejected:** sampling device internals (breaks on mutants) and
structural coverage as the closure metric (says what ran, not what was exercised).
Verilator line and toggle coverage of the original RTL is reported as a supplement
(`results/structural.json`).

## 17. The directed suite was written blind

It was written from the spec and a test plan (`docs/TESTPLAN.md`) without opening any
mutant, mutant result or the RTL, closed to the functional coverage model, and only then
run against mutants. **The number:** 16 tests, 11,690 cycles, all 98 bins.

## 18. A spec made for bounded reasoning

Synchronous reset with a reset value on every flop (no X, no `async2sync`), and a bit
period of `div + 1` clocks so that divisor 0 is one clock per bit. **The number:** a byte written, sent, looped back, received and read out again takes
about 20 cycles from reset at divisor 0, inside the depth-25 search. A
conventional 16x oversampling UART would have needed a depth of several hundred.
