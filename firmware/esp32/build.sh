#!/bin/sh
# Build the OpenFlight ESP32 bench firmware with the REAL ESP-IDF toolchain.
# Steps: openflight compile (observer) -> copy model into main/gen ->
# bake recorded vectors -> source ESP-IDF export -> idf.py build -> size/map.
# Requires: IDF_PATH set to an ESP-IDF checkout; host python with torch/numpy.
# Usage: bash firmware/esp32/build.sh [build_dir]
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BUILD="${1:-$ROOT/firmware/esp32/build}"
GEN="$ROOT/firmware/esp32/main/gen"
if [ -z "${IDF_PATH:-}" ]; then
  echo "ERROR: IDF_PATH unset. Set IDF_PATH=/path/to/esp-idf" >&2
  exit 5
fi
mkdir -p "$GEN" "$BUILD"
cd "$ROOT"  # host-python steps import repo-root modules (learned_observer)
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
echo "--- openflight compile (observer mlp:60,128,64,1) ---"
# Host-python steps run BEFORE sourcing export.sh so the caller's torch/numpy
# environment is used (ESP-IDF ships its own python venv).
python3 -m openflight.cli compile learned_observer.pt \
  --arch mlp:60,128,64,1 --target esp32 --output "$ROOT/firmware/esp32/gen_build"
cp "$ROOT/firmware/esp32/gen_build/model.h" \
   "$ROOT/firmware/esp32/gen_build/model.cpp" "$GEN/"
echo "--- bake recorded vectors ---"
python3 "$ROOT/firmware/esp32/gen_vectors.py" --n 200 \
  --out "$GEN/test_vectors.h"
echo "--- source ESP-IDF export ---"
# shellcheck disable=SC1091
. "$IDF_PATH/export.sh" >/dev/null
command -v xtensa-esp32-elf-gcc >/dev/null 2>&1 || {
  echo "ERROR: export.sh did not put xtensa-esp32-elf-gcc on PATH" >&2
  exit 5; }
echo "--- idf.py build ---"
idf.py -C "$ROOT/firmware/esp32" -B "$BUILD" build
echo "--- merge flash image (QEMU boots this, not the app bin) ---"
# Merge bootloader (0x1000) + partition table (0x8000) + app (0x10000)
# into one flash_image.bin. Without this step QEMU runs a STALE image —
# this exact bug was found when the stack-highwater printf existed in
# openflight_bench.bin but never appeared in QEMU (flash_image.bin was
# from an earlier build).
python3 -m esptool --chip esp32 merge_bin -o "$BUILD/flash_image.bin" \
  --fill-flash-size 4MB \
  0x1000 "$BUILD/bootloader/bootloader.bin" \
  0x8000 "$BUILD/partition_table/partition-table.bin" \
  0x10000 "$BUILD/openflight_bench.bin" 2>&1 | tail -n 5
echo "--- size summary ---"
python3 "$IDF_PATH/tools/idf_size.py" "$BUILD/openflight_bench.map" 2>/dev/null \
  | head -n 25 || xtensa-esp32-elf-size "$BUILD"/openflight_bench.elf
echo "bin: $BUILD/openflight_bench.bin"

# Capture stack high-water mark from a boot-only QEMU run (no protocol
# traffic). The firmware prints STACK_HIGHWATER_BYTES after its 200-window
# selftest, before the protocol loop. Full protocol+parity validation is
# in qemu_test.py, which also writes results/esp32/stack_highwater.txt.
if command -v qemu-system-xtensa >/dev/null 2>&1; then
  echo "--- stack high-water (QEMU, after selftest workload) ---"
  python3 - "$BUILD" <<'PYEOF'
import os, select, subprocess, sys
build = sys.argv[1]
cmd = ["qemu-system-xtensa", "-M", "esp32", "-m", "4M",
       "-drive", f"file={build}/flash_image.bin,if=mtd,format=raw",
       "-drive", f"file={build}/qemu_efuse.bin,if=none,format=raw,id=efuse",
       "-global", "driver=nvram.esp32.efuse,property=drive,value=efuse",
       "-global", "driver=timer.esp32.timg,property=wdt_disable,value=true",
       "-display", "none", "-monitor", "none", "-serial", "stdio"]
p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.DEVNULL)
data = b""
import time
t0 = time.time()
while time.time() - t0 < 90:
    r, _, _ = select.select([p.stdout], [], [], 5)
    if r:
        chunk = os.read(p.stdout.fileno(), 65536)
        if not chunk:
            break
        data += chunk
        # Match the complete line so a chunk split cannot stop the
        # capture mid-number (a "...BYTES=6" / "152 (..." split happened
        # once and truncated 6152 to 6).
        if b"\r\n" in data and b"STACK_HIGHWATER_BYTES=" in data:
            import re as _re
            if _re.search(rb"STACK_HIGHWATER_BYTES=\d+ \([^\r\n]*\)\r\n", data):
                break
p.kill()
for line in data.decode("latin1").splitlines():
    if "STACK_HIGHWATER" in line or "SELFTEST" in line:
        print(line)
PYEOF
else
  echo "--- stack high-water ---"
  echo "(qemu-system-xtensa not on PATH; the full harness (qemu_test.py) "
  echo "writes results/esp32/stack_highwater.txt when QEMU is available)"
fi
echo "---"
