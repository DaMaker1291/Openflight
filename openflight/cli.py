"""openflight CLI: inspect / compile / benchmark / adapter / deploy."""
from __future__ import annotations

import argparse
import json
import os
import sys

from openflight.errors import OpenFlightError


def _require_torch(stage: str):
    """Diagnose a missing PyTorch for the subcommands that need to load
    weights (inspect/compile/benchmark/deploy). Contract validation, the
    importers, and the evidence graph are torch-free and never call this.

    Returns the imported torch module so callers can bind it locally.
    """
    try:
        import torch
    except ImportError as e:
        raise OpenFlightError(
            stage, "E050",
            f"PyTorch is required for `{stage}` but is not installed",
            "this environment",
            f"importing torch failed: {e}. `{stage}` loads model weights, "
            "which needs torch; contract validation, import, and evidence "
            "do not.",
            "pip install 'openflight[torch]' (or pip install torch), "
            "then re-run.",
            exit_code=5) from e
    return torch


def _validate_arch(name):
    """Parse/validate an --arch string without importing torch.

    Returns None for named example arches, or the parsed dims for mlp:.
    Raises ValueError for malformed/unknown arch strings.
    """
    if not name or name in ("observer60", "disturbance12"):
        return
    if name.startswith("mlp:"):
        try:
            dims = [int(d) for d in name[4:].split(",")]
            if len(dims) < 2 or not all(d > 0 for d in dims):
                raise ValueError
        except ValueError:
            raise ValueError(f"bad --arch {name!r}; want mlp:d0,d1,...,dn")
        return
    raise ValueError(f"unknown --arch {name} (observer60|disturbance12|mlp:dims)")


def _arch_error(name, exc):
    return OpenFlightError("cli", "E012", f"unknown architecture: {exc}",
                           where=f"--arch {name}",
                           why="Arch must be observer60, disturbance12, or "
                               "mlp:d0,d1,...,dn.",
                           action="Run with a supported --arch value.")


def _check_arch(name):
    """Torch-free --arch validation (E012) for pre-torch-gate checks."""
    if not name:
        return
    try:
        _validate_arch(name)
    except ValueError as e:
        raise _arch_error(name, e) from e


def _arch_for_example(name: str):
    import torch.nn as nn
    _validate_arch(name)
    if name == "observer60":
        return nn.Sequential(
            nn.Linear(60, 128), nn.ReLU(), nn.Linear(128, 64), nn.ReLU(),
            nn.Linear(64, 1))
    if name == "disturbance12":
        class DisturbanceObserver(nn.Module):
            def __init__(self):
                super().__init__()
                self.network = nn.Sequential(
                    nn.Linear(12, 64), nn.ReLU(), nn.Linear(64, 64),
                    nn.ReLU(), nn.Linear(64, 3))
            def forward(self, x):
                return self.network(x)
        return DisturbanceObserver()
    # mlp:d0,d1,...,dn -> Linear(d0,d1)+ReLU+...+Linear(dn-1,dn).
    # Lets any feed-forward researcher model reach the contract gate
    # without editing the CLI.
    dims = [int(d) for d in name[4:].split(",")]
    layers = []
    for k in range(len(dims) - 1):
        layers.append(nn.Linear(dims[k], dims[k + 1]))
        if k < len(dims) - 2:
            layers.append(nn.ReLU())
    return nn.Sequential(*layers)


def _resolve_arch(name):
    if not name:
        return None
    try:
        return _arch_for_example(name)
    except ValueError as e:
        raise _arch_error(name, e) from e


