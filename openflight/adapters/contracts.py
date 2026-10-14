"""State/IMU contract loading + validation (YAML subset or JSON)."""
from __future__ import annotations

import json


def _parse_simple_yaml(text: str) -> dict:
    """Minimal YAML subset parser for contracts (mappings + scalars)."""
    root: dict = {}
    stack: list[tuple[int, dict]] = [(-1, root)]
    for raw in text.splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        line = raw.strip()
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if val == "":
            child: dict = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _scalar(val)
    return root


def _scalar(v: str):
    if v in ("true", "True"):
        return True
    if v in ("false", "False"):
        return False
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v.strip("'\"")


def load_contract(path: str) -> dict:
    with open(path) as f:
        text = f.read()
    try:
        c = json.loads(text)
    except Exception:
        try:
            import yaml  # type: ignore
            c = yaml.safe_load(text)
        except Exception:
            c = _parse_simple_yaml(text)
    return validate_contract(c)


REQUIRED_STATE = ("position", "velocity", "orientation", "angular_velocity")


def validate_contract(c: dict) -> dict:
    if not isinstance(c, dict) or c.get("schema_version") != 1:
        raise ValueError("contract needs schema_version: 1")
    st = c.get("state", {})
    for k in REQUIRED_STATE:
        if k not in st:
            raise ValueError(f"contract.state missing '{k}' (never infer silently)")
    ori = st["orientation"]
    if ori.get("representation") != "quaternion" or ori.get("ordering") not in ("wxyz", "xyzw"):
        raise ValueError("orientation must declare representation: quaternion, ordering: wxyz|xyzw")
    for section in ("position", "velocity"):
        if "frame" not in st[section] or "units" not in st[section]:
            raise ValueError(f"state.{section} needs frame + units")
    if "frame" not in st["angular_velocity"] or "units" not in st["angular_velocity"]:
        raise ValueError("state.angular_velocity needs frame + units")
    imu = c.get("imu", {})
    for s in ("accelerometer", "gyroscope"):
        if s in imu and "units" not in imu[s]:
            raise ValueError(f"imu.{s} needs units")
    return c


def check_compat(sim: dict, model_expects: dict) -> list[str]:
    """Compare simulator output convention vs model expectation. Returns mismatches."""
    issues = []
    for key in ("ordering", "frame", "units"):
        a = sim.get(key)
        b = model_expects.get(key)
        if a is not None and b is not None and a != b:
            issues.append(f"{key}: sim={a} model={b}")
    return issues
