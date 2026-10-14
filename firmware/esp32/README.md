# OpenFlight ESP32 bench firmware

Real ESP-IDF target (ESP32 devkit). The generated observer + sensor adapter
are compiled INTO this firmware; inference runs on the Xtensa core.

## Build (needs ESP-IDF v5.3.2 + host torch/numpy)

```sh
export IDF_PATH=/path/to/esp-idf
bash firmware/esp32/build.sh            # -> firmware/esp32/build/*.bin
```

`build.sh`: openflight compile → copy `model.h/.cpp` to `main/gen/` → bake
recorded vectors (`gen_vectors.py`, N=200, TOL=1e-4 predefined) → `idf.py
build` → `idf_size` summary.

## Execute in emulation (no hardware needed)

```sh
# Espressif QEMU (installed via: idf_tools.py install qemu-xtensa)
python3 firmware/esp32/qemu_test.py     # scenarios A-D + parity vs torch
```

## Execute on Wokwi (needs WOKWI_CLI_TOKEN)

```sh
WOKWI_CLI_TOKEN=<token> python3 firmware/esp32/sim_test.py
```

CI: `.github/workflows/openflight-esp32.yml` (QEMU job needs no secret;
Wokwi job skips gracefully without the token).

## Evidence

`docs/ESP32_SIM_EVALUATION.md`, `results/esp32/`. Simulator timing is
NOT a silicon performance claim.
