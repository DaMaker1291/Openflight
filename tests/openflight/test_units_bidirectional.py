"""Bidirectional unit-conversion tests: constants, wired direction, roundtrip.

Each pair is tested in BOTH directions through the real pipeline
(build_ops gain), on values including zero, negatives, and wide magnitudes.
"""
import pytest

from openflight.contract import units as U
from openflight.contract import pipeline as PL

# (sensor_units, model_units, expected_gain): gain maps sensor -> model.
PAIRS = [
    ("radians_per_second", "degrees_per_second", 57.29577951308232),
    ("degrees_per_second", "radians_per_second", 0.017453292519943295),
    ("centimetres", "metres", 0.01),
    ("metres", "centimetres", 100.0),
    ("kilometres_per_hour", "metres_per_second", 1.0 / 3.6),
    ("metres_per_second", "kilometres_per_hour", 3.6),
    ("rpm", "radians_per_second", 0.10471975511965977),
    ("radians_per_second", "rpm", 9.549296585513721),
    ("millimetres", "kilometres", 1e-6),
    ("g", "metres_per_second_squared", 9.80665),
    ("milliseconds", "seconds", 1e-3),
]

VALUES = [0.0, 1.0, -1.0, 0.5, -0.5, 123.456, -123.456, 1e-6, -1e-6,
          1e6, -1e6]


def _contracts(su, mu):
    sensor = {"test_qty": {"units": su}}
    model = {
        "raw_layout": [{"quantity": "test_qty", "component": "x"}],
        "features": [{"name": "f", "source": {"quantity": "test_qty",
                                              "component": "x"},
                      "units": mu,
                      "normalization": {"method": "none"}}],
    }
    # checker resolves quantities via QUANTITY_PATHS; bypass it and test the
    # pipeline math directly with a stubbed field lookup.
    return sensor, model


@pytest.mark.parametrize("su,mu,factor", PAIRS)
def test_factor_both_directions(su, mu, factor):
    assert U.conversion(su, mu) == pytest.approx(factor, rel=1e-12)


@pytest.mark.parametrize("su,mu,factor", PAIRS)
def test_pipeline_gain_direction(su, mu, factor, monkeypatch):
    """build_ops must apply sensor->model (not the reverse)."""
    import openflight.contract.checker as Ch
    monkeypatch.setitem(Ch.QUANTITY_PATHS, "test_qty", ("test_qty",))
    sensor, model = _contracts(su, mu)
    sensor = {"test_qty": sensor["test_qty"]}
    ops = PL.build_ops(sensor, model)
    assert len(ops) == 1
    assert ops[0]["gain"] == pytest.approx(factor, rel=1e-12)
    for v in VALUES:
        assert ops[0]["gain"] * v + ops[0]["offset"] == pytest.approx(
            v * factor, rel=1e-9, abs=1e-12)


@pytest.mark.parametrize("su,mu,factor", PAIRS)
def test_roundtrip(su, mu, factor):
    back = U.conversion(mu, su)
    assert factor * back == pytest.approx(1.0, rel=1e-12)
    for v in VALUES:
        assert v * factor * back == pytest.approx(v, rel=1e-9, abs=1e-12)


def test_convert_then_normalize_order(monkeypatch):
    """y = x*A*S + O: conversion first, affine second — with nonzero offset."""
    import openflight.contract.checker as Ch
    monkeypatch.setitem(Ch.QUANTITY_PATHS, "test_qty", ("test_qty",))
    sensor = {"test_qty": {"units": "degrees_per_second"}}
    model = {
        "raw_layout": [{"quantity": "test_qty", "component": "x"}],
        "features": [{"name": "f", "source": {"quantity": "test_qty",
                                              "component": "x"},
                      "units": "radians_per_second",
                      "normalization": {"method": "affine", "scale": 2.0,
                                        "offset": 0.5}}],
    }
    ops = PL.build_ops(sensor, model)
    a = 0.017453292519943295
    assert ops[0]["gain"] == pytest.approx(2.0 * a, rel=1e-12)
    assert ops[0]["offset"] == pytest.approx(0.5)
    for v in [0.0, 90.0, -180.0, 3600.0]:
        assert ops[0]["gain"] * v + ops[0]["offset"] == pytest.approx(
            v * a * 2.0 + 0.5, rel=1e-12)
