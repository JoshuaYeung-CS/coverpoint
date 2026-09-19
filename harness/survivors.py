"""Write docs/SURVIVORS.md from the confirmatory results.

The tables (who killed what, and the class of each mutant the formal arm missed) are
computed. The one-line explanations were written by reading the mutated cell in the
elaborated design (`build/prep.il`), after the sample was scored. They are analysis, not
part of the pre-registered score.
"""
from __future__ import annotations

from .common import RESULTS, ROOT, load

COUNTER = ("a conditional bit flip inside a baud counter. It scrambles the order in which the counter visits "
           "its values; at the divisors the suite uses (0, 1, 2, 3, 5, 7, 15, 137) it either never triggers or the "
           "scrambled walk still takes the same number of cycles per bit (checked by hand for 495 at 137)")

WHY = {
    # survive everything
    87: "`rx_slot == 10` with bit 2 of `rx_slot` ignored: also true for 14, which the receiver never reaches. "
        "Equivalent on reachable states; argued, not proved.",
    486: "`tx_frame[11]` stuck at 1: the bit is only ever loaded with 1, and is only read while a frame is "
         "active. Equivalent on reachable states; argued, not proved.",
    525: "one FIFO storage word is no longer cleared by reset. A word is always written before it is read "
         "(reads are gated by the count), so its reset value never reaches a port; argued, not proved.",
    857: "`tx_slot == tx_last_slot` with bit 1 of `tx_slot` flipped while `tx_slot < 8`: `tx_last_slot` is 9, "
         "10 or 11 whenever a frame is active, so the comparison is false either way. Argued, not proved.",
    # formal only
    314: "`s1` (first synchroniser flop) resets to 0 instead of 1. Looks like a start bit only if `rx_en` is "
         "written by a transfer that straddles the release of reset; no test drives the bus during reset.",
    611: "same register and effect as 314 (`inv` instead of `const0`).",
    969: "`tx_active` resets to 1 instead of 0 and clears itself one cycle later. `STATUS.tx_busy` is wrong for "
         "exactly the first cycle after reset; only a read already in progress as reset is released sees it.",
    # directed survivors killed elsewhere
    138: "flips bit 6 of TX FIFO slot 0 each cycle its bit 1 is set: data and timing dependent. The suite's "
         "bytes and its fixed write-to-send spacing never expose it; random spacing does on every seed.",
    300: "flips bit 3 of TX FIFO slot 1 each cycle its bit 1 is set: same class as 138.",
    38: "inverts bit 4 of TX FIFO slot 0 every cycle: invisible when a byte stays in the slot for an even "
        "number of cycles, which the suite's fixed spacing always gives.",
    139: "bit 4 of the receiver's half-period stuck at 0: needs a divisor whose half period has bit 4 set "
         "(no divisor the suite uses has bit 4, 5 or 6 set).",
    516: "bit 5 of the receiver's half-period stuck at 0: same gap as 139.",
    547: "`rx_div[4]` stuck at 0: needs a receive divisor with bit 4 set; none the suite uses has it.",
    58: COUNTER + " (`rx_timer[7]` flips when bit 5 is set).",
    782: COUNTER + " (`rx_timer[5]` flips when bit 6 is set).",
    495: COUNTER + " (`tx_phase` increment, bit 3 when bit 7).",
    667: COUNTER + " (`tx_phase` increment, bit 1 when bit 4).",
    760: COUNTER + " (`tx_phase` next value, bit 5 when bit 7).",
    808: COUNTER + " (`tx_phase` next value, bit 3 when bit 6).",
    829: COUNTER + " (`tx_phase[6]` flips when bit 4 is set).",
    844: COUNTER + " (`tx_phase` hold path, bit 4 when bit 2).",
    985: COUNTER + " (`tx_phase[3]` flips when bit 7 is set).",
    50: "the `paddr == STATUS` comparator ignores `paddr[7]`, so 0x88 aliases STATUS. The suite's 14 unmapped "
        "addresses do not include it; the solver finds it in 1 cycle.",
    705: "the `paddr == BAUD` comparator ignores `paddr[7]`, so 0x84 aliases BAUD. Same gap as 50.",
    859: "a write to any OTHER register clears `IRQ_EN[3]`. The suite always writes `IRQ_EN` last before it "
         "relies on it; random interleaving kills this on every seed.",
    948: "a write to any other register flips `CTRL.rx_en` when `CTRL.stop2` is set: cross-register "
         "interference behind a rarely used mode bit.",
}


