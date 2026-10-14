"""ROS 2 importer: .msg text -> sensor-contract draft with provenance.

No ROS install needed: the parser works on .msg text only. Units come from
REP-103 (SI mandate, documented); frames from REP-105 (FLU body,
inferred — the .msg text cannot establish the runtime frame). PX4's FRD
body frame is a real, expected mismatch; the checker blocks it.
"""
from __future__ import annotations

from openflight.contract import draft as D

REP103 = "REP-103 SI mandate (CONVENTIONS.md#rep103)"
REP105 = ("REP-105 body frame (FLU) default (CONVENTIONS.md#rep105) — "
          "verify against your TF tree; the .msg text cannot establish "
          "the runtime frame")

# .msg field name -> (sensor path, extra documented spec)
_IMU_TABLE = {
    "orientation": ("state", "orientation",
                    {"representation": "quaternion",
                     "ordering": "xyzw"},
                    {"representation": "geometry_msgs/Quaternion field "
                                       "order x,y,z,w (CONVENTIONS.md#ros-quat)",
                     "ordering": "ROS memory layout x,y,z,w "
                                 "(geometry_msgs/Quaternion fields; "
                                 "CONVENTIONS.md#ros-quat)"}),
    "angular_velocity": ("state", "angular_velocity",
                         {"frame": "body",
                          "units": "radians_per_second"},
                         {"units": f"{REP103}: angular rates in rad/s",
                          "frame": REP105}),
    "linear_acceleration": ("imu", "accelerometer",
                            {"frame": "body",
                             "units": "metres_per_second_squared"},
                            {"units": f"{REP103}: accelerations in m/s^2",
                             "frame": REP105}),
}

_SKIP_TYPES = ("std_msgs/Header",)


def _parse_msg(text: str) -> list[tuple[str, str]]:
    """Return (type, name) field lines; constants and comments dropped."""
    fields = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or "=" in line:
            continue  # blank or constant
        parts = line.split()
        if len(parts) != 2:
            continue
        ftype, fname = parts
        if ftype in _SKIP_TYPES or ftype.startswith("std_msgs/"):
            continue
        fields.append((ftype, fname))
    return fields


def flatten_quantities(draft: dict) -> dict:
    """{quantity_name: spec_dict} across the v1 groups."""
    out: dict[str, dict] = {}

    def walk(node, name):
        if not isinstance(node, dict):
            return
        scalar_leaves = [k for k, v in node.items()
                         if not isinstance(v, dict)]
        dict_children = [k for k, v in node.items()
                         if isinstance(v, dict)]
        if scalar_leaves and node is not draft and name:
            out[name] = node
        for k in dict_children:
            if k == "provenance":
                continue
            walk(node[k], k)

    walk(draft, "")
    return out


def import_ros2(msg_path: str, msg_type: str,
                out_path: str | None = None) -> dict:
    try:
        with open(msg_path) as f:
            text = f.read()
    except OSError as e:
        raise D.DraftError(f"cannot read .msg file: {e}")
    fields = _parse_msg(text)
    groups: dict = {}
    prov: dict = {}

    def put(group: str, key: str, spec: dict, sources: dict) -> None:
        groups.setdefault(group, {})[key] = dict(spec)
        for field, src in sources.items():
            # frames are always inferred: .msg text cannot establish them;
            # everything else here is documented from cited conventions
            status = "inferred" if field == "frame" else "documented"
            prov[f"{group}.{key}.{field}"] = {"status": status,
                                              "source": src}

    warnings = []
    seen_unknown = set()
    for ftype, fname in fields:
        if msg_type == "sensor_msgs/Imu" and fname in _IMU_TABLE:
            group, key, spec, sources = _IMU_TABLE[fname]
            put(group, key, spec, sources)
        elif ftype in ("float32", "float64"):
            put("state", fname, {"frame": "body"},
                {"frame": REP105})
        elif ftype == "geometry_msgs/Vector3":
            put("state", fname, {"frame": "body"},
                {"frame": REP105})
        elif "[" in ftype:
            if ftype not in seen_unknown:
                seen_unknown.add(ftype)
                warnings.append({
                    "code": "W302",
                    "reason": f"skipping field {fname!r}: array type "
                              f"{ftype!r} has no contract quantity"})
        else:
            if ftype not in seen_unknown:
                seen_unknown.add(ftype)
                warnings.append({
                    "code": "W302",
                    "reason": f"skipping field {fname!r}: unknown type "
                              f"{ftype!r} not in the importer's table"})

    if not groups:
        raise D.DraftError(
            f"{msg_path}: no importable fields for {msg_type!r}")

    # v1 sensor schema requires the full state quartet; no .msg provides
    # position/velocity — emit empty placeholders so confirm's schema
    # check demands the human fill them from the real localization source
    state = groups.setdefault("state", {})
    for req in ("position", "velocity"):
        state.setdefault(req, {})

    draft = {"schema_version": 1, **groups, "provenance": prov}
    if out_path:
        D.write_draft(draft, out_path)
    return {"draft": draft, "warnings": warnings}
