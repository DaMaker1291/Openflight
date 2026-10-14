"""Freeze OpenFlight v0.1: record source revision, hashes, env, models.

Usage: python3 openflight/freeze.py [--out results/freeze_v0.1.json]
Writes a manifest pinning everything an independent reproduction needs.
Does not commit anything.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DEFAULT = ROOT / "results" / "freeze_v0.1.json"

SOURCE_DIRS = ["openflight", "firmware", "tests/openflight"]
SOURCE_SUFFIXES = {".py", ".cpp", ".h", ".yaml", ".yml", ".md", ".sh"}
SKIP_DIRS = {"__pycache__"}
MODEL_FILES = ["learned_observer.pt", "ppo_best.pt",
               "examples/mlp_observer/model_weights.pt"]
# repo-root physics/exporter files the tests import (closed under import)
EXTRA_SOURCES = ["learned_observer.py", "macondo_hover.py",
                 "observer_deploy.py", "openrescue/__init__.py",
                 "openrescue/metrics.py"]


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def git(cmd):
    try:
        return subprocess.run(["git"] + cmd, cwd=ROOT, capture_output=True,
                              text=True, timeout=30).stdout.strip()
    except Exception:
        return "unavailable"


def main():
    out = Path(sys.argv[sys.argv.index("--out") + 1]) \
        if "--out" in sys.argv else OUT_DEFAULT
    files = {}
    for d in SOURCE_DIRS:
        for p in sorted((ROOT / d).rglob("*")):
            if p.is_file() and p.suffix in SOURCE_SUFFIXES \
                    and not any(s in p.parts for s in SKIP_DIRS):
                files[str(p.relative_to(ROOT))] = sha256_file(p)
    for rel in EXTRA_SOURCES:
        p = ROOT / rel
        if p.exists():
            files[rel] = sha256_file(p)
    try:
        import torch, numpy
        deps = {"python": sys.version.split()[0],
                "torch": torch.__version__, "numpy": numpy.__version__}
    except ImportError as e:
        deps = {"error": str(e)}
    try:
        import pytest
        deps["pytest"] = pytest.__version__
    except ImportError:
        deps["pytest"] = "not-installed"
    try:
        out_cxx = subprocess.run(["c++", "--version"], capture_output=True,
                                 text=True, timeout=30).stdout.splitlines()[0]
        deps["cxx"] = out_cxx.strip()
    except Exception:
        deps["cxx"] = "unavailable"
    manifest = {
        "project": "openflight",
        "version": "0.1.0",
        "git_head": git(["rev-parse", "HEAD"]),
        "git_status_openflight": git(["status", "--short", "--", "openflight",
                                      "firmware", "tests/openflight",
                                      "examples", "results"]),
        "source_files": files,
        "n_source_files": len(files),
        "dependencies": deps,
        "models": {m: (sha256_file(ROOT / m) if (ROOT / m).exists()
                       else "missing") for m in MODEL_FILES},
        "toolchain_note": "no MCU hardware or cross-toolchain in this env; "
                          "host-only (see docs/HARDWARE_PLAN.md)",
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"wrote {out} ({len(files)} source files hashed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
