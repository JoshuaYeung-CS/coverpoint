# What a professional bench would have that this one does not

Plainly, and in rough order of how much it matters.

1. **A commercial simulator and real SystemVerilog UVM.** This bench is UVM-style, in
   Python (pyuvm) on cocotb, over Verilator. The structure is the same (sequence items,
   sequencers, drivers, monitors, an environment, a scoreboard, tests chosen by name),
   but it is not SystemVerilog UVM: no `uvm_config_db` of virtual interfaces, no factory
   overrides used in anger, no register abstraction layer, no phasing beyond
   build/connect/run. No free simulator on this machine runs SystemVerilog UVM.
2. **Four-state simulation.** Verilator is two-state: there is no X. A real bench catches
   a whole class of reset and uninitialised-register bugs through X propagation. Here
   every flop has a reset value by specification and the formal runs pin the pre-reset
   state, so that class is excluded by construction rather than tested.
3. **Concurrent SystemVerilog assertions.** The open-source Yosys front end accepts
   immediate assertions only, so the properties are written as immediate `assert`s over
   auxiliary state. No `|->`, no sequences, no `bind`. The white-box invariants are
   compiled into the module under an `ifdef` because there is no `bind`.
4. **A constraint solver.** Constrained-random here means weighted choices from a seeded
   generator with the weights in one reviewable table. SystemVerilog `randomize()` with
   declarative constraints, solve-before ordering and coverage-driven feedback into the
   constraints is a different level of tool.
5. **A checker that is not an oracle.** The scoreboard is a cycle-exact reference model,
   which is affordable for a block this small and is what makes the comparison clean, but
   it is not what industry scoreboards look like. They are transaction-level, they
   tolerate timing, and their gaps are where real escapes come from. This project holds
   the checker constant on purpose and therefore says nothing about checker quality.
6. **Real fault models.** Yosys `mutate` makes single-point netlist mutations (invert,
   stuck-at, and a conditional invert). Real bugs are more often a wrong idea implemented
   correctly: a missing case, a misread spec. Mutation score measures how much of the
   logic the verification would notice being wrong, not how many real bugs it would find.
   Commercial qualification tools (Synopsys Certitude is the best known) work on the RTL
   source with a richer fault set.
7. **Clock domains, asynchronous inputs, gate-level timing.** One clock, synchronous
   reset, and `rxd` changes on a clock edge in every test. The two-flop synchroniser is in
   the design but nothing here exercises metastability, baud-rate mismatch between two
   free-running clocks, or post-layout timing. There is no CDC analysis because there is
   one domain.
8. **Regression infrastructure.** No nightly runs, no seed farm, no coverage database
   merged across thousands of runs, no triage tooling, no waveform debug flow (Verilator
   can dump traces; nothing here looks at them).
9. **A verification plan reviewed by someone else.** `docs/TESTPLAN.md` maps every rule of
   the spec to a test, but nobody independent signed it off, and the spec, the plan and
   the design all come from one desk.
10. **Scale.** About 370 lines of RTL, 184 flops. An unbounded inductive proof against a
    full specification shadow is only practical because the block is this small; on a
    real block the formal work is choosing what *not* to prove.
11. **A transaction monitor that follows the line settings.** `TxMonitor` decodes frames
    for the log but is never told the programmed divisor or parity, so its log is only
    right for 8N1 at divisor 0. It decides nothing and feeds nothing that is scored.
