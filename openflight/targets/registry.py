"""Deployment targets: flags, timers, memory limits, flashing (opt-in)."""
from __future__ import annotations

TARGETS = {
    "generic-cortex-m": {
        "cxx": "arm-none-eabi-g++", "flags": ["-O2", "-mcpu=cortex-m4", "-mthumb"],
        "timer": "DWT cycle counter",
        "flash_kb": 1024, "ram_kb": 256,
        "flash_cmd": None,
    },
    "esp32": {
        "cxx": "xtensa-esp32-elf-g++", "flags": ["-O2"],
        "timer": "ESP cycle counter (ccount)",
        "flash_kb": 4096, "ram_kb": 520,
        "flash_cmd": "idf.py flash (opt-in: --flash)",
    },
    "stm32": {
        "cxx": "arm-none-eabi-g++", "flags": ["-O2", "-mcpu=cortex-m7"],
        "timer": "DWT cycle counter",
        "flash_kb": 2048, "ram_kb": 512,
        "flash_cmd": "st-flash / openocd (opt-in: --flash)",
    },
    "host": {
        "cxx": "c++", "flags": ["-O2", "-std=c++17"],
        "timer": "clock_gettime(CLOCK_MONOTONIC)",
        "flash_kb": -1, "ram_kb": -1,
        "flash_cmd": None,
    },
}


def get(name: str) -> dict:
    if name not in TARGETS:
        raise ValueError(f"unknown target {name}; choose {sorted(TARGETS)}")
    return TARGETS[name]
