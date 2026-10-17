"""Fail-first regressions for repro.py's report verification.

Audit finding (2026-10-16): verify() for battery/independent/heldout/
importers checked only `n == correct and n > 0`, so a synthetic report with
a single correct case out of one passed — the verifier could not detect
truncated or inconsistent reports. These tests define the corrected
behaviour: complete expected case inventories, stable unique case
identities, seed/schema agreement, summary-vs-cases consistency, and a
failed reproduction recording a failed evidence result rather than leaving
the previous success presented as current.
"""
import copy
import json

from openflight import repro

RESULTS = repro.ROOT / "results"
CASE_REPORTS = {
    "battery": "contract_battery_report.json",
    "independent": "independent_challenge.json",
    "heldout": "heldout_challenge.json",
    "importers": "importers_report.json",
}


def _load(name):
    return json.loads((RESULTS / CASE_REPORTS[name]).read_text())


def _v(name, rep):
    ok, _detail = repro.verify(name, rep)
    return ok


def test_verify_accepts_real_reports():
    for name in CASE_REPORTS:
        ok, detail = repro.verify(name, _load(name))
        assert ok, f"{name}: real report must verify: {detail}"


def test_verify_rejects_truncated_report():
    rep = _load("battery")
    rep["cases"] = rep["cases"][:1]
    rep["summary"] = {"valid": {"n": 1, "correct": 1}}
    ok, detail = repro.verify("battery", rep)
    assert not ok, (
        "a 1-of-1 report must not verify (truncated coverage accepted: "
        f"{detail})"
    )


def test_verify_rejects_missing_category():
    rep = _load("battery")
    del rep["summary"]["ambiguous"]  # 22/22 remain, internally consistent
    ok, detail = repro.verify("battery", rep)
    assert not ok, f"a report missing a benchmark category accepted: {detail}"


def test_verify_rejects_duplicate_case_identity():
    rep = _load("battery")
    # same total case count, one identity duplicated in place of another
    rep["cases"][1] = copy.deepcopy(rep["cases"][0])
    ok, detail = repro.verify("battery", rep)
    assert not ok, f"duplicated case identity accepted: {detail}"
    assert "duplicate" in detail, (
        f"rejection was for the wrong reason (expected duplicate): {detail}"
    )


def test_verify_rejects_wrong_seed():
    rep = _load("heldout")
    rep["seed"] = 12345
    ok, detail = repro.verify("heldout", rep)
    assert not ok, f"wrong benchmark seed accepted: {detail}"


def test_verify_rejects_wrong_schema_version():
    rep = _load("importers")
    rep["schema_version"] = 2
    ok, detail = repro.verify("importers", rep)
    assert not ok, f"wrong report schema version accepted: {detail}"


def test_verify_rejects_summary_disagreeing_with_cases():
    rep = _load("independent")
    # internally consistent summary (21/21) but only 17 cases exist
    rep["cases"] = rep["cases"][:-4]
    ok, detail = repro.verify("independent", rep)
    assert not ok, f"summary/case-list disagreement accepted: {detail}"


def test_verify_rejects_summary_claiming_more_correct_than_cases():
    rep = _load("importers")
    rep["summary"]["importers"]["correct"] = 5  # cases all score True
    ok, detail = repro.verify("importers", rep)
    assert not ok, f"summary/correct-count disagreement accepted: {detail}"


def test_failed_reproduction_records_failed_evidence(monkeypatch):
    """A failed run must not leave the previous success as current evidence."""
    calls = []

    def _rc(*_a, **_k):
        calls.append(_k)
        return None

    class _Result:
        returncode = 1
        stdout = "1 failed"
        stderr = ""

    monkeypatch.setattr(repro, "run", lambda *a, **kw: _Result())
    monkeypatch.setattr("openflight.evidence.record", _rc)
    rc = repro.main()
    assert rc == 1, "failed reproduction must exit nonzero"
    assert calls, (
        "failed reproduction recorded no evidence outcome; the previous "
        "successful record would still be presented as current"
    )
    results = calls[0]["results"]
    assert results and all(v["result"] == "fail" for v in results.values())


def _stage_results(root, skip=()):
    """Copy every report repro.py checks (plus the freeze manifest)."""
    import shutil

    (root / "results").mkdir()
    for rel, _desc in repro.CHECKS.values():
        if any(s in rel for s in skip):
            continue
        shutil.copy(repro.ROOT / rel, root / rel)
    shutil.copy(repro.ROOT / "results" / "freeze_v0.1.json",
                root / "results" / "freeze_v0.1.json")


class _Run:
    def __init__(self, returncode, stdout="242 passed"):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def test_successful_reproduction_verifies_all_reports(tmp_path, monkeypatch):
    """Happy path: all reports present and valid => exit 0, isolated root."""
    _stage_results(tmp_path)
    monkeypatch.setattr(repro, "run", lambda *a, **kw: _Run(0))
    monkeypatch.setattr(repro, "ROOT", tmp_path)
    rc = repro.main()
    assert rc == 0


def test_missing_report_fails_reproduction(tmp_path, monkeypatch):
    _stage_results(tmp_path, skip=("heldout_challenge.json",))
    monkeypatch.setattr(repro, "run", lambda *a, **kw: _Run(0))
    monkeypatch.setattr(repro, "ROOT", tmp_path)
    rc = repro.main()
    assert rc == 1, "a reproduction missing a required report must fail"
