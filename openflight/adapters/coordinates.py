"""Coordinate-frame + quaternion utilities (numpy, no hidden conventions)."""
from __future__ import annotations

import numpy as np


def quat_to_rot(q: np.ndarray, ordering: str = "wxyz") -> np.ndarray:
    q = np.asarray(q, dtype=float)
    if ordering == "xyzw":
        x, y, z, w = q
    elif ordering == "wxyz":
        w, x, y, z = q
    else:
        raise ValueError(f"unknown ordering {ordering}")
    n = np.sqrt(w * w + x * x + y * y + z * z)
    if n < 1e-12:
        raise ValueError("zero quaternion")
    w, x, y, z = w / n, x / n, y / n, z / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def convert_quat(q: np.ndarray, src: str, dst: str) -> np.ndarray:
    q = np.asarray(q, dtype=float)
    if src == dst:
        return q.copy()
    if src == "xyzw" and dst == "wxyz":
        return np.array([q[3], q[0], q[1], q[2]])
    if src == "wxyz" and dst == "xyzw":
        return np.array([q[1], q[2], q[3], q[0]])
    raise ValueError(f"quat conversion {src}->{dst} unsupported")


def world_to_body(v_w: np.ndarray, q: np.ndarray, ordering: str = "wxyz") -> np.ndarray:
    R = quat_to_rot(q, ordering)
    return R.T @ np.asarray(v_w, dtype=float)


def body_to_world(v_b: np.ndarray, q: np.ndarray, ordering: str = "wxyz") -> np.ndarray:
    R = quat_to_rot(q, ordering)
    return R @ np.asarray(v_b, dtype=float)
