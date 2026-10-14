#!/bin/sh
# Cross-compile check for OpenFlight firmware (portability, not performance).
# Compiles benchmark_main.cpp + a generated model with ARM Cortex-M flags.
# Exposes: compiler compatibility, target language support, missing headers.
# Does NOT establish: latency, stack use, timer behavior (needs silicon).
# Graceful without toolchain: prints SKIP and exits 0 unless --require.
set -eu
REQUIRE=0
if [ "${1:-}" = "--require" ]; then REQUIRE=1; fi
if ! command -v arm-none-eabi-g++ >/dev/null 2>&1; then
  echo "SKIP: arm-none-eabi-g++ not installed (apt install gcc-arm-none-eabi)"
  [ "$REQUIRE" -eq 1 ] && exit 1 || exit 0
fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="${BUILD_DIR:-$ROOT/build/example_disturbance12}"
if [ ! -f "$BUILD/model.cpp" ]; then
  echo "model not found at $BUILD; generating with host toolchain first..."
  python3 -m openflight.cli compile examples/mlp_observer/model_weights.pt \
    --arch disturbance12 --target generic-cortex-m --output "$BUILD"
fi
arm-none-eabi-g++ -mcpu=cortex-m4 -mthumb -Os -std=c++17 \
  -Wall -Wextra -fno-exceptions -fno-rtti \
  -ffunction-sections -fdata-sections \
  -I "$BUILD" -I "$ROOT/firmware/generic" \
  -c "$ROOT/firmware/generic/benchmark_main.cpp" -o /tmp/of_bench.o
arm-none-eabi-g++ -mcpu=cortex-m4 -mthumb -Os -std=c++17 \
  -Wall -Wextra -fno-exceptions -fno-rtti \
  -ffunction-sections -fdata-sections \
  -I "$BUILD" \
  -c "$BUILD/model.cpp" -o /tmp/of_model.o
arm-none-eabi-size /tmp/of_bench.o /tmp/of_model.o
echo "CROSS-COMPILE OK (objects only; link + HAL port need silicon target)"
