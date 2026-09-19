# coverpoint

A verification bench for a small bus peripheral, and one measured answer: **when the bugs
are generated mechanically instead of planted by whoever wrote the tests, how many does
each verification technique catch, and what does it cost?**

The device is `cp_uart`, an APB3 UART with a transmit FIFO, a receive FIFO and one
interrupt, written in SystemVerilog to a spec fixed at the clock-cycle level
(`docs/SPEC.md`). Around it:

- a UVM-style bench in Python (pyuvm on cocotb, Verilator underneath): sequence items,
  sequencers, drivers, monitors, an environment, a lockstep scoreboard against an
  independently written reference model, a 98-bin functional coverage model, a 16-test
  directed suite and a constrained-random test;
- a formal side: a port-only property set, and an **unbounded proof that the design
  matches its specification on every output, for all time and all 256 baud divisors**
  (k-induction with refinement invariants: PASS. Without the invariants the same proof
  returns UNKNOWN, which is the point of `DECISIONS.md` entry 13);
- a harness that samples single-point mutants of the design with Yosys, scores every
  technique against them on a fixed budget, proves which mutants are equivalent, and
  regenerates every number below from one command.

The plan (`docs/PREREG.md`) was committed before the scored mutants were drawn, and the
harness refuses to draw them otherwise.

## The result

Confirmatory sample: 1,000 mutants, drawn once. 56 were proved equivalent to the original
design and removed from every denominator, leaving 944.

| technique | killed | survived | mutation score | 95% interval | simulated cycles |
|---|---:|---:|---:|---|---:|
| one smoke test (a byte through loopback) | 455 | 489 | 48.2% | 45.0% to 51.4% | 77 |
| directed suite, 16 hand-written tests | 918 | 26 | **97.2%** | 96.0% to 98.1% | 11,690 |
| constrained-random, equal cycles (mean of 10 seeds) | 914.3 | 29.7 | **96.9%** | seeds: 907 to 924 killed | 11,690 |
| constrained-random, ten times the cycles (mean of 10 seeds) | 934.3 | 9.7 | 99.0% | seeds: 933 to 937 killed | 116,900 |
| formal, bounded: every legal input sequence 25 cycles deep, divisor 0 or 1 | 802 | 142 | **85.0%** | 82.5% to 87.1% | not applicable |
| any simulation arm | 937 | 7 | 99.3% | | |
| any arm | 940 | 4 | 99.6% | | |

Formal has no cycle count. Its cost on this machine was 3,780 solver-seconds for the 1,000
mutants (median counterexample 7 cycles long, deepest 24); the directed suite took 129
seconds of wall-clock on eight workers and the ten long random seeds 1,066. Those are
costs on one laptop, not budgets, and are not regenerated.

### What the numbers say

1. **Directed and constrained-random are indistinguishable at equal cycles.** 97.2%
   against 96.9%, and the directed score sits inside the spread of the random seeds (907
   to 924 killed, against 918). The plan said in advance that this outcome would be
   reported as "no measurable difference at this budget". That is the headline.
2. **They do not kill the same mutants.** On each seed, 3 to 17 mutants are killed by the
   directed suite and not by random, and 5 to 9 the other way round. Together the
   simulation arms reach 99.3%.
3. **Random gets there sooner, then directed catches up.** After 1,000 cycles random has
   killed 830 mutants on average and the directed suite 720; after 3,000, 888 against
   770. The reason is order, not quality: the directed suite runs its transmit tests
   first and does not touch the receiver until cycle 3,122, while random stimulus works
   both sides from the first cycle. The suite draws level once its receive tests have run.
4. **The bounded formal search is fast and shallow.** Every one of its 802 kills is a real
   counterexample from reset, at most 24 cycles long. What it misses is structural, and
   was named in the plan before the sample was drawn: 49 mutants need a baud divisor above
   1, and 89 need more than 25 cycles to reach a port (`docs/SURVIVORS.md`).
5. **Formal found three bugs that no simulation arm did**, which the plan predicted it
   would not. All three are wrong reset values that only show when a bus transfer is in
   flight as reset is released. No test in the bench resets the device with the bus busy,
   and the coverage model has no bin for it. The solver is not told when to reset.
