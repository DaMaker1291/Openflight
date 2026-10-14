# ESP32 simulation evaluation (NOT physical hardware)

Variant: plain ESP32 (ESP32-DevKitC equivalent). Simulator: Espressif QEMU
(qemu-system-xtensa, esp-develop 9.0.0, `esp32` machine) executed locally;
Wokwi project + CI job provided but Wokwi execution is PENDING (requires a
`WOKWI_CLI_TOKEN` account secret — no token in this environment).

Toolchain: ESP-IDF v5.3.2 (shallow clone), xtensa-esp-elf-gcc
(crosstool-NG esp-13.2.0_20240530) 13.2.0. ESP-IDF installed outside the repo
(`~/esp-idf`); only the project sources live in `firmware/esp32/`.

Model: `learned_observer.pt`
(sha256 `905aefaa…43045e0b`), arch `mlp:60,128,64,1`, 16,129 params.
Firmware ELF sha256 `c95be3c1…ebfb2372a`, .bin sha256 `522abeb6…92113e52`.
Parity tolerance predefined: 1e-4 (same as host test; never relaxed).

## Experiment 1 — target compilation: PASS

`bash firmware/esp32/build.sh`: openflight compile → model+adapter sources
copied into `main/gen/` → recorded vectors baked → `idf.py build` with the
real Xtensa toolchain. The generated inference code AND sensor adapter compile
as part of the ESP-IDF app (not merely alongside it). Binary 0x495b0 bytes;
71% of the 1 MB app partition free.

## Experiment 2 — numerical parity in simulation: PASS

- Boot SELFTEST (200 recorded windows, inference inside firmware):
  `SELFTEST maxerr=3.576e-07 N=200 TOL=1.0e-04 PASS`.
- Live protocol run (`firmware/esp32/qemu_test.py`, 50 recorded windows):
  max abs err **3.576e-07** vs the saved PyTorch reference, all finite.
- Bit-identical to the host result (3.576e-07): same IEEE-754 float32
  arithmetic, no fast-math divergence on this model. That is a consistency
  observation, not a proof about other models or compiler flags.

## Experiment 3 — protocol correctness: PASS

Valid HELLO/CONFIGURE/RUN_TEST/RESULT exchange; corrupted CRC → ERROR naming
the seq with no RESULT emitted; unknown message type → ERROR; truncated frame
→ no reply until the remaining bytes complete the frame (documented rule:
exact-frame receiver; recovery past a *corrupted alignment* needs link reset —
no silent misbehavior was observed, but resync is NOT implemented).

## Experiment 4 — deployment gating: PASS

RUN_TEST before CONFIGURE → explicit ERROR; CONFIGURE with wrong (12,3)
sizes against the (60,1) firmware model → explicit ERROR; correct
CONFIGURE(60,1) → ack. No inference runs unconfigured.

## Experiment 5 — resource assessment (target build, not estimates)

From `openflight_bench.map` (`results/esp32/`, `idf_size.txt`):

| Section | Measured | Notes |
|---|---|---|
| Model weights in flash `.rodata` | **64,512 B** in five named sections (W_0 30720 + W_2 32768 + W_4 256 + BIAS_0 512 + BIAS_2 256) **plus** the 4-byte output bias, which GCC folded into the function's literal pool (verified via `objdump -h`/`nm`: no `BIAS_4` symbol; `.literal.predict_scratch` holds it) → **64,516 B total, exactly the compiler prediction** |
| Self-test vectors+refs in flash | 48,128 + 800 B | test payload, not shipped in production use |
| App `.text` (code) | 90,990 B total app (incl. ESP-IDF) | model code is a fraction; per-symbol split in map |
| DRAM `.bss`+`.data` | 19,476 B total | includes FreeRTOS/UART stacks, not just inference |
| Activation buffers | stack-resident by codegen design | NOT in map; stack high-water measured after selftest workload |
| Latency | first RESULT 218–480 µs observed across QEMU runs on the **simulator clock** | simulator timing only; no silicon claim |
| Stack high-water (min free) | **6152 bytes**, after 200-window selftest, before protocol loop | `uxTaskGetStackHighWaterMark(NULL)`; unit verified against ESP-IDF v5.3 source (`portSTACK_TYPE = uint8_t` on Xtensa → bytes); QEMU value; post-protocol-loop watermark not yet measured |

## What may be claimed

| Measurement | Claim |
|---|---|
| Numerical parity | observed for 200+50 recorded inputs in emulation |
| Compiler compatibility | ESP32 target builds with ESP-IDF v5.3.2 + GCC 13.2.0 |
| Static weight storage | 64,516 B in flash, verified in the target map |
| Inference latency | observed simulator values only |
| Stack high-water (min free) | measured: 6152 B after 200-window selftest, before protocol loop; QEMU value; unit verified against ESP-IDF v5.3 source (bytes) |
| Physical correctness / WCET / post-protocol stack | NOT established |

## Failures preserved

- Build script initially ran host-python steps under ESP-IDF's venv
  (no torch) → reordered to host-first, documented in `build.sh`.
- `gen_vectors.py` imported repo-root modules unreachable from its own
  directory → `PYTHONPATH` fix in `build.sh`.
- QEMU `-serial mon:stdio` multiplexing broke binary transfer → plain
  `-serial stdio`, monitor disabled (matches `qemu_test.py`).
- `qemu_test.py` FW path doubled (`firmware/esp32/firmware/...`) → QEMU
  exited instantly; fixed, and the instant-exit failure mode is why the
  SELFTEST assertion exists.
- **Stale flash image**: `build.sh` never ran `merge_bin`; QEMU booted an
  old `flash_image.bin` while `openflight_bench.bin` was rebuilt — stack
  printf existed in the app bin but never appeared in QEMU. Fix: added
  `esptool merge_bin` step to `build.sh`; the harness now requires the
  STACK line, so a stale image fails loudly instead of silently.
- **printf vs UART driver**: `printf` after `uart_driver_install` does not
  reach the protocol UART (console detached) — boot lines use
  `uart_write_bytes`; the stack line was converted to match.
- **Format specifier**: Xtensa `uint32_t` is `unsigned long`; `%u` failed
  under `-Werror=format` → `%lu` with cast.
- **Stack unit**: label initially said "words"; ESP-IDF v5.3 source shows
  `portSTACK_TYPE = uint8_t` on Xtensa, so the return is bytes — label
  corrected to `STACK_HIGHWATER_BYTES`, verified from source.
- Wokwi: CLI installed (0.28.1) but execution blocked on missing
  `WOKWI_CLI_TOKEN`. Wokwi project files + CI job (skips gracefully without
  the secret) are committed; Wokwi-observed results: none yet.