def cmd_inspect(a):
    if not os.path.exists(a.model):
        raise OpenFlightError("inspect", "E010", f"model file not found: {a.model}",
                              where=a.model,
                              why="inspect needs a weights file (.pt state_dict).",
                              action="Check the path, or run the quickstart example.")
    _check_arch(a.arch)
    torch = _require_torch("inspect")
    arch = _resolve_arch(a.arch)
    from openflight.compiler import loader, graph as G, validation as V
    try:
        model, meta = loader.load_model(arch, a.model)
    except ValueError as e:
        raise OpenFlightError("inspect", "E011", f"unsupported model: {e}",
                              where=a.model,
                              why="The architecture uses operations OpenFlight "
                                  "cannot compile. See COMPATIBILITY.md.",
                              action="Use a supported architecture or remove "
                                     "the unsupported operation.") from e
    sd = model.state_dict()
    first_w = [v for k, v in sd.items() if k.endswith(".weight")][0]
    ex = torch.zeros(1, first_w.shape[1])
    g = G.extract_graph(model, ex)
    info = V.validate_graph(g)
    print(f"Model: {a.model}\nInput shape:  [1, {info['input_size']}]")
    print(f"Output shape: [1, {info['output_size']}]\n")
    print("Supported operators:")
    for op, n in info["ops"].items():
        print(f"  {op}: {n}")
    print(f"\nParameters:\n  {info['params']:,}")
    print(f"\nFloat32 parameter storage:\n  {info['weight_bytes']:,} bytes")
    print("\nEstimated peak activation storage:\n  Calculated from generated buffer plan "
          "(run `compile`)")
    print(f"\nDeployment target:\n  {a.target or 'Not selected'}")
    return 0


def cmd_compile(a):
    if not os.path.exists(a.model):
        raise OpenFlightError("compile", "E010", f"model file not found: {a.model}",
                              where=a.model,
                              why="compile needs a weights file.",
                              action="Check the path or run the quickstart example.")
    _check_arch(a.arch)
    torch = _require_torch("compile")
    arch = _resolve_arch(a.arch)
    from openflight.compiler.api import compile_model
    ex = None
    if a.input_size:
        ex = torch.zeros(1, a.input_size)
    try:
        out = compile_model(arch, a.model, a.output, ex, a.name or "model",
                            a.atol, a.rtol)
    except ValueError as e:
        raise OpenFlightError("compile", "E030", f"compilation failed: {e}",
                              where=a.model,
                              why="Unsupported operation, shape, or weights. "
                                  "See COMPATIBILITY.md.",
                              action="Run inspect to identify the unsupported "
                                     "operation.", exit_code=3) from e
    print(f"wrote {a.output}/ (params={out['info']['params']:,}, "
          f"weights={out['info']['weight_bytes']} B, "
          f"peak-act={out['mem']['peak_activation_bytes']} B)")
    for f in sorted(os.listdir(a.output)):
        print(f"  {f}")
    # static no-alloc check (source text only — see scan_no_heap docstring
    # for what this does and does not establish)
    from openflight.compiler.validation import scan_no_heap
    bad = scan_no_heap(os.path.join(a.output, "model.cpp"))
    print(f"allocation scan of generated predict path: "
          f"{'CLEAN (no heap calls in source text)' if not bad else 'FOUND ' + str(bad)}")
    return 0


def cmd_benchmark(a):
    from openflight.targets.registry import get
    try:
        tgt = get(a.target)
    except ValueError as e:
        raise OpenFlightError("benchmark", "E013", str(e),
                              where=f"--target {a.target}",
                              why="Unknown deployment target.",
                              action="Choose a listed target.") from e
    if not os.path.exists(a.model):
        raise OpenFlightError("benchmark", "E010", f"model file not found: {a.model}",
                              where=a.model,
                              why="benchmark needs a weights file.",
                              action="Check the path or run the quickstart example.")
    _check_arch(a.arch)
    torch = _require_torch("benchmark")
    arch = _resolve_arch(a.arch)
    from openflight.compiler.api import compile_model
    from openflight.benchmark import runner, memory as M, reports as R
    builddir = a.build or os.path.join("build", "bench")
    ex = torch.zeros(1, a.input_size) if a.input_size else None
    out = compile_model(arch, a.model, builddir, ex)
    model = out["model"]
    res = runner.run_host(model, builddir, runs=a.runs,
                          deadline_us=a.deadline_us, seed=a.seed)
    ok = res["max_abs_err"] <= a.atol + a.rtol * 1.0
    print(f"host differential: max_abs_err={res['max_abs_err']:.3e} "
          f"(tol atol={a.atol}) -> {'PASS' if ok else 'FAIL'}")
    print(f"latency median={res['latency']['median_us']:.1f}us "
          f"p95={res['latency']['p95_us']:.1f}us p99={res['latency']['p99_us']:.1f}us "
          f"max={res['latency']['max_us']:.1f}us n={res['latency']['n']}")
    if a.deadline_us:
        print(f"deadline {a.deadline_us}us misses: "
              f"{res['latency']['deadline_misses']}/{res['latency']['n']}")
    mem = M.estimate_from_metadata(out["gen"]["metadata"], out["mem"])
    mem["target"] = a.target
    mem["timer"] = tgt["timer"]
    mem["target_measured"] = "not measured (no hardware attached in this run)"
    manifest = {"schema_version": 1, "model_sha": out["weights_sha"],
                "header_sha": out["gen"]["header_sha"],
                "source_sha": out["gen"]["source_sha"],
                "target": a.target, "timer": tgt["timer"],
                "runs": a.runs, "deadline_us": a.deadline_us,
                "toolchain": os.environ.get("CXX", "c++"),
                "note": "host Level-1 benchmark; MCU timing requires --flash on hardware"}
    info = R.write_reports(a.results,
                           {"stats": res["latency"], "raw": res["raw_latency"]},
                           {"max_abs_err": res["max_abs_err"],
                            "mean_abs_err": res["mean_abs_err"],
                            "atol": a.atol, "pass": ok},
                           mem, manifest)
    print(f"wrote {a.results}/ ({len(info['files'])} files)")
    if a.flash:
        print(f"FLASH requested: {tgt['flash_cmd']} — attach board and confirm. "
              "Refusing to flash without explicit --flash (opt-in).")
    return 0 if ok else 2


