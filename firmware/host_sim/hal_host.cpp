// Host-simulation HAL: stdin/stdout transport + clock_gettime ticks.
//
// This executes the UNMODIFIED firmware logic (benchmark_main.cpp) on the
// host so the protocol handling, CONFIGURE gating, error paths, and
// predict-only timing separation are tested for real. What it does NOT prove:
// real MCU timer behavior (DWT/ccount), linker-map sizes, stack high-water
// mark, or on-silicon latency — see HARDWARE_PLAN.md.
#include "hal.h"

#include <ctime>
#include <unistd.h>

std::size_t hal_serial_read(uint8_t* buf, std::size_t len) {
    std::size_t got = 0;
    while (got < len) {
        ssize_t r = ::read(STDIN_FILENO, buf + got, len - got);
        if (r <= 0) return got;  // EOF/error: 0 signals dead link
        got += static_cast<std::size_t>(r);
    }
    return got;
}

void hal_serial_write(const uint8_t* buf, std::size_t len) {
    std::size_t sent = 0;
    while (sent < len) {
        ssize_t r = ::write(STDOUT_FILENO, buf + sent, len - sent);
        if (r <= 0) return;
        sent += static_cast<std::size_t>(r);
    }
}

uint32_t hal_timer_ticks() {
    timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    uint64_t ns = static_cast<uint64_t>(ts.tv_sec) * 1000000000u +
                  static_cast<uint64_t>(ts.tv_nsec);
    return static_cast<uint32_t>(ns & 0xFFFFFFFFu);
}

uint32_t hal_ticks_per_second() { return 1000000000u; }
