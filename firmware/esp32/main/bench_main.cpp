// OpenFlight ESP32 benchmark firmware (ESP-IDF, UART0 protocol).
//
// Same wire protocol as firmware/generic/benchmark_main.cpp (ported, not
// shared: ESP-IDF UART + esp_timer replace the HAL):
//   header <u8 ver><u8 type><u16 seq><u32 len><u16 crc> LE (10 bytes),
//   crc = zlib.crc32(payload) & 0xFFFF.
//   HELLO=1 CONFIGURE=2 RUN_TEST=3 RESULT=4 ERROR=255.
//   CONFIGURE payload <u16 in><u16 out>; RUN_TEST payload INPUT_SIZE f32 LE;
//   RESULT payload <u32 latency_us><f32 outputs>; ERROR payload ASCII.
// At boot the firmware runs SELFTEST_N recorded vectors from flash through
// openflight::predict() and prints one greppable line:
//   SELFTEST maxerr=<e> N=<n> TOL=<t> PASS|FAIL
// then enters the protocol loop. Inference ALWAYS runs inside this firmware;
// the host never substitutes its own computation.
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>

#include "driver/uart.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "model.h"
#include "test_vectors.h"

namespace {

constexpr uint8_t VER = 1;
constexpr uint8_t T_HELLO = 1, T_CONFIGURE = 2, T_RUN_TEST = 3, T_RESULT = 4,
                  T_ERROR = 255;
constexpr size_t HDRLEN = 10;
constexpr size_t MAX_PAYLOAD = 4096;
constexpr uart_port_t PORT = UART_NUM_0;
constexpr int RX_BUF = 8192, TX_BUF = 4096;

uint32_t crc_table_[256];
uint8_t rx_[HDRLEN + MAX_PAYLOAD];
uint8_t tx_[HDRLEN + MAX_PAYLOAD];
float in_[openflight::INPUT_SIZE > 0 ? openflight::INPUT_SIZE : 1];
float out_[openflight::OUTPUT_SIZE > 0 ? openflight::OUTPUT_SIZE : 1];

void crc_init() {
    for (uint32_t i = 0; i < 256; i++) {
        uint32_t c = i;
        for (int k = 0; k < 8; k++)
            c = (c & 1) ? (0xEDB88320u ^ (c >> 1)) : (c >> 1);
        crc_table_[i] = c;
    }
}
uint16_t crc16(const uint8_t* p, size_t n) {
    uint32_t c = 0xFFFFFFFFu;
    for (size_t i = 0; i < n; i++)
        c = crc_table_[(c ^ p[i]) & 0xFF] ^ (c >> 8);
    return static_cast<uint16_t>((c ^ 0xFFFFFFFFu) & 0xFFFFu);
}
void put16(uint8_t* b, uint16_t v) {
    b[0] = v & 0xFF;
    b[1] = (v >> 8) & 0xFF;
}
void put32(uint8_t* b, uint32_t v) {
    b[0] = v & 0xFF;
    b[1] = (v >> 8) & 0xFF;
    b[2] = (v >> 16) & 0xFF;
    b[3] = (v >> 24) & 0xFF;
}
uint16_t get16(const uint8_t* b) {
    return static_cast<uint16_t>(b[0] | (b[1] << 8));
}
uint32_t get32(const uint8_t* b) {
    return static_cast<uint32_t>(b[0] | (b[1] << 8) | (b[2] << 16) |
                                 (b[3] << 24));
}
// Blocking read of exactly n bytes; returns false only on fatal UART error.
bool read_full(uint8_t* b, size_t n) {
    size_t got = 0;
    while (got < n) {
        int r = uart_read_bytes(PORT, b + got, n - got,
                                pdMS_TO_TICKS(5000));
        if (r <= 0) return false;
        got += static_cast<size_t>(r);
    }
    return true;
}
void send(uint8_t type, uint16_t seq, const uint8_t* p, size_t n) {
    tx_[0] = VER;
    tx_[1] = type;
    put16(tx_ + 2, seq);
    put32(tx_ + 4, static_cast<uint32_t>(n));
    put16(tx_ + 8, crc16(p ? p : tx_, n));
    if (n) memcpy(tx_ + HDRLEN, p, n);
    uart_write_bytes(PORT, tx_, HDRLEN + n);
}
void send_error(uint16_t seq, const char* msg) {
    size_t n = strlen(msg);
    if (n > 200) n = 200;
    send(T_ERROR, seq, reinterpret_cast<const uint8_t*>(msg), n);
}

#define SELFTEST_SAMPLES_TO_PRINT 8

void run_selftest() {
    // Contract-adapted recorded windows are baked in already normalized;
    // inference path is identical to RUN_TEST (same predict call).
    float worst = 0.0f;
    for (int k = 0; k < SELFTEST_N; k++) {
        float y[openflight::OUTPUT_SIZE];
        openflight::predict(&SELFTEST_X[k * openflight::INPUT_SIZE], y);
        for (size_t i = 0; i < openflight::OUTPUT_SIZE; i++) {
            float d = fabsf(y[i] - SELFTEST_REF[k * openflight::OUTPUT_SIZE + i]);
            if (!(d <= worst)) worst = d;  // NaN-safe max
        }
        if (k < SELFTEST_SAMPLES_TO_PRINT) {
            char line[128];
            snprintf(line, sizeof(line), "STEST sample=%d err=%.3e\r\n", k, worst);
            uart_write_bytes(PORT, line, strlen(line));
        }
    }
    char line[128];
    snprintf(line, sizeof(line), "SELFTEST maxerr=%.3e N=%d TOL=%.1e %s\r\n",
             (double)worst, SELFTEST_N, (double)SELFTEST_TOL,
             worst <= SELFTEST_TOL ? "PASS" : "FAIL");
    uart_write_bytes(PORT, line, strlen(line));
}

}  // namespace

