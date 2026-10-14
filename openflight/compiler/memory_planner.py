"""Static activation memory planner (buffer-lifetime / register-style)."""
from __future__ import annotations

from openflight.compiler.graph import Graph


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """Closed-interval overlap: a shared endpoint counts as conflict.

    Tensor k is live on the closed interval [k, k + 1]: produced by node k
    and consumed by node k + 1. The shared endpoint models the handoff —
    the producer's output must still be readable while the consumer reads
    it — which is exactly what the generated ping-pong code requires
    (src stays live while dst is written).
    """
    return a[0] <= b[1] and b[0] <= a[1]


def plan_memory(graph: Graph) -> dict:
    """Sequential chain: each tensor live from creation to last use (next node).

    Allocate non-overlapping lifetimes to shared physical buffers (greedy
    interval coloring). Returns plan with offsets, sizes, peak.
    """
    # tensor sizes in floats (batch dim assumed 1 for MCU; use feature dim)
    sizes = []
    for n in graph.nodes:
        # output_shape like (1, F) or (F,)
        f = n.output_shape[-1]
        sizes.append(int(f))
    # lifetimes: tensor k produced by node k, consumed by node k+1 (except last)
    intervals = []
    for k in range(len(sizes)):
        start = k
        end = k + 1 if k < len(sizes) - 1 else k  # last consumed immediately
        intervals.append((start, end))
    # greedy coloring: first color not used by any overlapping earlier tensor
    color_of: list[int] = []
    for k, iv in enumerate(intervals):
        used = {color_of[j] for j in range(k) if _overlaps(iv, intervals[j])}
        c = 0
        while c in used:
            c += 1
        color_of.append(c)
    nbuf = max(color_of) + 1 if color_of else 0
    # buffer sizes = max tensor assigned
    buf_floats = [0] * nbuf
    atores = []
    for k, c in enumerate(color_of):
        buf_floats[c] = max(buf_floats[c], sizes[k])
    # offsets: pack buffers contiguously
    offsets = []
    off = 0
    for bf in buf_floats:
        offsets.append(off)
        off += bf * 4
    for k, c in enumerate(color_of):
        atores.append({"tensor": f"t{k}", "op": graph.nodes[k].operation,
                       "floats": sizes[k], "bytes": sizes[k] * 4,
                       "buffer": c, "offset": offsets[c]})
    peak = off
    return {"tensors": atores, "buffers": [
        {"id": i, "floats": bf, "bytes": bf * 4, "offset": offsets[i]}
        for i, bf in enumerate(buf_floats)],
        "peak_activation_bytes": peak,
        "peak_activation_floats": peak // 4 if peak else 0,
        "strategy": "greedy interval-coloring, ping-pong safe (adjacent conflict)"}