def cmd_adapter(a):
    from openflight.adapters import contracts as C, codegen as CG
    c = C.load_contract(a.contract)
    out = CG.generate(c, a.python_output, a.cpp_output)
    print(f"contract OK (ordering={out['ordering']}); wrote {out['py']}, {out['cpp']}")
    return 0


def _load_contracts(sensor_path, model_path):
    """Load sensor + model contracts. Returns (sensor, model) or (None, errs).

    Schema violations are reported as blocking config errors (E001/E002),
    never raised as tracebacks."""
    from openflight.adapters import contracts as C
    from openflight.contract import model_contract as MC
    try:
        sensor = C.load_contract(sensor_path)
    except Exception as e:
        return None, [{"code": "E001", "feature": "<sensor-contract>",
                       "reason": f"sensor contract invalid: {e}"}]
    try:
        model = MC.load_model_contract(model_path)
    except Exception as e:
        return None, [{"code": "E002", "feature": "<model-contract>",
                       "reason": f"model contract invalid: {e}"}]
    return (sensor, model), []


def cmd_validate(a):
    import json as J
    from openflight.contract import checker
    for label, path in (("sensor contract", a.contract),
                        ("model contract", a.model_contract)):
        if not os.path.exists(path):
            raise OpenFlightError("validate", "E001" if label.startswith("sensor") else "E002",
                                  f"{label} file not found: {path}",
                                  where=path,
                                  why="validate compares two contract files.",
                                  action="Check both paths exist, or run the "
                                         "quickstart example.")
    pair, errs = _load_contracts(a.contract, a.model_contract)
    if errs:
        report = {"schema_version": 1, "status": "blocked",
                  "checks": {}, "errors": errs, "warnings": [],
                  "conversions": [], "deployment": "blocked"}
    else:
        sensor, model = pair
        report = checker.check(sensor, model)
    if a.format == "json":
        print(J.dumps(report, indent=2))
    else:
        print(checker.render_text(report))
    return 0 if report["status"] == "pass" else 2


def cmd_version(a):
    from openflight import __version__
    print(f"openflight {__version__}")
    return 0


