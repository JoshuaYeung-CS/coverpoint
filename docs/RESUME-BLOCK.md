# Résumé block: a proposal

> **Adopted 2026-10-16.** This block is live in `resumes/resume-master.tex` as id `coverpoint` (resumes c08f7d1; coverpoint's final sentence 4f7e33b), restyled to the 2026-10-11 two-bullet contract, on the hardware page. The same two bullets head the CV's Research Projects list (resumes fa7ca4a). The proposal below is the record of the wording it was cut from, not the shipping wording.

Nothing in `resumes/` has been touched. This is the block in master syntax, the claims it
makes with where each is checked, and the wording that was rejected. It would be the first
block in the pool with a hardware description language, a testbench or a formal proof on
it.

## Proposed block

```latex
%% >>> block: coverpoint | project
    \resumeProjectHeading
      {\textbf{UART Peripheral Verification Study} $|$ \emph{SystemVerilog, Python (cocotb, pyuvm), Verilator, Yosys, SymbiYosys}}{Sep 2026 -- Present}
      \resumeItemListStart
        \resumeItem{Measured how many hardware bugs each verification technique catches on an APB UART I designed in SystemVerilog, scoring hand-written directed tests, constrained-random stimulus and formal checks against 1,000 machine-generated design mutations instead of bugs I planted myself.}
        \resumeItem{Built a UVM-style testbench in Python with a cycle-accurate reference model and a functional coverage model; directed and constrained-random tests each caught 97\% of bugs at equal simulation cost, and the reset bugs neither could reach were found by the formal search.}
        \resumeItem{Proved the design correct against its specification for all time by induction, adding the strengthening invariants the proof needed, and fixed the scoring plan before drawing the mutants so that every reported figure regenerates from one command.}
      \resumeItemListEnd
%% <<< block: coverpoint
```

Two-bullet version, for a page at capacity: keep bullets 1 and 2.

## Every claim, and where it is checked

| claim | source |
|---|---|
| an APB UART I designed in SystemVerilog | `rtl/cp_uart.sv`, `rtl/cp_fifo.sv`, `docs/SPEC.md` |
| directed, constrained-random and formal, scored against mutations | `docs/PREREG.md`, `harness/run.py` |
| 1,000 machine-generated design mutations | `results/confirmatory/mutants.json`; Yosys `mutate`, seed 20260919 |
| instead of bugs I planted myself | no mutant was placed by hand; the seed was committed before the draw (`results/confirmatory/OPENED.json`) |
| UVM-style testbench in Python | `bench/tb/`: pyuvm sequence items, sequencers, drivers, monitors, environment, scoreboard, tests |
| cycle-accurate reference model | `bench/model.py`, written from the spec alone, before the RTL was opened; 303 tests in `tests/test_model.py` |
| functional coverage model | `bench/tb/coverage.py`, 98 bins |
| each caught 97% at equal simulation cost | directed 97.2%, random 96.9% as the mean of ten seeds, both at 11,690 cycles; rounded to "97%". "Each", not "the same": they do not kill the same mutants (README finding 2) |
| the reset bugs neither could reach were found by the formal search | mutants 314, 611, 969 in `docs/SURVIVORS.md`: killed by the formal arm only |
| proved correct against its specification for all time by induction | `results/proof.json`: PASS with `formal/invariants.svh`, all 256 divisors; "correct against its specification" is the claim, not "correct" |
| adding the strengthening invariants the proof needed | the same proof returns UNKNOWN without them (`results/proof.json`); `DECISIONS.md` entry 13 |
| fixed the scoring plan before drawing the mutants | `docs/PREREG.md`, frozen at commit `9cc02e7`; enforced by `harness/guard.py` and `tests/test_guards.py` |
| every reported figure regenerates from one command | `make reproduce`, exits 1 on any drift |

## Choices made, and what was rejected

- **Title.** "UART Peripheral Verification Study" says what it is to a recruiter.
  "coverpoint" is a repository name. Rejected: "Mutation-Based Verification Benchmark"
  (jargon in the one place a skimmer reads).
- **"UVM-style testbench in Python"**, never "UVM testbench" and never "SystemVerilog UVM".
  The stack line names pyuvm so nobody has to guess. If a posting's keyword filter needs
  the three letters, they are there, attached to the truth.
- **One system number per bullet**: 1,000 in the first (the size of the evidence), 97% in
  the second (the count of reset bugs, three, is left out to keep it to one), none in the
  third. The 85% formal score is left out on purpose: without the
  sentence explaining the bound it reads as "formal is worse", which is not what was found.
- **Rejected for bullet 2:** "constrained-random matched directed testing". True, but it
  invites "so why write directed tests?"; the bullet says both halves, including what
  neither could do.
- **Rejected for bullet 3:** "formally verified the design". The honest scope is an
  inductive proof against a specification I also wrote, under stated environment
  assumptions. "Proved the design correct against its specification" carries that.
- **Not claimed anywhere:** silicon, FPGA, timing closure, SystemVerilog UVM, concurrent
  SVA, a commercial simulator, that mutation score is a bug-finding rate, or novelty (the
  one-netlist mutation method is YosysHQ's MCY).
- **No symbols.** No arrows, comparison signs or multiplication signs in the block.
- **Dates.** `Sep 2026 -- Present` follows the house range format while later rounds are
  planned.
- **Stack line.** Only what the repository uses. ABC and z3 are left off: they are solvers
  behind SymbiYosys-style flows and mean nothing to a recruiter; they are in the README.

## Where it fits

Design verification, FPGA / RTL and hardware test automation pages, as the lead project:
it is the only block with a hardware description language on it. It pairs with `cachesim`
(differential testing against an independent model, mutation checks) without repeating it:
that block is software about hardware, this one is hardware. It is weak for pure software
roles.

## Interview risk, stated once

The strongest question is "your scoreboard is a cycle-exact model of your own design, so
what did you actually test?" The answer is `DEFENSE.md` question 2: the checker is held
constant on purpose so that only stimulus varies, every arm is therefore an upper bound,
and the README says so in its own section. The second is "is that UVM?" (question 12): no,
and the block does not say it is. Both are better raised by the candidate.
