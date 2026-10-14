// OpenFlight firmware HAL: serial byte stream + monotonic tick counter.
//
// Porting contract (MCU target):
//   hal_serial_read  — block until `len` bytes received or return < len on
//                      fatal link error. Must NOT return partial data silently.
//   hal_serial_write — block until all bytes are queued/sent.
//   hal_timer_ticks  — monotonic tick counter, arbitrary epoch.
//   hal_ticks_per_second — tick rate (e.g. DWT CYCCNT: cpu_hz; ESP ccount:
//                      cpu_hz). Latency math needs no float on target.
// The benchmark loop measures predict() only; serial bytes are outside the
// timed region by construction (see benchmark_main.cpp).
#pragma once
#include <cstddef>
#include <cstdint>

std::size_t hal_serial_read(uint8_t* buf, std::size_t len);
void hal_serial_write(const uint8_t* buf, std::size_t len);
uint32_t hal_timer_ticks();
uint32_t hal_ticks_per_second();