def cmd_doctor(a):
    """Environment diagnostic: available / missing / unsupported / not-tested."""
    import shutil

    def have(mod):
        try:
            m = __import__(mod)
            return f"available ({getattr(m, '__version__', 'unknown version')})"
        except ImportError:
            return "missing"

    rows = [
        ("python", f"available ({sys.version.split()[0]})"),
        ("torch", have("torch")),
        ("numpy", have("numpy")),
        ("pyyaml (optional, contracts)", have("yaml")),
        ("pyserial (optional, hardware)", have("serial")),
        ("host C++ compiler", shutil.which(os.environ.get("CXX", "c++")) or "missing"),
        ("arm-none-eabi-g++ (Cortex-M)", shutil.which("arm-none-eabi-g++") or "missing"),
        ("xtensa-esp32-elf-g++ (ESP32)", shutil.which("xtensa-esp32-elf-g++") or "missing"),
    ]
    print("\nOPENFLIGHT DOCTOR\n")
    for name, status in rows:
        print(f"  {name:<34}{status}")
    print("\nNotes:")
    print("  - A missing cross-compiler means cross-compilation was NOT performed,")
    print("    not that the target is supported. Hardware flashing is opt-in.")
    print("  - Host-only checks are marked as such in every report.")
    missing_core = [n for n, s in rows[:1] if s == "missing"]
    optional_missing = [n for n, s in rows[1:8] if s == "missing"]
    _opt_hint = {
        "torch": "weight-loading (inspect/compile/benchmark/deploy); "
                 "pip install 'openflight[torch]'",
        "numpy": "weight-loading and numeric adapters; "
                 "pip install 'openflight[torch]'",
        "pyyaml (optional, contracts)": "YAML contract parsing; "
                                        "pip install 'openflight[yaml]'",
        "pyserial (optional, hardware)": "hardware flashing; "
                                         "pip install 'openflight[hardware]'",
        "host C++ compiler": "host_sim firmware build",
        "arm-none-eabi-g++ (Cortex-M)": "Cortex-M cross-compile",
        "xtensa-esp32-elf-g++ (ESP32)": "ESP32 cross-compile",
    }
    if optional_missing:
        print("\nOptional components not installed (some features unavailable):")
        for n in optional_missing:
            print(f"  - {n}: {_opt_hint.get(n, 'optional feature')}")
    if missing_core:
        raise OpenFlightError("doctor", "E050",
                              f"missing core dependencies: {', '.join(missing_core)}",
                              where="python environment",
                              why="python itself is unavailable, so no "
                                  "OpenFlight command can run.",
                              action="Install Python 3.10+ and re-run doctor.",
                              exit_code=5)
    return 0


