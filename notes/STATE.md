# State

Last updated 2026-11-05.

## Where it stands

Round 1 is complete. The plan was frozen at `9cc02e7`, the confirmatory sample (1,000
mutants, seed 20260919) was opened once at that commit, and the results are committed as
produced.

- 56 mutants proved equivalent, 944 scored.
- Smoke test 48.2%; directed suite 97.2%; constrained-random at equal cycles 96.9% (mean
  of ten seeds, 907 to 924 killed against the suite's 918): the pre-registered null, "no
  measurable difference at this budget". Random at ten times the cycles 99.0%.
- Formal, bounded (25 cycles, divisor 0 or 1): 85.0%. Its misses are the two structural
  kinds named in advance (49 need a divisor above 1, 89 need more depth).
- Six of seven predictions held. Prediction 7 was wrong: formal killed three mutants that
  no simulation arm did, all wrong reset values visible only when a bus transfer straddles
  the release of reset.
- Four mutants survive everything, unresolved; each is argued unobservable from reset.
- The original design is proved equal to its specification shadow for all time and all
  divisors (k-induction, z3, about 5 s). Without the refinement invariants: UNKNOWN.
- `make reproduce` re-runs everything and exits 1 on drift. Verified end to end on
  2026-09-20: exit 0 after 76 minutes on a heavily loaded machine (59 when first scored).
  `make test` has 312 tests.

Public at github.com/JoshuaYeung-CS/coverpoint since 2026-11-05 (MIT), tag `v1.0-msr2027` = the
release submitted to the MSR 2027 Data and Tool Showcase.
Commits are Joshua Yeung's. The résumé block in `docs/RESUME-BLOCK.md` is a proposal;
`resumes/` has not been touched.

## Ranked next steps (each needs a NEW mutant sample and its own pre-registration)

1. **Close the reset hole, then measure it.** Add "reset with a transfer in flight" to the
   coverage model, the random knobs and the directed suite; pre-register; draw a third
   sample. Expected: the three formal-only reset mutants (or their cousins) move to the
   simulation arms. This is the cleanest demonstration of formal feeding the bench.
2. **A weaker, realistic checker.** Replace lockstep with a transaction-level scoreboard
   (byte streams, register read-back, flags with timing tolerance) and re-score the same
   stimulus. The gap between the two scores is the "propagated but not detected" class,
   which this round excluded by construction. This is the experiment an interviewer will
   ask for next.
3. **Divisor bits 4 to 6 in the directed suite.** Twelve of the suite's 26 survivors are
   baud-counter mutants that no divisor it uses can expose. One more test at, say, 0x5A
   and 0x75 should take most of them; only meaningful on a new sample.
4. **Deeper formal.** Depth 25 at divisor 0 or 1 is a laptop limit. Options: assume-
   guarantee on the FIFOs so the top-level search does not carry their state; k-induction
   on mutants with the refinement invariants re-pointed at the netlist's register names
   (every induction failure would still need a real trace to count as a kill).
5. **Prove the four unresolved survivors equivalent** by handing PDR the reachability
   facts they hinge on (`rx_slot <= 10`; a frame in flight implies `tx_last_slot >= 9`).
6. Not worth doing: more seeds or more mutants at the same design. The intervals are
   already a point or two wide and the answer would not change.

## Things that are easy to get wrong

- PATH order: the venv must come before the conda prefix, or Verilator's build picks up
  conda's python and dies with "SRE module mismatch". `harness/common.tool_env` does it.
- z3 through SymbiYosys is only good for the inductive proof here. Bounded checks on
  mutants need ABC (`.tools/abc`, built from a pinned tarball because `git clone` cannot
  write `.git/hooks` inside the sandbox; `git init` and `git commit` need the override
  for the same reason).
- `setundef -zero -init` before `write_aiger` is what makes equivalence cheap. Without it
  `scorr` merges nothing and true equivalents never resolve.
- Budgets are depths and cycles, never seconds. A seconds budget made the formal score
  depend on machine load. One recorded by-product still did (the depth an *unresolved*
  equivalence check reached before its time cap), which is why `reproduce` compares
  outcomes through `harness/run.py: stable` (docs/DEVIATIONS.md item 2).
- The union over random seeds has ten times the budget. The headline is the per-seed mean.
- Frozen files: `rtl/`, `bench/`, `formal/`, most of `harness/`, `docs/PREREG.md`,
  `docs/prereg.json`, `docs/SPEC.md`, `requirements.txt`, `Makefile`. Editing any of them
  fails `tests/test_guards.py`. `harness/report.py`, `harness/survivors.py` and
  `harness/structural.py` are free.
- Wording: "UVM-style, in Python (pyuvm) on cocotb". Never SystemVerilog UVM, never
  silicon, never concurrent SVA.
