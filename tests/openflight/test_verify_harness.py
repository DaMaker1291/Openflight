"""Regression tests for the independent verification harness
(`reproduction/verify_diagnose_integrity.py`).

These guard the environment gate specifically: every package pinned in
`requirements-lock.txt` must be checked (not only a core subset), names must
be normalised, and any version mismatch — core or not — must yield a failing
verdict.
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "reproduction" / "verify_diagnose_integrity.py"


def _harness():
    spec = importlib.util.spec_from_file_location(
        "verify_diagnose_integrity", HARNESS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_non_core_dependency_mismatch_fails():
    """A mismatch in a package outside the former core subset (e.g.
    networkx) must fail the gate, not merely warn."""
    mod = _harness()
    pins = mod.parse_pins("torch==2.14.1\nfilelock==4.1.2\nnetworkx==3.7\n")
    installed = {"torch": "2.14.1", "filelock": "4.1.2", "networkx": "3.99"}
    results = mod.check_pins(pins, installed)
    status = {name: s for s, name, _ in results}
    assert status["dependency networkx"] == mod.FAIL
    assert status["dependency torch"] == mod.PASS
    assert status["dependency filelock"] == mod.PASS
    assert mod.verdict(results) != 0


def test_lockfile_checks_every_pin_and_normalises_names():
    """Every distribution in the lock file is checked, and package names are
    normalised so `PyYAML`/`pyyaml` and `typing_extensions`/
    `typing-extensions` compare correctly."""
    mod = _harness()
    pins = mod.parse_pins(mod.LOCK.read_text())
    assert {"torch", "numpy", "pyyaml", "pytest", "matplotlib",
            "filelock", "networkx"} <= set(pins)
    assert len(pins) >= 20
    assert "typing-extensions" in pins
    assert "python-dateutil" in pins
    # a fully matching environment passes
    assert mod.verdict(mod.check_pins(pins, dict(pins))) == 0