def cmd_deploy(a):
    # gated pipeline with explicit per-stage outcomes (see stages.py).
    # A pass at one stage never implies later stages.
    # The contract-validation stage is torch-free and runs first; the
    # torch gate only applies to weight loading (inference codegen).
    import hashlib
    import json as J
    from openflight.stages import StageReport
    stages = StageReport()

    def sha_file(path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            h.update(f.read())
        return h.hexdigest()

    if a.model_contract:
        if not a.contract:
            raise OpenFlightError(
                "deploy", "E002", "--model-contract needs --contract",
                where="command line",
                why="Compatibility is checked between two contracts.",
                action="Pass both --contract (sensor) and --model-contract.")
        pair, errs = _load_contracts(a.contract, a.model_contract)
        if errs:
            print("DEPLOY STOPPED: contract schema invalid:")
            for e in errs:
                print(f"  {e['code']}: {e['reason']}")
                if e.get("action"):
                    print(f"    Action: {e['action']}")
            stages.record("contract_validation", "fail", evidence="schema errors")
            stages.write(os.path.join(a.output, "deployment_report.json"),
                         {"model": a.model})
            return 2
        sensor, model = pair
        from openflight.contract import checker, pipeline as PL
        report = checker.check(sensor, model)
        print(checker.render_text(report))
        if report["status"] != "pass":
            print("DEPLOY STOPPED: contract validation failed — refusing to "
                  "generate code from incompatible contracts")
            stages.record("contract_validation", "fail",
                          evidence=f"{len(report['errors'])} error(s), "
                                   f"first: {report['errors'][0]['code']}")
            os.makedirs(a.output, exist_ok=True)
            stages.write(os.path.join(a.output, "deployment_report.json"),
                         {"model": a.model})
            return 2
        stages.record("contract_validation", "pass",
                      evidence=f"{len(report['conversions'])} conversion(s) generated")
        os.makedirs(a.output, exist_ok=True)
        with open(os.path.join(a.output, "contract_report.json"), "w") as f:
            J.dump(report, f, indent=2)
        PL.generate(sensor, model,
                    os.path.join(a.output, "contract_adapt.py"),
                    os.path.join(a.output, "contract_adapt.h"))
        PL.write_manifest(a.contract, a.model_contract, a.output)
        stages.record("adapter_generation", "pass",
                      evidence="contract_adapt.py/.h")
        contract_shas = {"sensor_contract_sha": sha_file(a.contract),
                         "model_contract_sha": sha_file(a.model_contract)}
    else:
        print("WARNING: no contracts supplied — semantic compatibility was "
              "NOT checked. The contract gate is opt-in; supply --contract "
              "and --model-contract to enable it.", file=sys.stderr)
        stages.record("contract_validation", "skipped",
                      limitation="no contracts supplied; semantic compatibility "
                                 "was NOT checked")
        stages.record("adapter_generation", "skipped",
                      limitation="no contracts supplied")
        contract_shas = {}
    if not os.path.exists(a.model):
        raise OpenFlightError("deploy", "E010", f"model file not found: {a.model}",
                              where=a.model, why="deploy needs a weights file.",
                              action="Check the path or run the quickstart.")
    _check_arch(a.arch)
    torch = _require_torch("deploy")
    arch = _resolve_arch(a.arch)
    from openflight.compiler.api import compile_model
    ex = torch.zeros(1, a.input_size) if a.input_size else None
    try:
        out = compile_model(arch, a.model, a.output, ex)
    except ValueError as e:
        stages.record("inference_codegen", "fail", evidence=str(e)[:200])
        stages.write(os.path.join(a.output, "deployment_report.json"),
                     {"model": a.model})
        raise OpenFlightError("deploy", "E030", f"code generation failed: {e}",
                              where=a.model,
                              why="Unsupported operation, shape, or weights. "
                                  "See COMPATIBILITY.md.",
                              action="Use inspect to identify the unsupported "
                                     "operation.", exit_code=3) from e
    stages.record("inference_codegen", "pass",
                  evidence=f"{out['info']['params']:,} params, "
                           f"{out['info']['weight_bytes']:,} B weights")
    if a.model_contract:
        # contract feature widths must equal the compiled model's input dim
        rep = checker.check(*_load_contracts(a.contract, a.model_contract)[0],
                            model_input_size=out["info"]["input_size"])
        if rep["status"] != "pass":
            print("DEPLOY STOPPED: model contract does not match the compiled "
                  "model:")
            print(checker.render_text(rep))
            stages.record("contract_validation", "fail",
                          evidence="contract/model width mismatch")
            stages.write(os.path.join(a.output, "deployment_report.json"),
                         {"model": a.model})
            return 2
    try:
        from openflight.benchmark import runner
        res = runner.run_host(out["model"], a.output, runs=1000,
                              deadline_us=a.deadline_us)
        stages.record("host_compilation", "pass", evidence="host c++ -O2 build")
    except RuntimeError as e:
        stages.record("host_compilation", "fail", evidence=str(e)[:200])
        stages.write(os.path.join(a.output, "deployment_report.json"),
                     {"model": a.model})
        raise OpenFlightError("deploy", "E031", f"host compilation failed: {e}",
                              where=a.output,
                              why="Generated code did not compile on the host.",
                              action="Check that a C++17 compiler is "
                                     "installed (openflight doctor).",
                              exit_code=3) from e
    parity_ok = res["max_abs_err"] <= a.atol
    stages.record("numerical_parity",
                  "pass" if parity_ok else "fail",
                  evidence=f"max_abs_err={res['max_abs_err']:.3e} "
                           f"(atol={a.atol}) on host",
                  limitation="host-only; target behavior unverified")
    stages.record("cross_compilation", "not-run",
                  limitation="no cross-toolchain invoked by deploy")
    stages.record("firmware_simulation", "not-run",
                  limitation="use the firmware harness separately")
    stages.record("hardware", "not-run",
                  limitation="flashing is opt-in and no device was attached")
    try:
        cxx_version = __import__("subprocess").run(
            [os.environ.get("CXX", "c++"), "--version"],
            capture_output=True, text=True).stdout.splitlines()[0].strip()
    except Exception:
        cxx_version = "unknown"
    meta = {"model": a.model, "model_sha": out["weights_sha"],
            "target": a.target, "compiler": cxx_version,
            "artifact_shas": {f: sha_file(os.path.join(a.output, f))
                              for f in sorted(os.listdir(a.output))
                              if os.path.isfile(os.path.join(a.output, f))},
            **contract_shas}
    try:
        from openflight import __version__ as of_version
    except Exception:
        of_version = "unknown"
    meta["openflight_version"] = of_version
    stages.write(os.path.join(a.output, "deployment_report.json"), meta)
    print(stages.render())
    if not parity_ok:
        print(f"DEPLOY STOPPED: numerical equivalence failed "
              f"(max err {res['max_abs_err']:.3e} > atol {a.atol})")
        return 4
    gate_msg = ("contract gate PASS" if a.model_contract else
                "contract gate SKIPPED (no contracts supplied)")
    print(f"deploy: {gate_msg}, compile OK, host test PASS "
          f"(err {res['max_abs_err']:.2e}), "
          f"median {res['latency']['median_us']:.1f}us. "
          "Hardware flash is opt-in (--flash).")
    return 0


def cmd_import_gym(a):
    from openflight.contract import draft as D
    from openflight.importers import gym_importer as G
    try:
        out = G.import_gym(a.obs, stats_path=a.vec_normalize,
                           net_arch=a.net_arch, out_path=a.out)
    except D.DraftError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    for w in out["warnings"]:
        print(f"warning {w['code']}: {w['reason']}", file=sys.stderr)
    n = len(out["draft"]["features"])
    print(f"draft written: {a.out} ({n} features)")
    print(f"next: openflight contract confirm {a.out} "
          "--out <final> [--confirm path | --confirm-all]")
    return 0


def cmd_import_ros2(a):
    from openflight.contract import draft as D
    from openflight.importers import ros2_importer as R
    try:
        out = R.import_ros2(a.msg, a.type, out_path=a.out)
    except D.DraftError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    for w in out["warnings"]:
        print(f"warning {w['code']}: {w['reason']}", file=sys.stderr)
    print(f"draft written: {a.out}")
    print(f"next: openflight contract confirm {a.out} "
          "--out <final> [--confirm path | --confirm-all]")
    return 0


def cmd_contract_confirm(a):
    from openflight.contract import draft as D
    try:
        result = D.confirm(a.draft, a.out, confirm=a.confirm,
                           confirm_all=a.confirm_all, kind=a.kind)
    except D.DraftError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"contract written: {result['out']}")
    print(f"provenance sidecar: {result['sidecar']}")
    return 0


