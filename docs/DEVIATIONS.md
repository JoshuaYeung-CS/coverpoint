# Deviations from the pre-registration

`docs/PREREG.md` was frozen at commit `9cc02e7`. The confirmatory sample was drawn and
scored once, at that commit (`results/confirmatory/OPENED.json` records it, with a hash of
every frozen file; `tests/test_guards.py` fails if any of them changes). This file lists
everything done differently from the plan, and everything done after the sample was
opened.

## Done differently from the plan

1. **Where the survivor explanations live.** The plan says every mutant that survives
   everything is explained in one line "in the README". They are in `docs/SURVIVORS.md`,
   which the README links and summarises, because the same table also explains the
   directed suite's 26 survivors and the formal arm's misses and would have swamped the
   README.

2. **One frozen file was amended after the sample was opened: `harness/run.py`, its
   comparison logic only.** The first full `make reproduce` reproduced every mutant, every
   kill cycle of every simulation run, every formal verdict and frame, every equivalence
   verdict and the whole score table bit for bit, and still reported drift, in one
   by-product: for a mutant whose equivalence check comes back `unresolved`, the harness
   also records how deep the search got before its time cap, and that depth depends on
   how busy the machine is (mutant 50 on dev: 33 cycles when first scored, 30 when
   reproduced under load; mutant 7: 30 and 28). The verdicts did not change and nothing
   reads that depth. The pre-registration's own rule is that budgets are depths, never
   seconds; this one recorded field broke it. `reproduce` now compares outcomes with that
   field removed for unresolved mutants (`harness/run.py: stable`), and gained
   `--compare-only` so the amended comparison could be applied to the run that exposed the
   problem. **No file under `results/` was changed, and no verdict, kill or score.**
   `results/confirmatory/OPENED.json` is untouched; the amended hash is recorded in
   `docs/amendments.json`, and `tests/test_guards.py` accepts a changed frozen file only
   if it is listed there and named here.

Nothing else. No other frozen file has changed since the sample was opened. No test, knob,
sequence, property, budget or scoring rule was changed after seeing a confirmatory result.

## A prediction that was wrong

Prediction 7 said the formal arm would kill no mutant that every simulation arm misses.
It killed three (314, 611, 969). This is a result, not a deviation, and is reported as
finding 5 in the README. The bench was **not** changed in response: adding a
"reset while the bus is busy" test now and re-scoring would be exactly the move the plan
exists to prevent. It is the first item in `notes/STATE.md` for a later round, on a new
sample.

## Done after the sample was opened (post-hoc, none of it changes a score)

- **Survivor analysis.** `harness/survivors.py` and the explanations in
  `docs/SURVIVORS.md` were written after scoring, by reading each mutated cell in the
  elaborated design. The classification of the formal arm's misses is mechanical (from
  the unrestricted bounded search every killed mutant also got); the one-line reasons are
  analysis. One of them (mutant 495 at divisor 137) was checked by hand and by re-running
  the large-divisor test on it.
- **A longer proof attempt** on the four mutants that survived everything unresolved: PDR
  with a 1,200-second cap instead of the registered 300 (`results/posthoc_long_pdr.json`).
  An earlier attempt with a one-hour cap was cut off by a restart after about 75 minutes
  without a verdict and is not recorded. **Outcome: all four are still unresolved** after 1,200
  seconds of PDR each, which fits the explanation in `docs/SURVIVORS.md`: each is
  equivalent only on reachable states, so the proof needs an invariant the engine has to
  find for itself. Whatever it returns, the four stay in every
  denominator in the headline table, as registered.
- **Re-running single tests on single mutants** (859 and 495 among them) to confirm an
  explanation before writing it down.

## Not pre-registered, run before the sample was opened

- **Structural coverage** (`harness/structural.py`, `results/structural.json`): Verilator
  line, branch, expression and toggle coverage of the original RTL under the smoke test,
  the directed suite and one random seed. Supplementary; it is quoted in the README only
  to make the point that the smoke test's 71% line coverage sits next to a 48% mutation
  score.

## Known defects left in the frozen bench

- `TxMonitor` is never told the programmed divisor or parity, so the transaction log it
  publishes is only right for 8N1 at divisor 0. It makes no pass/fail decision and nothing
  scored depends on it. Found before the freeze, left alone rather than touching the bench
  between the dry run and the freeze. Listed in `docs/GAPS.md`.
