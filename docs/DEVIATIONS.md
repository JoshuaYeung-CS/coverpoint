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

Nothing else. No frozen file has changed since the sample was opened. No test, knob,
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
  with a one-hour cap instead of the registered 300 seconds
  (`results/posthoc_long_pdr.json`). Whatever it returns, the four stay in every
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
