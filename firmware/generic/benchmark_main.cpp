// OpenFlight benchmark firmware (generic target).
//
// Protocol (matches openflight/benchmark/protocol.py, VERSION 1):
//   header: <u8 ver><u8 type><u16 seq><u32 len><u16 crc> little-endian
//           (10 bytes), crc = zlib.crc32(payload) & 0xFFFF (table below is
//           zlib-compatible)
//   types:  HELLO=1, CONFIGURE=2, RUN_TEST=3, RESULT=4, ERROR=255
//   CONFIGURE payload: <u16 input_size><u16 output_size> (must match model)
//   RUN_TEST payload:  INPUT_SIZE float32 LE samples
//   RESULT payload:    <u32 latency_us><float32 outputs...>  (predict-only)
//   ERROR payload:     ASCII message (seq echoes the offending message)
//
// No heap: all buffers are fixed-size globals. Error policy: malformed input
// yields an ERROR reply (or exit on dead link), never silent misbehavior.
#include "hal.h"
#include "model.h"

#include <cstdint>
#include <cstring>

namespace {

constexpr uint8_t VER = 1;
constexpr uint8_t T_HELLO = 1, T_CONFIGURE = 2, T_RUN_TEST = 3, T_RESULT = 4,
                  T_ERROR = 255;
constexpr std::size_t HDRLEN = 10;  // <BBHIH: ver,type,seq16,len32,crc16
constexpr std::size_t MAX_PAYLOAD = 4096;

uint32_t crc_table_[256];
bool crc_ready_ = false;
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
    crc_ready_ = true;
}

uint16_t crc16(const uint8_t* p, std::size_t n) {
    if (!crc_ready_) crc_init();
    uint32_t c = 0xFFFFFFFFu;
    for (std::size_t i = 0; i < n; i++)
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

bool read_full(uint8_t* b, std::size_t n) {
    std::size_t got = 0;
    while (got < n) {
        std::size_t r = hal_serial_read(b + got, n - got);
        if (r == 0) return false;  // dead link: caller exits, never spins
        got += r;
    }
    return true;
}

void send(uint8_t type, uint16_t seq, const uint8_t* p, std::size_t n) {
    tx_[0] = VER;
    tx_[1] = type;
    put16(tx_ + 2, seq);
    put32(tx_ + 4, static_cast<uint32_t>(n));
    put16(tx_ + 8, crc16(p ? p : tx_, n));
    if (n) std::memcpy(tx_ + HDRLEN, p, n);
    hal_serial_write(tx_, HDRLEN + n);
}

void send_error(uint16_t seq, const char* msg) {
    std::size_t n = std::strlen(msg);
    if (n > 200) n = 200;
    send(T_ERROR, seq, reinterpret_cast<const uint8_t*>(msg), n);
}

}  // namespace

int main() {
    crc_init();
    bool configured = false;
    for (;;) {
        if (!read_full(rx_, HDRLEN)) return 1;  // link dead: exit nonzero
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
        if (ln && !read_full(rx_ + HDRLEN, ln)) return 1;
        const uint8_t* pl = rx_ + HDRLEN;
        if (crc16(pl, ln) != crc) {
            send_error(seq, "crc mismatch");
            continue;
        }
        if (type == T_HELLO) {
            const char* hi = "openflight-fw/1";
            send(T_HELLO, seq, reinterpret_cast<const uint8_t*>(hi),
                 std::strlen(hi));
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
            std::memcpy(in_, pl, ln);
            // ---- timed region: predict() only, no serial ----
            uint32_t t0 = hal_timer_ticks();
            openflight::predict(in_, out_);
            uint32_t t1 = hal_timer_ticks();
            // --------------------------------------------------
            uint32_t tps = hal_ticks_per_second();
            uint64_t us =
                (static_cast<uint64_t>(t1 - t0) * 1000000u) / (tps ? tps : 1u);
            uint8_t rp[4 + sizeof(out_)];
            put32(rp, us > 0xFFFFFFFFu ? 0xFFFFFFFFu
                                      : static_cast<uint32_t>(us));
            std::memcpy(rp + 4, out_, sizeof(out_));
            send(T_RESULT, seq, rp, sizeof(rp));
        } else {
            send_error(seq, "unknown message type");
        }
    }
    return 0;
}
