"""Firmware harness test (Priority A, host-executed).

Builds the UNMODIFIED firmware/benchmark_main.cpp against the compiled
observer model + host-sim HAL, then drives it over pipes with the real
protocol: HELLO, CONFIGURE (right + wrong sizes), N RUN_TESTs with recorded
gust windows, CRC corruption, unknown type, truncated stream.

Asserts: outputs match torch on recorded inputs; CONFIGURE gates RUN_TEST;
errors are ERROR replies (never silent); dead link exits nonzero without
hanging. Latency distribution is reported as OBSERVED host-sim values only —
not MCU evidence (see HARDWARE_PLAN.md).
"""
import json
import os
import struct
import subprocess

import numpy as np
import torch

from openflight.benchmark import protocol as P

REPORT = "results/firmware_harness.json"
N = 200


def _recorded():
    import learned_observer as L
    from macondo_hover import Airframe
    rng = np.random.default_rng(7)
    af = Airframe()
    t = np.arange(int(5.0 * L.LOOP_HZ)) / L.LOOP_HZ
    wind = L.wind_array("step", t, 22.3, rng, rise=0.15, t_gust=0.5)
    r = L.rollout(af, 0.025, 0.003, 0.030, wind, "analytic",
                  noise_sigma=0.05, rng=rng, t_end=5.0, collect=True)
    return r["X"].astype(np.float32)[:N]


def _build(tmp_path):
    from openflight.compiler.api import compile_model
    from openflight.cli import _arch_for_example
    bdir = str(tmp_path / "build")
    out = compile_model(_arch_for_example("mlp:60,128,64,1"),
                        "learned_observer.pt", bdir)
    fw = os.path.abspath("firmware")
    exe = str(tmp_path / "fw")
    pr = subprocess.run(
        ["c++", "-O2", "-std=c++17", "-Wall",
         "-I", bdir, "-I", os.path.join(fw, "generic"),
         os.path.join(fw, "generic", "benchmark_main.cpp"),
         os.path.join(fw, "host_sim", "hal_host.cpp"),
         os.path.join(bdir, "model.cpp"), "-o", exe],
        capture_output=True, text=True)
    assert pr.returncode == 0, pr.stderr[:3000]
    # no-heap check on the firmware image path (host objects)
    assert "malloc" not in pr.stderr
    return exe, out


class Link:
    def __init__(self, proc):
        self.p = proc
        self.buf = b""

    def send(self, mtype, seq, payload=b""):
        self.p.stdin.write(P.encode(mtype, seq, payload))
        self.p.stdin.flush()

    def recv(self, timeout=15):
        import select
        out = self.p.stdout
        while True:
            msgs, rest = P.decode_stream(self.buf)
            if msgs:
                self.buf = rest
                return msgs[0]
            r, _, _ = select.select([out], [], [], timeout)
            assert r, "firmware response timeout"
            chunk = os.read(out.fileno(), 65536)
            assert chunk, "firmware closed link unexpectedly"
            self.buf += chunk


def test_firmware_end_to_end(tmp_path):
    exe, out = _build(tmp_path)
    X = _recorded()
    ck = torch.load("learned_observer.pt", map_location="cpu",
                    weights_only=True)
    mean = np.asarray(ck["mean"], dtype=np.float32)
    std = np.asarray(ck["std"], dtype=np.float32)
    Xn = ((X - mean) / std).astype(np.float32)
    with torch.no_grad():
        ref = out["model"](torch.from_numpy(Xn)).numpy().reshape(-1)

    proc = subprocess.Popen([exe], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)
    try:
        link = Link(proc)
        # HELLO
        link.send(P.HELLO, 0, b"host")
        mt, sq, body = link.recv()
        assert (mt, sq) == (P.HELLO, 0)
        # RUN_TEST before CONFIGURE -> ERROR
        link.send(P.RUN_TEST, 1, Xn[0].tobytes())
        mt, sq, body = link.recv()
        assert mt == P.ERROR, (mt, body)
        # CONFIGURE wrong sizes -> ERROR
        link.send(P.CONFIGURE, 2, struct.pack("<HH", 12, 3))
        mt, sq, body = link.recv()
        assert mt == P.ERROR, (mt, body)
        # CONFIGURE right sizes -> ack
        link.send(P.CONFIGURE, 3, struct.pack("<HH", 60, 1))
        mt, sq, body = link.recv()
        assert (mt, sq, body) == (P.CONFIGURE, 3, b"")
        # RUN_TEST with wrong payload length -> ERROR
        link.send(P.RUN_TEST, 4, b"\x00" * 8)
        mt, sq, body = link.recv()
        assert mt == P.ERROR, (mt, body)
        # N recorded RUN_TESTs
        import time
        lats, got = [], []
        for i in range(N):
            t0 = time.monotonic_ns()
            link.send(P.RUN_TEST, 5 + i, Xn[i].tobytes())
            mt, sq, body = link.recv()
            t1 = time.monotonic_ns()
            assert mt == P.RESULT and sq == 5 + i, (mt, sq, body[:50])
            lat_us = struct.unpack("<I", body[:4])[0]
            y = np.frombuffer(body[4:], dtype=np.float32)
            assert y.shape == (1,)
            lats.append(lat_us)
            got.append(float(y[0]))
            # firmware-reported (predict-only) latency fits inside round trip
            assert lat_us * 1000 <= (t1 - t0), (lat_us, (t1 - t0) // 1000)
        got = np.array(got)
        err = np.abs(got - ref)
        assert np.isfinite(got).all()
        assert float(err.max()) < 1e-4, float(err.max())
        # CRC corruption -> ERROR, link stays alive
        bad = bytearray(P.encode(P.RUN_TEST, 9000, Xn[0].tobytes()))
        bad[-1] ^= 0xFF
        proc.stdin.write(bytes(bad))
        proc.stdin.flush()
        mt, sq, body = link.recv()
        assert mt == P.ERROR and sq == 9000, (mt, sq, body)
        assert b"crc" in body
        # unknown type -> ERROR
        link.send(99, 9001, b"")
        mt, sq, body = link.recv()
        assert mt == P.ERROR, (mt, body)
        lat = np.array(lats, dtype=float)
        summary = {"n": N, "min_us": float(lat.min()),
                   "median_us": float(np.median(lat)),
                   "p95_us": float(np.percentile(lat, 95)),
                   "max_observed_us": float(lat.max()),
                   "max_abs_err": float(err.max()),
                   "mean_abs_err": float(err.mean())}
    finally:
        proc.stdin.close()
        proc.wait(timeout=15)
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w") as f:
        json.dump({"timer": "host-sim clock_gettime (NOT MCU evidence)",
                   "model": "learned_observer.pt", "n": N,
                   "gate_checks": "HELLO/CONFIGURE-gating/CRC/unknown-type "
                                  "all answered, link alive",
                   "latency_observed_us": summary,
                   "note": "observed maxima are not WCET bounds"},
                  f, indent=2)
    print("\nfirmware harness: " +
          f"n={N} max_abs_err={summary['max_abs_err']:.3e} " +
          f"lat p50={summary['median_us']:.1f}us p95={summary['p95_us']:.1f}us " +
          f"max_obs={summary['max_observed_us']:.1f}us")


def test_firmware_dead_link_exits(tmp_path):
    exe, _ = _build(tmp_path)
    proc = subprocess.Popen([exe], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)
    # truncated header then EOF: must exit nonzero, must not hang
    proc.stdin.write(b"\x01\x03")
    proc.stdin.close()
    assert proc.wait(timeout=15) != 0
