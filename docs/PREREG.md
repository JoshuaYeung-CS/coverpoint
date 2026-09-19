# Pre-registration

Written and committed before the confirmatory mutant sample was drawn. The machine-readable
half is `docs/prereg.json`; the harness reads every parameter from there and refuses to
draw the confirmatory sample unless that file says `frozen` and everything the score
depends on is committed (`harness/guard.py`). After this commit, this file and
`prereg.json` do not change. Anything done differently goes in `docs/DEVIATIONS.md`.

## The question

Three ways of verifying the same small peripheral are pointed at the same mechanically
generated bugs. How many does each catch, and what does it cost?

- a hand-written **directed** suite,
- **constrained-random** stimulus with a functional coverage model,
- **formal**: a bounded search over every legal input sequence against a complete
  property set.

## What is held constant, and what that means

All simulation arms share one checker: a cycle-accurate reference model stepped in
lockstep with the device and compared on every output in every cycle. The formal arm's
property set is a complete specification shadow that fixes every output in every cycle.
So in every arm, a bug is caught if and only if the stimulus (or the solver's search)
makes it reach a port. **The experiment measures stimulus reach, with the checker held
constant.** It follows that every arm is an upper bound on its real-world counterpart: a
real directed test has hand-written checks, which are usually its weak point, and a real
property set is never complete. That is stated here so it is not mistaken for a finding.

## The bugs

Single-point mutations of the elaborated design from Yosys `mutate`, sampled by seed, all
five modes (`inv`, `const0`, `const1`, `cnot0`, `cnot1`), after
`prep -flatten; memory_map; pmuxtree; opt_clean`. Nobody chose where they go. All mutants
of a sample live in one netlist behind a 16-bit `mutsel` input; `mutsel = 0` is the
unmutated design. The bench touches only top-level ports.

| sample | seed | mutants | role |
|---|---|---|---|
| dev | 1 | 200 | development: looked at freely while the bench and harness were built |
| confirmatory | 20260919 | 1000 | drawn once, after this commit |

The two samples may share mutants (the design has a finite number of mutation sites).
The overlap is reported by mutant key and not removed.

## The arms and their budgets

| arm | what runs | budget |
|---|---|---|
| baseline | the single `smoke` test (one byte through loopback) | its length, 77 cycles |
| directed | the 16 tests of `bench/tb/directed.py`, in the order listed in `prereg.json` | their total, 11,690 cycles |
| constrained-random | `random_mix`, knobs as committed in `bench/tb/random_seqs.py`, seeds 0 to 9 | **11,690 cycles per seed** (equal to the directed suite) |
| constrained-random, long | the same ten runs continued | 116,900 cycles per seed, reported as a curve |
| formal | ABC `bmc3` on `formal/cp_uart_props.sv` plus the mutant | **25 clock cycles deep**, baud divisor restricted to 0 and 1 |

Budgets are simulated cycles and search depth, never seconds, so the outcome does not
depend on the machine. Wall-clock is recorded as cost only. A formal run that hits its
900-second safety timeout before reaching depth 25 is reported as `TIMEOUT` and is not a
kill.

## What "killed" means

A mutant is **killed by a simulation arm** when the lockstep scoreboard reports a
mismatch within the budget with that mutant switched on, and the identical test and seed
finishes with no mismatch on `mutsel = 0`. It is **killed by the formal arm** when ABC
returns a counterexample from reset within the depth. `UNDECIDED` (no counterexample
within the depth) is not a kill and not a pass; it is its own column.

For the constrained-random arm the reported number is the **mean over the ten seeds** of
the per-seed kill count, with the per-seed range. The union over seeds is reported too,
labelled as such; it has ten times the budget and is not the headline.

Validity gates, any of which stops the run: every test and every seed passes on
`mutsel = 0`; the formal arm finds no violation on `mutsel = 0`; the original design is
proved against the property set for all time and all divisors by k-induction
(`harness/prove.py`); no mutant is both killed and proved equivalent.

## Equivalent mutants

Some mutants change no behaviour at the ports; counting them as missed would punish
every arm equally and hide the real gap. Every mutant that **no arm killed** (including
the long random runs) goes to an equivalence miter against the unmutated design, under
the same environment assumptions as the formal arm but with no divisor restriction:
ABC `scorr`, then `bmc3` to 30 cycles, then `pdr`. Verdicts:

- **equivalent**: proved equal at the ports for all time. Removed from every arm's
  denominator.
- **different**: a counterexample exists. Stays in; it is a survivor of every arm.
- **unresolved**: neither. Stays in, counted as a survivor. This is the conservative
  choice: it can only lower every arm's score.

Every killed mutant also gets the bounded half of the miter (30 cycles, no proof
attempt). For the unkilled ones the proof attempt has a 300-second cap; one that does not finish leaves the
mutant unresolved, which is the conservative direction. On dev every proof that succeeded
took under half a second. A killed mutant can only come back `different` or `unresolved`; `equivalent` would mean the
harness is wrong, and halts the run.

## Primary metric and comparisons

**Mutation score = killed / (mutants - proved equivalent)**, per arm, with a Wilson 95%
interval over mutants. Reported for every arm alongside survivors and cycles.

Primary comparison: **directed against constrained-random at equal cycles**, as the
difference between the directed score and the mean per-seed random score, with the
per-seed paired counts (killed by one and not the other).

Secondary: the formal arm against both; the kills-against-cycles curve at
100, 300, 1,000, 3,000, 11,690, 30,000 and 116,900 cycles; the functional coverage
closure curve (98 bins, `bench/tb/coverage.py`) for the ten seeds on `mutsel = 0`, the
cycle at which each seed closes all bins, and the directed suite's cumulative coverage.

Every mutant that survives everything is explained in one line in the README.

## Predictions, made from the dev sample

Dev sample, 200 mutants, 14 proved equivalent, so 186 scored: smoke 92; directed 180;
random at 11,690 cycles a mean of 179.6 over ten seeds (178 to 183); random at 116,900
cycles a mean of 184.0; formal at depth 25 kills 159, median counterexample 7 cycles; one
mutant survives everything and is unresolved. Random stimulus reached 90 to 98 of the 98
coverage bins by 11,690 cycles (mean 94.9) and closed all 98 on all ten seeds between
cycle 7,412 and cycle 76,926.

1. Directed and random at equal cycles land **within 2 percentage points** of each
   other. If the difference is smaller than the per-seed range of the random arm, the
   result is "no measurable difference at this budget" and is reported in those words.
2. The formal arm kills **fewer** mutants than either simulation arm, and the ones it
   misses are of two known kinds: mutants in logic that only matters for divisors above 1
   (the search is restricted to 0 and 1), and mutants that need more than 25 cycles to
   reach a port (third and fourth FIFO entries on the receive side, overruns). This is a
   structural limit stated in advance, not a discovery.
3. The formal arm's median counterexample is **under 10 cycles**.
4. Of the mutants nothing kills, **at least 80% are proved equivalent** (dev: 14 of 15).
5. Random stimulus reaches **a mean of at least 93 of 98** coverage bins by 11,690
   cycles, and closes all 98 on **at least eight of the ten seeds** by 116,900. (The seeds
   are the same as on dev and coverage is collected on the unmutated design, so this is a
   check that the confirmatory netlist behaves like the dev one, not an independent
   prediction. It is listed so that the closure curve has a stated expectation.)
6. The single smoke test kills **between 40% and 55%** of scored mutants.
7. The formal arm kills **no mutant that every simulation arm misses** (dev: none). If it
   does, those mutants are the most interesting line in the result and are listed.

What would count as a null: prediction 1's "no measurable difference". It is an
acceptable result and would be the headline if it happens.

## What changed after the dev sample was first scored

The dev sample was scored several times while the harness was being built. Between the
first dev scores and this commit:

- `bench/tb/coverage.py`: the report dropped two coverpoints (14 of 98 bins) because of
  a name filter. Fixed. Coverage never influences a kill.
- `bench/model.py`: two read-only properties (`last_tx_byte`, `last_rx_byte`) added for
  the coverage collector. No behaviour changed; the 303 model tests pass unchanged.
- The formal and equivalence harness moved from z3 (through SymbiYosys) to ABC, because
  z3 reached depth 14 in 15 minutes on this machine. Budgets moved from seconds to depth.
- The property file was split into `shadow.svh` / `asserts.svh` so the same text serves
  the black-box mutant runs and the white-box proof; its queue logic was rewritten
  without variable shifts. Same properties.
- `rtl/`: formal-only hooks inside `ifdef CP_FORMAL_WHITEBOX`. Never defined in
  simulation, synthesis or mutation, so the mutated design is unchanged; the dev sample
  came out identical mutant for mutant.

No directed test, no random knob, no sequence and no property was changed in response to
any mutant result. The directed suite was written from the specification and the test
plan by someone who had not seen any mutant or any mutant result, and was closed to the
functional coverage model (three receive-error cases added) **before** it was run against
any mutant.

## Tool versions

Recorded because the mutant sample depends on Yosys and the verdicts on the solvers:
Yosys 0.69 (`yowasp-yosys==0.69.0.0.post1233`), Verilator 5.052, cocotb 2.1.0,
pyuvm 5.0.0, cocotb-coverage 2.0, z3 (`z3-solver==5.1.0.0`), ABC at commit
`3660a63a392b276616dd56ffee7e47b29b5df95e`.
