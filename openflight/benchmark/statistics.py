"""Latency statistics: distribution, never a single number."""
from __future__ import annotations

import numpy as np


def summarize(lat_us: np.ndarray, deadline_us: float | None = None) -> dict:
    lat = np.asarray(lat_us, dtype=float)
    out = {
        "n": int(lat.size),
        "min_us": float(np.min(lat)) if lat.size else float("nan"),
        "median_us": float(np.median(lat)) if lat.size else float("nan"),
        "p95_us": float(np.percentile(lat, 95)) if lat.size else float("nan"),
        "p99_us": float(np.percentile(lat, 99)) if lat.size else float("nan"),
        "max_us": float(np.max(lat)) if lat.size else float("nan"),
        "mean_us": float(np.mean(lat)) if lat.size else float("nan"),
        "std_us": float(np.std(lat)) if lat.size else float("nan"),
    }
    if deadline_us is not None:
        out["deadline_us"] = float(deadline_us)
        out["deadline_misses"] = int(np.sum(lat > deadline_us))
        out["deadline_miss_rate"] = float(np.mean(lat > deadline_us)) if lat.size else 0.0
    return out
