"""Guards on the experiment's honesty, not on the device.

They fail if the confirmatory sample was scored without a frozen plan behind it, if a
frozen file changed after the sample was opened, or if the repository grew a remote.
"""
import hashlib
import subprocess

import pytest

from harness import guard
from harness.common import RESULTS, ROOT, load


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def test_repository_has_no_remote():
    assert git("remote") == ""


def test_confirmatory_needs_a_frozen_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "PREREG_JSON", tmp_path / "missing.json")
    with pytest.raises(guard.PreregError):
        guard.check_sample_allowed("confirmatory", 1, 1)


def test_confirmatory_refuses_an_unregistered_seed():
    if not guard.PREREG_JSON.exists():
        pytest.skip("plan not written yet")
    plan = load(guard.PREREG_JSON)
    with pytest.raises(guard.PreregError):
        guard.check_sample_allowed("confirmatory", plan["confirmatory"]["seed"] + 1, plan["confirmatory"]["count"])


def test_development_sample_is_always_allowed():
    guard.check_sample_allowed("dev", 123, 5)


def test_confirmatory_results_imply_an_opening_record():
    conf = RESULTS / "confirmatory"
    if not conf.exists():
        pytest.skip("confirmatory sample not opened yet")
    assert guard.OPENED.exists(), "confirmatory results exist without OPENED.json"
    opened = load(guard.OPENED)
    # the plan was committed at or before the opening commit, and has not changed since
    assert git("cat-file", "-t", opened["commit"]) == "commit"
    for path in ("docs/PREREG.md", "docs/prereg.json"):
        assert git("diff", "--stat", opened["commit"], "HEAD", "--", path) == "", f"{path} changed after opening"
    assert load(guard.PREREG_JSON)["status"] == "frozen"


def test_frozen_files_have_not_drifted():
    """A frozen file must still be what it was when the sample was opened. The only way
    round that is an entry in docs/amendments.json, which names the file, its new hash and
    the item in docs/DEVIATIONS.md that explains the change. OPENED.json is never edited."""
    if not guard.OPENED.exists():
        pytest.skip("confirmatory sample not opened yet")
    frozen = load(guard.OPENED)["frozen_sha256"]
    amendments = load(ROOT / "docs" / "amendments.json") if (ROOT / "docs" / "amendments.json").exists() else {}
    deviations = (ROOT / "docs" / "DEVIATIONS.md").read_text()
    for path, digest in frozen.items():
        now = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        if now == digest:
            continue
        assert path in amendments and amendments[path]["sha256"] == now, \
            f"{path} changed after the confirmatory sample was opened"
        assert path in deviations, f"{path} is amended but docs/DEVIATIONS.md does not mention it"


def test_results_files_are_as_produced():
    """The committed confirmatory outcomes must be the ones written at the opening commit's
    successor: no amendment is allowed to touch results/."""
    if not guard.OPENED.exists():
        pytest.skip("confirmatory sample not opened yet")
    changed = git("log", "--format=%h", "--", "results/confirmatory/outcomes.json",
                  "results/confirmatory/score.json", "results/confirmatory/mutants.json").split()
    assert len(changed) == 1, f"confirmatory results were committed more than once: {changed}"
