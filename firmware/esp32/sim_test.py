#!/usr/bin/env python3
"""Drive the simulated ESP32 firmware over Wokwi serial (scenarios A-D).

Transport: launches `wokwi-cli <proj> --timeout S` as a subprocess and talks
to its stdio as the UART byte stream (wokwi-cli forwards target serial to
stdout/stdin in interactive runs; in CI the same scenarios run against the
serial log where applicable). ROM boot chatter is absorbed by frame resync:
the driver scans for the first valid (ver,type,len,crc) header instead of
assuming alignment.

Scenarios:
  A valid deployment: HELLO, CONFIGURE(60,1), N RUN_TESTs on recorded
    windows -> RESULT each, parity vs torch refs within TOL.
  B corrupted CRC: prediction request with flipped CRC byte -> ERROR, and no
    RESULT is produced for that seq.
  C invalid order: RUN_TEST before CONFIGURE -> explicit ERROR.
  D broken link: truncated header then EOF on a second instance -> process
    exits nonzero without hanging (local harness equivalent; Wokwi instances
    cannot be half-closed, so D runs against firmware/host_sim locally).

Requires WOKWI_CLI_TOKEN for live simulation; without it the script reports
SKIP (exit 0) instead of failing. Numerical expectations are identical to the
host-firmware harness (TOL=1e-4, predefined).
"""
import os
import select
import struct
import subprocess
import sys

import numpy as np
import torch

WOKWI = os.environ.get("WOKWI_CLI", "wokwi-cli")
PROJ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wokwi")
TOL = 1e-4
N = 50

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", ".."))
from openflight.benchmark import protocol as P  # noqa: E402


def recorded():
    import learned_observer as L
    from macondo_hover import Airframe
    rng = np.random.default_rng(7)
    af = Airframe()
    t = np.arange(int(5.0 * L.LOOP_HZ)) / L.LOOP_HZ
    wind = L.wind_array("step", t, 22.3, rng, rise=0.15, t_gust=0.5)
    r = L.rollout(af, 0.025, 0.003, 0.030, wind, "analytic",
                  noise_sigma=0.05, rng=rng, t_end=5.0, collect=True)
    return r["X"].astype(np.float32)[:N]


class Link:
    def __init__(self, proc):
        self.p = proc
        self.buf = b""
        self.results = 0

    def send(self, mtype, seq, payload=b""):
        self.p.stdin.write(P.encode(mtype, seq, payload))
        self.p.stdin.flush()

    def recv(self, timeout=30):
        out = self.p.stdout
        while True:
            try:
                msgs, rest = P.decode_stream(self.buf)
            except ValueError:
                # resync: drop one byte (ROM chatter / misalignment), continue
                self.buf = self.buf[1:]
                continue
            if msgs:
                self.buf = rest
                return msgs[0]
            r, _, _ = select.select([out], [], [], timeout)
            if not r:
                raise TimeoutError("sim response timeout")
            chunk = os.read(out.fileno(), 65536)
            if not chunk:
                raise EOFError("sim closed link")
            self.buf += chunk


def main() -> int:
    if not os.environ.get("WOKWI_CLI_TOKEN"):
        print("SKIP: WOKWI_CLI_TOKEN not set (simulation needs an API token)")
        return 0
    X = recorded()
    ck = torch.load("learned_observer.pt", map_location="cpu",
                    weights_only=True)
    mean = np.asarray(ck["mean"], dtype=np.float32)
    std = np.asarray(ck["std"], dtype=np.float32)
    Xn = ((X - mean) / std).astype(np.float32)
    from openflight.cli import _arch_for_example
    model = _arch_for_example("mlp:60,128,64,1")
    sd = {k[4:] if k.startswith("mlp.") else k: v
          for k, v in ck["model"].items()}
    model.load_state_dict(sd)
    model.eval()
    with torch.no_grad():
        ref = model(torch.from_numpy(Xn)).numpy().reshape(-1)

    proc = subprocess.Popen([WOKWI, PROJ, "--timeout", "180"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)
    try:
        link = Link(proc)
        # A: handshake + configure
        link.send(P.HELLO, 0, b"host")
        mt, sq, body = link.recv()
        assert (mt, sq) == (P.HELLO, 0), (mt, sq, body[:40])
        assert body.startswith(b"openflight-fw-esp32"), body[:40]
        link.send(P.RUN_TEST, 1, Xn[0].tobytes())  # C: premature first
        mt, sq, body = link.recv()
        assert mt == P.ERROR, (mt, body)
        link.send(P.CONFIGURE, 2, struct.pack("<HH", 60, 1))
        mt, sq, body = link.recv()
        assert (mt, sq, body) == (P.CONFIGURE, 2, b"")
        link.send(P.CONFIGURE, 3, struct.pack("<HH", 12, 3))  # wrong sizes
        mt, sq, body = link.recv()
        assert mt == P.ERROR, (mt, body)
        # A: N recorded predictions
        worst = 0.0
        for i in range(N):
            link.send(P.RUN_TEST, 10 + i, Xn[i].tobytes())
            mt, sq, body = link.recv()
            assert mt == P.RESULT and sq == 10 + i, (mt, sq, body[:40])
            lat = struct.unpack("<I", body[:4])[0]
            y = np.frombuffer(body[4:], dtype=np.float32)
            assert y.shape == (1,) and np.isfinite(y).all()
            worst = max(worst, float(abs(y[0] - ref[i])))
            if i == 0:
                print(f"first RESULT latency_us={lat} (simulator clock only)")
        # B: corrupted CRC -> ERROR, no RESULT for that seq
        bad = bytearray(P.encode(P.RUN_TEST, 9000, Xn[0].tobytes()))
        bad[-1] ^= 0xFF
        proc.stdin.write(bytes(bad))
        proc.stdin.flush()
        mt, sq, body = link.recv()
        assert mt == P.ERROR and sq == 9000, (mt, sq, body)
        print(f"SIM parity: N={N} max_abs_err={worst:.3e} tol={TOL:.1e}")
        assert worst < TOL, worst
        print("SIM scenarios A+B+C: PASS")
        return 0
    finally:
        try:
            proc.stdin.close()
        except BrokenPipeError:
            pass
        proc.wait(timeout=60)


if __name__ == "__main__":
    sys.exit(main())