def cmd_evidence_record(a):
    from openflight import evidence as EV
    EV.record(root=a.root)
    print(f"evidence recorded: {os.path.join(a.root, 'results', 'evidence.json')}")
    return 0


def cmd_evidence_status(a):
    from openflight import evidence as EV
    st = EV.status(root=a.root)
    if st.get("error"):
        print(f"error: {st['error']}", file=sys.stderr)
        return 2
    if a.format == "json":
        print(json.dumps(st, indent=2))
        return 0 if not st["stale_checks"] else 1
    print(f"evidence record from {st['recorded_at']}")
    for check, info in sorted(st["checks"].items()):
        mark = "STALE" if info["stale"] else "fresh"
        print(f"  {check}: {mark}")
        for r in info["reasons"]:
            print(f"    - {r}")
    if st["stale_checks"]:
        print("stale checks: " + ", ".join(st["stale_checks"]))
        print("claims at risk: " + ", ".join(st["claims_at_risk"]))
    else:
        print("all checks fresh")
    if st["unresolved_limitations"]:
        print("unresolved limitations (provenance sidecars / blanket "
              "confirmations):")
        for lim in st["unresolved_limitations"]:
            print(f"  {lim['sidecar']} (confirm_mode={lim['confirm_mode']})")
            for b in lim["not_individually_verified"]:
                print(f"    not individually verified: {b}")
            for l in lim["limitations"]:
                print(f"    [{l.get('code', '?')}] {l.get('reason', '')}")
    return 0 if not st["stale_checks"] else 1