def main() -> None:
    sample = RESULTS / "confirmatory"
    score, outcomes = load(sample / "score.json"), load(sample / "outcomes.json")["mutants"]
    mm = {m["id"]: m for m in load(sample / "mutants.json")["mutants"]}
    plan = load(ROOT / "docs" / "prereg.json")
    depth = plan["formal"]["frames"]

    def where(k):
        m = mm[k]
        return m["src"][0].replace("rtl/", "") if m["src"] else m["cell"].split("$")[1][:28]

    def killers(k):
        v = outcomes[str(k)]
        out = []
        if v["directed"]:
            out.append("directed")
        n = sum(1 for x in v["random"].values() if x is not None)
        if n:
            out.append(f"random {n}/10")
        if v["formal"]["status"] == "FAIL":
            out.append(f"formal@{v['formal']['frame']}")
        return ", ".join(out) or "nothing"

    def table(ids):
        rows = ["| id | mutation | where | killed by | why it survived |", "|---|---|---|---|---|"]
        for k in ids:
            rows.append(f"| {k} | `{mm[k]['mode']}` | `{where(k)}` | {killers(k)} | {WHY[k]} |")
        return "\n".join(rows)

    everything = score["unresolved_survivors"]
    formal_only = score["formal_vs_simulation"]["formal_only"]
    directed = [m["id"] for m in score["survivors"]["directed"] if m["id"] not in everything + formal_only]

    # The formal arm's misses, classified from the unrestricted equivalence search that every
    # killed mutant also got: a difference found within the formal depth by the unrestricted
    # search, but not by the formal arm, can only be one that needs a divisor above the bound.
    live = [int(k) for k, v in outcomes.items() if v["equivalence"]["verdict"] != "equivalent"]
    missed = [k for k in live if outcomes[str(k)]["formal"]["status"] != "FAIL" and k not in everything]
    classes = {"divisor": [], "depth": [], "deeper": []}
    for k in missed:
        e = outcomes[str(k)]["equivalence"]
        if e["verdict"] == "different" and e["frame"] <= depth:
            classes["divisor"].append(k)
        elif e["verdict"] == "different":
            classes["depth"].append(k)
        else:
            classes["deeper"].append(k)

    text = f"""# Survivors

Generated by `python -m harness.survivors` from `results/confirmatory/`. The counts are
computed; the explanations were written afterwards by reading each mutated cell in the
elaborated design. They are analysis, not part of the pre-registered score.

## Survived every arm ({len(everything)})

None of these was proved equivalent inside the registered budget, so all four count
against every arm. Each one is, by the argument given, unobservable from reset.

{table(everything)}

## Killed only by the formal arm ({len(formal_only)})

The pre-registration predicted there would be none. All three are wrong reset values
that show at a port only when an APB transfer is in flight as reset is released. Every
test and every random reset in the bench happens with the bus idle, and the coverage
model has no bin for it. The solver is not told when to reset, and finds it in 1 to 3
cycles. (A real APB master shares the reset and would not drive a transfer through it; a
production formal environment might well assume that away, and then these three would be
equivalent under it. They are as much a finding about environment assumptions as about
the design.)

{table(formal_only)}

## Survived the directed suite, killed by something else ({len(directed)})

{table(directed)}

## What the formal arm missed ({len(missed)}), by reason

Classified mechanically. Every killed mutant also got a bounded equivalence search with
**no** divisor restriction, to {plan["equivalence"]["killed_check_frames"]} cycles.

| reason | mutants |
|---|---|
| needs a baud divisor above {plan["formal"]["max_div"]}: the unrestricted search finds a difference within {depth} cycles, the formal arm (divisor 0 or 1) does not | {len(classes["divisor"])} |
| needs {depth + 1} to {plan["equivalence"]["killed_check_frames"]} cycles to reach a port | {len(classes["depth"])} |
| needs more than {plan["equivalence"]["killed_check_frames"]} cycles at any divisor (deep FIFO entries, overruns, long frames) | {len(classes["deeper"])} |

Both reasons were named in the pre-registration as structural limits of a bounded search
on a serial device, before the sample was drawn.
"""
    (ROOT / "docs" / "SURVIVORS.md").write_text(text)
    print(f"everything {len(everything)}, formal-only {len(formal_only)}, directed-only {len(directed)}, "
          f"formal missed {len(missed)}: {{k: len(v) for k, v in classes.items()}}".replace("{k: len(v) for k, v in classes.items()}", str({k: len(v) for k, v in classes.items()})))


if __name__ == "__main__":
    main()
