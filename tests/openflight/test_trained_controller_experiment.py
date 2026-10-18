"""The trained-controller fault-localisation experiment must hold.

Runs the experiment (a genuinely trained controller deployed through the
pipeline, with realistic faults injected) at a small sample count and asserts
the properties the experiment claims: every fault is localised to its expected
stage, the clean control reports agreement, and the diagnosis is reproducible.
All evidence is simulated host-side.
"""
import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("torch")

ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT = ROOT / "experiments" / "trained_controller" / "experiment.py"


def _experiment():
    spec = importlib.util.spec_from_file_location("trained_experiment", EXPERIMENT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_faults_localised_clean_agrees():
    mod = _experiment()
    res = mod.run(out_dir=None, n_samples=8, verbose=False)
    cases = {c["id"]: c for c in res["cases"]}

    assert cases["clean"]["diagnose"]["status"] == "agree"
    for cid, (_family, expected, _build) in mod.FAULTS.items():
        assert cases[cid]["diagnose"]["stage"] == expected, (
            cid, cases[cid]["diagnose"])
        assert cases[cid]["correct"]["diagnose"] is True
    assert res["metrics"]["localisation_accuracy"]["diagnose"] == 1.0
    assert res["metrics"]["false_diagnoses_on_clean"]["diagnose"] == 0


def test_diagnosis_reproducible_and_baseline_parity():
    mod = _experiment()
    res = mod.run(out_dir=None, n_samples=8, verbose=False)
    # the same evidence reproduces the same verdict
    assert res["metrics"]["reproducibility"]["second_run_equivalent"] is True
    # the hand-written staged baseline reaches the same stages on this set
    assert res["metrics"]["localisation_accuracy"]["baseline"] == 1.0
