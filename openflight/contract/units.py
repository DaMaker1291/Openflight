"""Unit registry: dimension-checked linear conversions y = a*x.

Only unambiguous multiplicative conversions are registered. Anything else
(including unknown unit strings) is NOT guessed — callers must block.
"""
from __future__ import annotations

import math

# unit -> (dimension, scale to SI base unit)
REGISTRY: dict[str, tuple[str, float]] = {
    # angle (base: radian)
    "radians": ("angle", 1.0),
    "degrees": ("angle", math.pi / 180.0),
    # angular velocity (base: rad/s)
    "radians_per_second": ("angular_velocity", 1.0),
    "degrees_per_second": ("angular_velocity", math.pi / 180.0),
    "rpm": ("angular_velocity", 2.0 * math.pi / 60.0),
    # length (base: metre)
    "metres": ("length", 1.0),
    "centimetres": ("length", 0.01),
    "millimetres": ("length", 0.001),
    "kilometres": ("length", 1000.0),
    # velocity (base: m/s)
    "metres_per_second": ("velocity", 1.0),
    "kilometres_per_hour": ("velocity", 1000.0 / 3600.0),
    "centimetres_per_second": ("velocity", 0.01),
    # acceleration (base: m/s^2)
    "metres_per_second_squared": ("acceleration", 1.0),
    "centimetres_per_second_squared": ("acceleration", 0.01),
    "g": ("acceleration", 9.80665),
    # time (base: second)
    "seconds": ("time", 1.0),
    "milliseconds": ("time", 1e-3),
    "microseconds": ("time", 1e-6),
    # dimensionless
    "dimensionless": ("dimensionless", 1.0),
}


# quantity -> allowed dimensions of that quantity's physical units (a set:
# some quantities legitimately appear dimensionless, e.g. orientation as
# projected gravity / direction cosines). The checker enforces this: a unit
# whose registered dimension is outside the allowed set is implausible even
# when the sensor and model declarations agree with each other (both sides
# can be wrong together).
QUANTITY_DIMENSION: dict[str, set[str]] = {
    "position": {"length"},
    "velocity": {"velocity"},
    "orientation": {"angle", "dimensionless"},
    "angular_velocity": {"angular_velocity"},
    "gyro": {"angular_velocity"},
    "gyroscope": {"angular_velocity"},
    "acceleration": {"acceleration"},
    "accelerometer": {"acceleration"},
}


def dimension(unit: str) -> str | None:
    """Registered dimension of a unit, or None if the unit is unknown."""
    entry = REGISTRY.get(unit)
    return entry[0] if entry else None


def plausible_for_quantity(unit: str, quantity: str) -> bool | None:
    """True/False when decidable; None when unit unknown or quantity unmapped.

    None means "cannot judge" — the caller must fall back to its normal
    unit-compatibility checks, never to a silent pass on the plausibility
    dimension (that gap is covered by U101 for unknown units).
    """
    expected = QUANTITY_DIMENSION.get(quantity)
    d = dimension(unit)
    if expected is None or d is None:
        return None
    return d in expected


def conversion(src: str, dst: str) -> float:
    """Multiplicative factor a such that x_dst = a * x_src.

    Raises KeyError on unknown units, ValueError on dimension mismatch.
    Both are caller-block conditions, never silent repairs.
    """
    if src not in REGISTRY:
        raise KeyError(f"unknown unit: {src!r}")
    if dst not in REGISTRY:
        raise KeyError(f"unknown unit: {dst!r}")
    d1, s1 = REGISTRY[src]
    d2, s2 = REGISTRY[dst]
    if d1 != d2:
        raise ValueError(
            f"incompatible dimensions: {src!r} is {d1}, {dst!r} is {d2}")
    return s1 / s2


def is_convertible(src: str, dst: str) -> bool:
    try:
        conversion(src, dst)
        return True
    except (KeyError, ValueError):
        return False
