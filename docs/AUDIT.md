# OpenFlight Audit (2026-10-11)

Method: read all 16 source files, executed 33 host tests, fixed what failed.
No hardware was available (see HARDWARE_PLAN.md); nothing below claims
target-side evidence. Severity = impact on a researcher relying on the tool.

## Findings fixed during this audit

| # | Claim / area | Location | Problem found | Fix | Evidence now |
|---|---|---|---|---|---|
| 1 | "Static memory plan" | `compiler/codegen.py`, `compiler/memory_planner.py` | **HIGH.** Plan computed buffer offsets/peak but codegen ignored them: emitted two `buf[max_dim]` stack arrays plus an unused `scratch[]` in `predict()`. Plan peak and actual stack use could diverge; "static" wording wrong (automatic storage, not static). | Codegen now sizes `buf_<id>[N]` from the plan's buffers; dead `scratch[]` removed; `predict()` forwards `nullptr` workspace; report notes say fixed-size stack, high-water mark still to be measured on target. | `test_plan_matches_generated_code` asserts plan bytes == emitted sizes, peak == sum of buffers, no dead scratch |
| 2 | "No dynamic allocation" scan | `cli.py`, `benchmark/runner.py` | **HIGH.** Substring grep over raw source, including comments — the guarantee comment itself tripped it (`FOUND ['malloc']` after fix #1). Dead `_compile_host`, unused imports; `np.loadtxt` crashed on `runs=1`. | Centralized `validation.scan_no_heap()` (strips `//` comments, documented as text-only evidence); runner cleaned; `ndmin=1`; timer methodology recorded in stats. | `test_no_heap_symbols_in_object` (`nm -u` on compiled `model.o`: no malloc/free/calloc/realloc/operator new/delete); old grep test upgraded to strip comments |
| 3 | Linear without bias | `compiler/graph.py` (both paths) | **MEDIUM.** `None.bias.detach()` → `AttributeError`, not the documented `ValueError` refusal. | Explicit `ValueError` on both Sequential and FX paths. | Parametrized `test_unsupported_modules_rejected` incl. `bias=False` |
| 4 | Batch handling | `compiler/validation.py` | **MEDIUM.** Batch≠1 example input silently generated batch-1 code. | Reject `input_shape[0] != 1` with message. | `test_batch_not_one_rejected` |
| 5 | Dim consistency | `compiler/validation.py` | **MEDIUM.** Relied on torch matmul error text. | Explicit in/out dim check per Linear node. | `test_consecutive_dim_mismatch_rejected` |
| 6 | C++ adapter parity | `adapters/codegen.py` | **MEDIUM.** Python had `gyro_measurement`, C++ did not; C++ divided by zero on zero quat (Python raises). | Added C `gyro_measurement`; zero-norm guard with documented Python/C behavioral difference (callers must validate). | `test_py_vs_c_parity` (50 vectors accel + gyro, atol 2e-6) |
| 7 | Protocol deframing | `benchmark/protocol.py` | **MEDIUM.** `decode` needed an exact packet; trailing bytes silently ignored; no length cap, no seq checking. | Added `MAX_PAYLOAD` cap, `decode_stream` (returns leftover, never drops), `check_seq` (gap/replay rejection). | 2 protocol tests: truncation, bad version/CRC, oversize, stream split, gap, replay |

## Residual gaps (documented, not fixed — see TEST_PLAN.md)

| Area | Gap | Severity |
|---|---|---|
| Allocations | Only host evidence (source scan + `nm -u`); on-target heap instrumentation not done — no board | HIGH (for any real-time claim) |
| Latency | Host `clock_gettime` only; no MCU timer, no toolchain for cross-compile | HIGH (for any deadline claim) |
| Memory | Plan is stack buffers; stack high-water mark, `.bss`/linker map unmeasured | HIGH |
| Adapters | Contract declares units/frames but generates **no unit conversion**; `check_compat` (3 string keys) not wired into CLI `deploy`; no timestamp handling; normalization unverified end-to-end | ~~MEDIUM-HIGH~~ RESOLVED 2026-10-11 — see CONTRACT_ENGINE.md: checker + unit/reorder/normalize pipeline + deploy gate + 10-fault evaluation. Remaining: nonlinear scales, frame-transform synthesis, bias modeling, timestamps |
| Runner | No serial transport (`pyserial` absent); Level 2+ unimplemented; `input_range` fixed U(-1,1) unless overridden | MEDIUM |
| Firmware | `firmware/generic/benchmark_main.cpp` is a comment stub, not compilable firmware | MEDIUM |
| Targets | Registry is a static table; no toolchain detection, no clock-config records | LOW |
| Reproducibility | Manifest hashes model.h/cpp only, not metadata/contract/vectors | LOW |

## Prior reported results — reassessed

| Reported | Verdict |
|---|---|
| 5,187 params / 20,748 B | Confirmed exact for 12→64→64→3 |
| max err 7.45e-08 (disturbance12) | Reproduced 7.451e-08; observer60 1.8–2.4e-07 across runs |
| 1–4 µs "benchmark" | Host-only (`clock_gettime`, Apple clang, arm64 Mac). Says nothing about ESP32/STM32. Labeled as such in reports/manifest |
| "CLEAN (no heap calls)" | Was source grep; now source grep (honest label) + `nm -u` object check on host. Target proof outstanding |
| 4 pytest | Now 33 tests, all executed (breakdown in TEST_PLAN.md) |
