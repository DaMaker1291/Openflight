"""Phase 4 audit: protocol robustness, statistics, reports, runner edges."""
import numpy as np
import pytest

from openflight.benchmark import protocol as P
from openflight.benchmark import statistics as S
from openflight.benchmark import reports as R


def test_protocol_edges():
    with pytest.raises(ValueError):  # short header
        P.decode(b"\x01\x02")
    pkt = P.encode(P.RUN_TEST, 7, b"\x01\x02")
    with pytest.raises(ValueError):  # truncated payload
        P.decode(pkt[:-1])
    bad_ver = bytearray(pkt)
    bad_ver[0] = 99
    with pytest.raises(ValueError):
        P.decode(bytes(bad_ver))
    bad_crc = bytearray(pkt)
    bad_crc[-1] ^= 0xFF
    with pytest.raises(ValueError):
        P.decode(bytes(bad_crc))
    with pytest.raises(ValueError):  # declared length over cap
        P.decode(P.HEADER.pack(1, P.RUN_TEST, 0, P.MAX_PAYLOAD + 1, 0) + b"\x00")
    mt, seq, body = P.decode(P.encode(P.HELLO, 0))  # empty payload ok
    assert (mt, seq, body) == (P.HELLO, 0, b"")


def test_decode_stream_deframing():
    a = P.encode(P.HELLO, 0, b"hi")
    b = P.encode(P.RESULT, 1, b"\x00" * 12)
    msgs, left = P.decode_stream(a + b)
    assert [m[0] for m in msgs] == [P.HELLO, P.RESULT]
    assert left == b""
    msgs, left = P.decode_stream(a + b[:5])  # incomplete second message
    assert len(msgs) == 1 and left == b[:5]
    P.check_seq(msgs)
    with pytest.raises(ValueError):  # gap
        P.check_seq([(P.HELLO, 0, b""), (P.HELLO, 2, b"")])
    with pytest.raises(ValueError):  # replay
        P.check_seq([(P.HELLO, 0, b""), (P.HELLO, 0, b"")])


def test_statistics_known_values():
    lat = np.array([10., 20., 30., 40., 100.])
    s = S.summarize(lat, deadline_us=50.0)
    assert s["n"] == 5 and s["min_us"] == 10.0 and s["median_us"] == 30.0
    assert s["max_us"] == 100.0 and s["mean_us"] == 40.0
    assert s["deadline_misses"] == 1
    assert abs(s["deadline_miss_rate"] - 0.2) < 1e-12
    assert s["p95_us"] >= s["median_us"]


def test_reports_all_files(tmp_path):
    lat = np.array([5., 6., 7.])
    info = R.write_reports(
        str(tmp_path), {"stats": S.summarize(lat), "raw": lat.tolist()},
        {"max_abs_err": 1e-7, "pass": True}, {"weight_bytes": 100},
        {"schema_version": 1})
    for f in ("raw_latency.csv", "summary.json", "memory_report.json",
              "correctness_report.json", "benchmark_report.html",
              "benchmark_table.tex", "experiment_manifest.json"):
        assert f in info["files"], f