extern "C" void app_main() {
    crc_init();
    uart_config_t cfg = {};
    cfg.baud_rate = 115200;
    cfg.data_bits = UART_DATA_8_BITS;
    cfg.parity = UART_PARITY_DISABLE;
    cfg.stop_bits = UART_STOP_BITS_1;
    cfg.flow_ctrl = UART_HW_FLOWCTRL_DISABLE;
    cfg.source_clk = UART_SCLK_DEFAULT;
    uart_driver_install(PORT, RX_BUF, TX_BUF, 0, nullptr, 0);
    uart_param_config(PORT, &cfg);
    // Drain boot-ROM chatter so the first protocol bytes are ours. Any
    // residual bytes are handled by host-side resync (documented).
    vTaskDelay(pdMS_TO_TICKS(300));
    uint8_t drain[256];
    int r = 0;
    do {
        r = uart_read_bytes(PORT, drain, sizeof(drain), pdMS_TO_TICKS(50));
    } while (r > 0);

    run_selftest();

    /* Stack high-water mark of the calling (main) task, in BYTES.
       Verified against ESP-IDF v5.3 source: portSTACK_TYPE is uint8_t on
       Xtensa (portmacro.h), so uxTaskGetStackHighWaterMark returns bytes,
       not FreeRTOS words. Printed after the 200-window selftest workload
       (before the protocol loop). Written via uart_write_bytes (not printf)
       so it reaches the protocol UART after uart_driver_install. */
    uint32_t hw_bytes = uxTaskGetStackHighWaterMark(NULL);
    char stack_line[128];
    snprintf(stack_line, sizeof(stack_line),
             "STACK_HIGHWATER_BYTES=%lu (after 200-window selftest, before protocol loop)\r\n",
             static_cast<unsigned long>(hw_bytes));
    uart_write_bytes(PORT, stack_line, strlen(stack_line));

    bool configured = false;
    for (;;) {
        if (!read_full(rx_, HDRLEN)) continue;  // UART error: keep serving
        uint8_t ver = rx_[0], type = rx_[1];
        uint16_t seq = get16(rx_ + 2);
        uint32_t ln = get32(rx_ + 4);
        uint16_t crc = get16(rx_ + 8);
        if (ver != VER) {
            send_error(seq, "bad version");
            continue;
        }
        if (ln > MAX_PAYLOAD) {
            send_error(seq, "length over cap");
            continue;
        }
        if (ln && !read_full(rx_ + HDRLEN, ln)) continue;
        const uint8_t* pl = rx_ + HDRLEN;
        if (crc16(pl, ln) != crc) {
            send_error(seq, "crc mismatch");
            continue;
        }
        if (type == T_HELLO) {
            const char* hi = "openflight-fw-esp32/1";
            send(T_HELLO, seq, reinterpret_cast<const uint8_t*>(hi),
                 strlen(hi));
        } else if (type == T_CONFIGURE) {
            if (ln != 4) {
                send_error(seq, "CONFIGURE needs 4 payload bytes");
                continue;
            }
            uint16_t wi = get16(pl), wo = get16(pl + 2);
            if (wi != openflight::INPUT_SIZE ||
                wo != openflight::OUTPUT_SIZE) {
                send_error(seq, "CONFIGURE size mismatch vs firmware model");
                continue;
            }
            configured = true;
            send(T_CONFIGURE, seq, nullptr, 0);
        } else if (type == T_RUN_TEST) {
            if (!configured) {
                send_error(seq, "RUN_TEST before CONFIGURE");
                continue;
            }
            if (ln != openflight::INPUT_SIZE * sizeof(float)) {
                send_error(seq, "RUN_TEST payload size mismatch");
                continue;
            }
            memcpy(in_, pl, ln);
            // ---- timed region: predict() only, no serial ----
            int64_t t0 = esp_timer_get_time();
            openflight::predict(in_, out_);
            int64_t t1 = esp_timer_get_time();
            // --------------------------------------------------
            int64_t us = t1 - t0;
            if (us < 0) us = 0;
            uint8_t rp[4 + sizeof(out_)];
            put32(rp, us > 0xFFFFFFFFLL ? 0xFFFFFFFFu
                                        : static_cast<uint32_t>(us));
            memcpy(rp + 4, out_, sizeof(out_));
            send(T_RESULT, seq, rp, sizeof(rp));
        } else {
            send_error(seq, "unknown message type");
        }
    }
}