6. **Coverage closure is not the finish line.** The directed suite hits all 98 functional
   coverage bins and 100% of lines, and still misses 26 mutants. Random stimulus closes
   all 98 bins on every seed (between cycle 7,412 and cycle 76,926) and keeps finding
   mutants afterwards. The smoke test covers 71% of lines and kills 48.2% of mutants.
7. **What the survivors are.** Of the directed suite's 26 survivors, 12 are stuck or
   conditionally flipped bits in the baud counters that the suite's divisors (0 to 7, 15
   and 137) do not expose, two are address aliases at `0x84` and `0x88` that its 14
   unmapped addresses do not include, two are cross-register interference that its habit
   of writing a register immediately before relying on it hides, three are data- and
   timing-dependent corruption of a FIFO slot, and three are the reset-value mutants of
   finding 5. The last four survive everything: each is argued to be unobservable from
   reset, none was proved so inside the budget, and all four are counted against every
   arm. Every one of them has a line in `docs/SURVIVORS.md`.

### Kills and coverage against cycles

| cycles | directed killed | random killed (mean) | random coverage bins (mean, of 98) |
|---:|---:|---:|---:|
| 100 | 225 | 486.1 | 25.5 |
| 300 | 392 | 646.1 | 41.3 |
| 1,000 | 720 | 830.4 | 66.1 |
| 3,000 | 770 | 887.7 | 85.3 |
| 11,690 | 918 | 914.3 | 94.9 |
| 30,000 | 918 | 924.8 | 97.3 |
| 116,900 | 918 | 934.3 | 98.0 |

### The predictions, scored

Seven predictions were written into `docs/PREREG.md` from the 200-mutant development
sample. Six held. One was wrong.

| # | prediction | outcome |
|---|---|---|
| 1 | directed and random within 2 points at equal cycles; inside the seed spread means "no measurable difference" | held: 0.3 points, inside the spread |
| 2 | formal kills fewer than either simulation arm, for two named structural reasons | held: 85.0%, and 138 of its 142 misses fall under the two reasons |
| 3 | formal's median counterexample is under 10 cycles | held: 7 |
| 4 | at least 80% of the mutants nothing kills are proved equivalent | held: 56 of 60 |
| 5 | random reaches a mean of 93 bins by 11,690 cycles and closes on at least eight seeds | held: 94.9, ten of ten |
| 6 | the smoke test kills 40% to 55% | held: 48.2% |
| 7 | formal kills nothing that every simulation arm misses | **wrong: three mutants** (finding 5) |

## What this measures, and what it does not

Every simulation arm shares one checker, a cycle-accurate reference model compared with
the device on every output in every cycle, and the formal arm's property set fixes every
output in every cycle too. So a bug is caught exactly when the stimulus, or the solver's
search, makes it reach a port. **The experiment measures stimulus reach with the checker
held constant.** Every arm is therefore an upper bound on its real-world counterpart: a
real directed test has hand-written checks, which are usually its weak point, and a real
property set is never complete.

Mutation score is also not a bug-finding rate. Single-point netlist mutations measure how
much of the logic the verification would notice being wrong. Real bugs are more often a
misread spec implemented faithfully.

`docs/GAPS.md` lists plainly what a professional bench has that this one does not. The
short version: a commercial four-state simulator and real SystemVerilog UVM, concurrent
assertions, a constraint solver, transaction-level checkers, richer fault models, more
than one clock, and someone else reviewing the plan.

## How the score is kept honest

