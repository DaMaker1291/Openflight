# Hardware Plan — first real-MCU experiment (NOT YET RUN on silicon)

Status 2026-10-12: **no hardware available in this environment.** No dev
boards on USB serial (`/dev` shows only Bluetooth/debug-console), no
`arm-none-eabi-g++` / `xtensa-esp32-elf-g++` / `idf.py` / `st-flash` /
`openocd` / `esptool.py`, no `pyserial`. No silicon results are claimed
anywhere in this repo; host numbers are labeled host-only in every report.

Done since last revision: the firmware is no longer a stub.
`firmware/generic/benchmark_main.cpp` (protocol loop behind `hal.h`) executes
unmodified against `firmware/host_sim/` and is covered by
`tests/openflight/test_firmware_harness.py` (gate paths, CRC interop both
directions, error replies, dead-link exit; `results/firmware_harness.json`).
What remains for silicon: a real `hal_*` port (UART + DWT `CYCCNT` / ESP
`ccount`) and steps 1–6 below.

## Smallest safe experiment (explicit approval required before flashing)

1. Target: one ESP32 dev board (or one STM32, not both). Record board rev,
   chip, crystal/clock config, ESP-IDF (or Cube) version, host toolchain
   version, full compiler flags.
2. Firmware: `build/example_disturbance12/model.{h,cpp}` + the benchmark app
    (`firmware/generic/benchmark_main.cpp`, now implemented against `hal.h`;
    host-simulated in `firmware/host_sim/`). For silicon, port `hal_*` to the
    real UART + timer (DWT `CYCCNT` / ESP `ccount`) with no logic changes.
    Flash **only** with explicit operator approval (`deploy --flash` stays opt-in).
3. Vectors: checked-in deterministic inputs (seed recorded in manifest), same
   bytes as the host run. Compare MCU outputs vs PyTorch reference at the
   documented atol; report max/mean err.
4. Timing: on-target predict-only timestamps (serial excluded), n=10,000,
   report min/median/p95/p99/max + deadline misses at the documented
   `deadline_us`, plus timer resolution and clock config. No WCET claims.
5. Memory: firmware `.map` (Flash `.text`/`.rodata`, SRAM `.data`/`.bss`),
   stack high-water mark (paint/fill method), heap-use instrumentation
   (`__wrap_malloc` or link map + runtime counters) proving zero heap in
   the inference path.
6. Artifacts: raw vectors, MCU outputs, latency CSV, map file, firmware ELF
   hash, full manifest — committed alongside the host results, never mixed
   with them.

## Success criteria (all six, else it is still a prototype)

firmware compiles · executes on MCU · outputs match reference within atol ·
zero-heap verified on target · Flash/RAM measured (or explicitly qualified) ·
latency measured on target with method documented.
