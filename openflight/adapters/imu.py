"""IMU measurement models (explicit bias/noise params, no hidden realism)."""
from __future__ import annotations

import numpy as np

from openflight.adapters.coordinates import world_to_body


def accel_measurement(a_w: np.ndarray, g_w: np.ndarray, q: np.ndarray,
                      ordering: str = "wxyz", bias: np.ndarray | None = None,
                      noise: np.ndarray | None = None) -> np.ndarray:
    """a_m = R^T (a_w - g_w) + b_a + eps_a. All args explicit SI."""
    a_w = np.asarray(a_w, dtype=float)
    g_w = np.asarray(g_w, dtype=float)
    m = world_to_body(a_w - g_w, q, ordering)
    if bias is not None:
        m = m + np.asarray(bias, dtype=float)
    if noise is not None:
        m = m + np.asarray(noise, dtype=float)
    return m


def gyro_measurement(omega: np.ndarray, bias: np.ndarray | None = None,
                     noise: np.ndarray | None = None) -> np.ndarray:
    o = np.asarray(omega, dtype=float).copy()
    if bias is not None:
        o = o + np.asarray(bias, dtype=float)
    if noise is not None:
        o = o + np.asarray(noise, dtype=float)
    return o