- **Nobody chose the bugs.** `yosys mutate`, seeded, all five modes, on the elaborated
  netlist. All mutants of a sample live in one netlist behind a `mutsel` input (the method
  of YosysHQ's MCY), so the bench can only ever touch top-level ports.
- **Two samples.** 200 development mutants were looked at freely while the bench and
  harness were built. The 1,000 confirmatory mutants were drawn after the plan was
  frozen. 69 mutants appear in both; they are not removed.
- **Equal budgets, fixed in advance.** Random gets exactly the directed suite's cycles.
  The headline is the mean over ten seeds; the union over seeds has ten times the budget
  and is labelled wherever it appears. Formal budgets are depths, not seconds, so the
  outcome does not depend on the machine.
- **Equivalent mutants are proved, not guessed.** Each unkilled mutant goes to a miter
  against the original design (ABC: signal correspondence, bounded search, then PDR).
  Proved equivalents leave every denominator. The unresolved ones stay in and count
  against every arm. Every killed mutant gets the bounded half of the same check; one
  that came back "equivalent" would halt the run. None did.
- **The directed suite was written blind**: from the spec and a test plan
  (`docs/TESTPLAN.md`), without sight of any mutant, any mutant result or the RTL, and
  closed to the coverage model before it met a mutant.
- **The design and its checkers were written apart.** RTL, Python reference model and
  formal specification shadow each came from the spec alone. First contact: zero
  mismatches, and then the proof (`notes/INTEGRATION.md`).
- **Deviations are logged** in `docs/DEVIATIONS.md`, and a test fails if any frozen file
  changes after the confirmatory sample was opened.

## Reproduce

```
make reproduce
```

Builds the tools, proves the design, redraws both mutant samples, re-runs every arm,
prints the tables above, and exits non-zero if any outcome differs from the committed
`results/` or if any number quoted in this README, `DEFENSE.md` or
`docs/RESUME-BLOCK.md` no longer matches (`docs/CITED.json`). About 70 minutes on an
eight-core laptop once the tools are built.

```
make test       # 300-odd reference-model tests, the pre-registration guards, the cited-number check
make prove      # the unbounded proof, with and without the invariants (about 10 seconds)
make lint       # Verilator -Wall on the RTL, zero waivers
```

Everything is project-local and nothing is installed globally: a Python venv (cocotb
2.1.0, pyuvm 5.0.0, cocotb-coverage 2.0, Yosys 0.69 and SymbiYosys from the YoWASP wheels,
z3), a conda prefix holding only Verilator 5.052, and ABC built from a pinned commit into
`.tools/` (about nine minutes with the system C compiler, 8 MB download). The first build
needs network for pip, conda-forge and one GitHub tarball.

## Layout

```
docs/SPEC.md            the device contract, to the clock edge
docs/PREREG.md          the plan, frozen before the confirmatory sample (+ prereg.json)
docs/DEVIATIONS.md      what was done differently, and everything done afterwards
docs/SURVIVORS.md       every surviving mutant, one line each
docs/TESTPLAN.md        spec rule -> directed test
docs/GAPS.md            what a professional bench would have
docs/RESUME-BLOCK.md    proposed résumé block (a proposal; nothing else was touched)
DECISIONS.md            each choice, the alternative, the number that decided it
DEFENSE.md              fifteen interview questions, answered from the code
rtl/                    cp_uart.sv, cp_fifo.sv
bench/model.py          cycle-accurate reference model (no imports)
bench/tb/               pyuvm agents, scoreboard, coverage, sequences, tests
formal/                 property set, environment assumptions, refinement invariants
harness/                mutants, simulation, formal, equivalence, scoring, report
results/                committed outcomes; regenerated and compared by make reproduce
tests/                  reference-model tests and the honesty guards
```

## Wording

The bench is UVM-style, in Python (pyuvm) on cocotb. It is not SystemVerilog UVM. Nothing
here has been near silicon. The properties are immediate assertions over auxiliary state,
not concurrent SVA. "Proved" means proved under the environment assumptions in
`formal/env.svh` (reset first, legal APB).

## Tools and licences

The RTL, bench and harness are original to this repository. Tools are used unmodified:
Yosys and SymbiYosys (ISC), Verilator (LGPL-3.0 or Artistic-2.0), cocotb (BSD-3-Clause),
pyuvm (Apache-2.0), cocotb-coverage (BSD-2-Clause), z3 (MIT), ABC (UC Berkeley,
BSD-style). The one-netlist mutation method is that of YosysHQ's MCY (ISC); none of its
code is used. AMBA APB is an Arm specification; only the public protocol is implemented.