def build_parser():
    p = argparse.ArgumentParser(prog="openflight", description="OpenFlight Deploy")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("inspect"); s.add_argument("model"); s.add_argument("--arch")
    s.add_argument("--target"); s.set_defaults(fn=cmd_inspect)
    s = sub.add_parser("compile"); s.add_argument("model")
    s.add_argument("--arch"); s.add_argument("--target", default="generic-cortex-m")
    s.add_argument("--output", default="build"); s.add_argument("--name", default="model")
    s.add_argument("--input-size", type=int); s.add_argument("--atol", type=float, default=1e-5)
    s.add_argument("--rtol", type=float, default=1e-4); s.set_defaults(fn=cmd_compile)
    s = sub.add_parser("benchmark"); s.add_argument("--model", required=True)
    s.add_argument("--arch"); s.add_argument("--target", default="host")
    s.add_argument("--runs", type=int, default=1000); s.add_argument("--deadline-us", type=float)
    s.add_argument("--atol", type=float, default=1e-3); s.add_argument("--rtol", type=float, default=1e-4)
    s.add_argument("--build"); s.add_argument("--results", default="results")
    s.add_argument("--input-size", type=int); s.add_argument("--seed", type=int, default=0)
    s.add_argument("--flash", action="store_true"); s.set_defaults(fn=cmd_benchmark)
    s = sub.add_parser("adapter"); s.add_argument("generate", nargs="?", default="generate")
    s.add_argument("--contract", required=True); s.add_argument("--python-output", required=True)
    s.add_argument("--cpp-output", required=True); s.set_defaults(fn=cmd_adapter)
    s = sub.add_parser("validate")
    s.add_argument("--contract", required=True)
    s.add_argument("--model-contract", required=True)
    s.add_argument("--format", choices=("text", "json"), default="text")
    s.set_defaults(fn=cmd_validate)
    s = sub.add_parser("deploy"); s.add_argument("--model", required=True)
    s.add_argument("--arch"); s.add_argument("--contract"); s.add_argument("--model-contract")
    s.add_argument("--target", default="host")
    s.add_argument("--output", default="build"); s.add_argument("--input-size", type=int)
    s.add_argument("--deadline-us", type=float); s.add_argument("--atol", type=float, default=1e-3)
    s.add_argument("--flash", action="store_true"); s.set_defaults(fn=cmd_deploy)
    s = sub.add_parser("version"); s.set_defaults(fn=cmd_version)
    s = sub.add_parser("doctor"); s.set_defaults(fn=cmd_doctor)
    s = sub.add_parser("import", help="importer drafts from offline artifacts")
    isub = s.add_subparsers(dest="imp", required=True)
    g = isub.add_parser("gym", help="SB3/Isaac Lab obs-space -> model draft")
    g.add_argument("--obs", required=True)
    g.add_argument("--vec-normalize", default=None)
    g.add_argument("--net-arch", default=None)
    g.add_argument("--out", required=True)
    g.set_defaults(fn=cmd_import_gym)
    r = isub.add_parser("ros2", help=".msg -> sensor draft")
    r.add_argument("--msg", required=True)
    r.add_argument("--type", required=True)
    r.add_argument("--out", required=True)
    r.set_defaults(fn=cmd_import_ros2)
    s = sub.add_parser("contract", help="contract utilities")
    csub = s.add_subparsers(dest="cact", required=True)
    c = csub.add_parser("confirm", help="confirm a draft contract")
    c.add_argument("draft")
    c.add_argument("--out", required=True)
    c.add_argument("--confirm", action="append", default=[])
    c.add_argument("--confirm-all", action="store_true")
    c.add_argument("--kind", choices=("model", "sensor"), default="model")
    c.set_defaults(fn=cmd_contract_confirm)
    s = sub.add_parser("evidence", help="evidence graph: record + staleness")
    esub = s.add_subparsers(dest="eact", required=True)
    e = esub.add_parser("record")
    e.add_argument("--root", default=".")
    e.set_defaults(fn=cmd_evidence_record)
    e = esub.add_parser("status")
    e.add_argument("--root", default=".")
    e.add_argument("--format", choices=("text", "json"), default="text")
    e.set_defaults(fn=cmd_evidence_status)
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        return a.fn(a)
    except OpenFlightError as e:
        print(e.render(), file=sys.stderr)
        return e.exit_code
    except BrokenPipeError:
        return 0


def console_main():
    raise SystemExit(main())


if __name__ == "__main__":
    raise SystemExit(main())
