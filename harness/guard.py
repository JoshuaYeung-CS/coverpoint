"""The pre-registration guard.

The development sample may be regenerated and looked at freely. The confirmatory sample
may only be drawn when docs/prereg.json says the plan is frozen, the seed and count asked
for are the registered ones, and everything the score depends on (design, bench, formal
properties, harness, the plan itself) is committed with no local changes. The first time
that happens, results/confirmatory/OPENED.json records the commit and a hash of every
frozen file; tests/test_guards.py fails if those files drift afterwards.
"""
from __future__ import annotations

import datetime
import hashlib
import subprocess

from .common import RESULTS, ROOT, dump, load

PREREG_JSON = ROOT / "docs" / "prereg.json"
OPENED = RESULTS / "confirmatory" / "OPENED.json"
FROZEN_DIRS = ("rtl", "bench", "formal", "harness")
FROZEN_FILES = ("docs/PREREG.md", "docs/prereg.json", "docs/SPEC.md", "requirements.txt")


class PreregError(RuntimeError):
    pass


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def frozen_paths() -> list[str]:
    tracked = git("ls-files", "--", *FROZEN_DIRS, *FROZEN_FILES).split()
    return sorted(p for p in tracked if "posthoc" not in p)


def frozen_hashes() -> dict[str, str]:
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in frozen_paths()}


def check_sample_allowed(sample: str, seed: int, count: int) -> None:
    if sample != "confirmatory":
        return
    if not PREREG_JSON.exists():
        raise PreregError("docs/prereg.json does not exist: the confirmatory sample stays sealed")
    plan = load(PREREG_JSON)
    if plan.get("status") != "frozen":
        raise PreregError("docs/prereg.json is not marked frozen")
    reg = plan["confirmatory"]
    if (seed, count) != (reg["seed"], reg["count"]):
        raise PreregError(f"registered seed/count are {reg['seed']}/{reg['count']}, got {seed}/{count}")
    dirty = git("status", "--porcelain", "--", *FROZEN_DIRS, *FROZEN_FILES).strip()
    if dirty:
        raise PreregError("uncommitted changes in frozen paths:\n" + dirty)
    if not OPENED.exists():
        dump(OPENED, {
            "commit": git("rev-parse", "HEAD").strip(),
            "opened_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "frozen_sha256": frozen_hashes(),
        })
