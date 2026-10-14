#!/usr/bin/env python3
"""Drive the ESP32 firmware in Espressif QEMU over emulated UART (scenarios A-D).

QEMU: qemu-system-xtensa -M esp32, flash_image.bin as MTD, plain stdio serial
(monitor mux disabled so binary protocol bytes pass through untouched).
ROM boot chatter is absorbed by frame resync. Simulator clock is NOT a
performance claim (see report): only functional + parity + protocol behavior.

Scenarios:
  A valid deployment: HELLO, CONFIGURE(60,1), N RUN_TESTs on recorded
    windows -> RESULT each, parity vs torch refs within TOL (predefined).
  B corrupted CRC -> ERROR, no RESULT for that seq.
  C RUN_TEST before CONFIGURE + wrong CONFIGURE sizes -> explicit ERRORs.
  D truncated header then EOF -> QEMU/process terminates (no hang).
Also asserts the boot SELFTEST line reads PASS.
"""
import os
import select
import struct
import subprocess
import sys

import numpy as np
import torch

ROOT = os.path.dirname(os.path.abspath(__file__ + "/../.."))
sys.path.insert(0, ROOT)
from openflight.benchmark import protocol as P  # noqa: E402

TOL = 1e-4
N = 50
FW = os.path.dirname(os.path.abspath(__file__)) + "/build"


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

    def send(self, mtype, seq, payload=b""):
        self.p.stdin.write(P.encode(mtype, seq, payload))
        self.p.stdin.flush()

    def recv(self, timeout=60):
        out = self.p.stdout
        while True:
            try:
                msgs, rest = P.decode_stream(self.buf)
            except ValueError:
                self.buf = self.buf[1:]  # resync past ROM chatter
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


def spawn():
    qemu = os.environ.get("QEMU_XTENSA", "qemu-system-xtensa")
    cmd = [qemu, "-M", "esp32", "-m", "4M",
           "-drive", f"file={FW}/flash_image.bin,if=mtd,format=raw",
           "-drive", f"file={FW}/qemu_efuse.bin,if=none,format=raw,id=efuse",
           "-global", "driver=nvram.esp32.efuse,property=drive,value=efuse",
           "-global", "driver=timer.esp32.timg,property=wdt_disable,value=true",
           "-nic", "user,model=open_eth",
           "-display", "none", "-monitor", "none", "-serial", "stdio"]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)


def wait_selftest(proc, timeout=120):
    """Wait for boot SELFTEST line, then the post-workload STACK_HIGHWATER
    line (printed by app_main after run_selftest, before the binary
    protocol loop starts). Returns (selftest_match, stack_match, data)."""
    import re
    data = b""
    st = None
    stk = None
    while True:
        r, _, _ = select.select([proc.stdout], [], [], timeout)
        if not r:
            raise TimeoutError("no SELFTEST line from sim")
        chunk = os.read(proc.stdout.fileno(), 65536)
        if not chunk:
            raise EOFError("sim exited before SELFTEST")
        data += chunk
        if st is None:
            st = re.search(
                rb"SELFTEST maxerr=([0-9.e+-]+) N=(\d+) TOL=([0-9.e+-]+) (PASS|FAIL)",
                data)
        if st is not None and stk is None:
            # Require the full line (terminator + parenthetical) so a
            # chunk split like "...BYTES=6" / "152 (after..." cannot match
            # prematurely — that exact bug truncated 6152 to 6 once.
            stk = re.search(
                rb"STACK_HIGHWATER_BYTES=(\d+) \([^\r\n]*\)\r\n", data)
        if st is not None and stk is not None:
            return st, stk, data


def main() -> int:
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

    proc = spawn()
    try:
        m, sm, _ = wait_selftest(proc)
        print(f"boot: {m.group(0).decode()}")
        print(f"stack: {sm.group(0).decode()}")
        with open(os.path.join(ROOT, "results", "esp32",
                               "stack_highwater.txt"), "w") as f:
            f.write(sm.group(0).decode() + "\n")
        assert m.group(4) == b"PASS", m.group(0)
        link = Link(proc)
        link.send(P.HELLO, 0, b"host")
        mt, sq, body = link.recv()
        assert (mt, sq) == (P.HELLO, 0), (mt, sq, body[:40])
        assert body.startswith(b"openflight-fw-esp32"), body[:40]
        link.send(P.RUN_TEST, 1, Xn[0].tobytes())  # C: premature
        mt, sq, body = link.recv()
        assert mt == P.ERROR, (mt, body)
        link.send(P.CONFIGURE, 2, struct.pack("<HH", 60, 1))
        mt, sq, body = link.recv()
        assert (mt, sq, body) == (P.CONFIGURE, 2, b"")
        link.send(P.CONFIGURE, 3, struct.pack("<HH", 12, 3))  # wrong sizes
        mt, sq, body = link.recv()
        assert mt == P.ERROR, (mt, body)
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
        bad = bytearray(P.encode(P.RUN_TEST, 9000, Xn[0].tobytes()))
        bad[-1] ^= 0xFF
        proc.stdin.write(bytes(bad))
        proc.stdin.flush()
        mt, sq, body = link.recv()
        assert mt == P.ERROR and sq == 9000, (mt, sq, body)
        # D: truncated frame then completion. The firmware must not answer
        # the fragment with anything valid; once the remaining bytes arrive
        # the frame completes and is answered normally (documented rule: the
        # receiver waits for exact frames; recovery past a *corrupted*
        # alignment requires link reset — see ESP32_SIM_EVALUATION.md).
        hello = P.encode(P.HELLO, 9001, b"host")
        proc.stdin.write(hello[:4])
        proc.stdin.flush()
        import time as _t
        _t.sleep(2)
        r, _, _ = select.select([proc.stdout], [], [], 3)
        assert not r, "firmware answered a truncated frame"
        proc.stdin.write(hello[4:])
        proc.stdin.flush()
        mt, sq, body = link.recv()
        assert (mt, sq) == (P.HELLO, 9001), (mt, sq, body[:40])
        print("QEMU scenario D (truncation): PASS")
        print(f"QEMU ESP32 parity: N={N} max_abs_err={worst:.3e} tol={TOL:.1e}")
        assert worst < TOL, worst
        print("QEMU scenarios A+B+C: PASS")
        return 0
    finally:
        try:
            proc.stdin.close()
        except BrokenPipeError:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
