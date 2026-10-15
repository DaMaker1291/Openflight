"""Task 3 (2026-10-14): importers — SB3/gym + ROS 2 drafts with provenance.

Self-authored unit/golden layer plus external golden cases transcribed from
public sources (citations in fixture headers). No gym/SB3/ROS installs:
everything works on offline artifacts (obs-space JSON, VecNormalize stats,
.msg text).
"""
import json
import math

import pytest

from openflight.contract import draft as D
from openflight.contract import checker, model_contract as MC
from openflight.adapters import contracts as C
from openflight.importers import gym_importer as G, ros2_importer as R

# ---------------------------------------------------------- self-authored

OBS_SPACE = [
    {"name": "IMU_gyro", "dim": 3, "index": [0, 1, 2]},
    {"name": "IMU_quat", "dim": 4, "index": [3, 4, 5, 6]},
    {"name": "obs_pos", "dim": 3, "index": [7, 8, 9]},   # ambiguous
]

VEC_STATS = {
    "mean": [0.1, -0.2, 0.3, 0.0, 0.0, 0.0, 1.0],
    "var": [0.25, 0.25, 0.25, 1.0, 1.0, 1.0, 0.04],
    "epsilon": 1e-5,
    "clip_obs": [0.0, 0.0],
}


def test_gym_import_every_field_has_provenance(tmp_path):
    obs_path = tmp_path / "obs.json"
    obs_path.write_text(json.dumps(OBS_SPACE))
    out = G.import_gym(str(obs_path), out_path=str(tmp_path / "m.draft.yaml"))
    d = out["draft"]
    assert D.missing_provenance(d) == []
    # ambiguous name omitted, never guessed
    pos_feats = [f for f in d["features"] if f["name"].startswith("obs_pos")]
    assert pos_feats
    for f in pos_feats:
        assert f["source"] == {} or "quantity" not in f["source"]
    assert not any("obs_pos" in k and "quantity" in k
                   for k in d["provenance"])
    # every filled quantity is inferred with the heuristic named
    assert all(m["status"] == "inferred"
               for m in d["provenance"].values())


def test_gym_vecnormalize_affine_math(tmp_path):
    obs_path = tmp_path / "obs.json"
    stats_path = tmp_path / "stats.json"
    obs_path.write_text(json.dumps(OBS_SPACE[:1]))  # gyro only, 3 scalars
    stats_path.write_text(json.dumps(VEC_STATS))
    out = G.import_gym(str(obs_path), stats_path=str(stats_path))
    feats = out["draft"]["features"]
    assert len(feats) == 3
    for i, f in enumerate(feats):
        exp_scale = 1.0 / math.sqrt(VEC_STATS["var"][i] + VEC_STATS["epsilon"])
        exp_offset = -VEC_STATS["mean"][i] * exp_scale
        assert f["normalization"]["method"] == "affine"
        assert f["normalization"]["scale"] == pytest.approx(exp_scale)
        assert f["normalization"]["offset"] == pytest.approx(exp_offset)
        p = out["draft"]["provenance"][f"features[{i}].normalization"]
        assert p["status"] == "documented"
        assert "stats.json" in p["source"]


def test_gym_vecnormalize_nonzero_clip_w301(tmp_path):
    obs_path = tmp_path / "obs.json"
    stats_path = tmp_path / "stats.json"
    obs_path.write_text(json.dumps(OBS_SPACE[:1]))
    s = dict(VEC_STATS, clip_obs=[-5.0, 5.0])
    stats_path.write_text(json.dumps(s))
    out = G.import_gym(str(obs_path), stats_path=str(stats_path))
    assert any(w["code"] == "W301" for w in out["warnings"])
    w301 = next(w for w in out["warnings"] if w["code"] == "W301")
    assert "clip" in w301["reason"].lower()


def test_gym_zero_clip_no_w301(tmp_path):
    obs_path = tmp_path / "obs.json"
    stats_path = tmp_path / "stats.json"
    obs_path.write_text(json.dumps(OBS_SPACE[:1]))
    stats_path.write_text(json.dumps(VEC_STATS))  # clip all zeros
    out = G.import_gym(str(obs_path), stats_path=str(stats_path))
    assert not any(w["code"] == "W301" for w in out["warnings"])


IMU_MSG = """\
# This is a comment
std_msgs/Header header
geometry_msgs/Quaternion orientation
float64[4] orientation_covariance
geometry_msgs/Vector3 angular_velocity
float64[9] angular_velocity_covariance
geometry_msgs/Vector3 linear_acceleration
float64[9] linear_acceleration_covariance
"""


def test_ros2_imu_msg_draft(tmp_path):
    msg_path = tmp_path / "Imu.msg"
    msg_path.write_text(IMU_MSG)
    out = R.import_ros2(str(msg_path), "sensor_msgs/Imu")
    d = out["draft"]
    assert D.missing_provenance(d) == []
    flat = R.flatten_quantities(d)
    # orientation: width-4 quaternion, documented ROS ordering xyzw
    assert flat["orientation"]["representation"] == "quaternion"
    assert flat["orientation"]["ordering"] == "xyzw"  # ROS memory layout
    assert flat["angular_velocity"]["units"] == "radians_per_second"
    # linear_acceleration lands under the checker's imu.accelerometer path
    assert flat["accelerometer"]["units"] == \
        "metres_per_second_squared"
    p = d["provenance"]
    # orientation fields documented (field order / memory layout)
    for field in ("representation", "ordering"):
        k = f"state.orientation.{field}"
        assert p[k]["status"] == "documented"
        assert "CONVENTIONS.md" in p[k]["source"]
    # vector quantities: units documented (REP-103), frame inferred
    # (REP-105, with verify note). linear_acceleration lands in the
    # checker's imu.accelerometer path (QUANTITY_PATHS).
    for path in ("state.angular_velocity", "imu.accelerometer"):
        unit_key = f"{path}.units"
        assert p[unit_key]["status"] == "documented"
        assert "REP-103" in p[unit_key]["source"]
    frame_keys = [k for k in p if k.endswith(".frame")]
    assert len(frame_keys) == 2  # angular_velocity + accelerometer
    assert all(p[k]["status"] == "inferred" for k in frame_keys)
    assert all("REP-105" in p[k]["source"] for k in frame_keys)
    assert any("TF tree" in p[k]["source"] for k in frame_keys)


def test_ros2_unknown_type_skipped_not_crashed(tmp_path):
    msg_path = tmp_path / "Weird.msg"
    msg_path.write_text("foo_msgs/CustomThing thing\nfloat64 value\n")
    out = R.import_ros2(str(msg_path), "weird_msgs/Weird")
    assert any("skip" in w["reason"].lower() for w in out["warnings"])
    flat = R.flatten_quantities(out["draft"])
    assert "value" in flat or any("value" in str(flat))
    assert not any("thing" in str(k) for k in flat)


# ---------------------------------------------------------- external golden

# Transcribed VERBATIM from leggedrobotics/legged_gym master@8fa29acc6fd191
# 0c3d9659eef6310bdd301cde0a:
#   envs/base/legged_robot.py compute_observations() (lines 212-219):
#     cat(base_lin_vel*2.0, base_ang_vel*0.25, projected_gravity,
#         commands[:, :3]*commands_scale, (dof_pos-default)*1.0,
#         dof_vel*0.05, actions)
#   envs/base/legged_robot_config.py: obs_scales.lin_vel=2.0, ang_vel=0.25,
#     dof_pos=1.0, dof_vel=0.05; clip_observations=100. (nonzero!);
#     num_actions=12; num_observations=235 (= 48 blind + 187 heights).
# Verified verbatim against the upstream raw files at that commit on
# 2026-10-15 (order, scales, 48-dim layout match; heights = 17x11 grid).
# The 48-dim blind configuration (measure_heights=False) is transcribed
# here; height samples are terrain perception, not sensor-contract material.
LEGGED_GYM_OBS = [
    {"name": "base_lin_vel", "dim": 3},    # * obs_scales.lin_vel = 2.0
    {"name": "base_ang_vel", "dim": 3},    # * obs_scales.ang_vel = 0.25
    {"name": "projected_gravity", "dim": 3},
    {"name": "commands", "dim": 3},        # lin_vel_x, lin_vel_y, ang_vel_yaw
    {"name": "dof_pos", "dim": 12},
    {"name": "dof_vel", "dim": 12},        # * obs_scales.dof_vel = 0.05
    {"name": "actions", "dim": 12},
]


def test_external_golden_legged_gym_obs_passes(tmp_path):
    """FALSE-REJECT WATCH: the real legged_gym 48-dim blind obs definition
    (transcribed from master@8fa29ac, see fixture header) imports,
    confirms, and passes the checker against a matching sensor draft."""
    obs_path = tmp_path / "obs.json"
    obs_path.write_text(json.dumps(LEGGED_GYM_OBS))
    out = G.import_gym(str(obs_path), out_path=str(tmp_path / "m.draft.yaml"))
    d = out["draft"]
    # width accounting stays honest: 48 input slots
    assert d["model"]["input_size"] == 48
    # base_lin_vel + base_ang_vel + projected_gravity are proposed
    assert [f["source"].get("quantity") for f in d["features"]
            if f["name"].startswith("base_lin_vel")] == ["velocity"] * 3
    gyro = [f for f in d["features"] if f["name"].startswith("base_ang_vel")]
    assert len(gyro) == 3
    assert all(f["source"].get("quantity") == "angular_velocity"
               for f in gyro)
    pg = [f for f in d["features"]
          if f["name"].startswith("projected_gravity")]
    assert len(pg) == 3
    assert all(f["source"].get("quantity") == "orientation" for f in pg)
    # ambiguous groups (commands, dof_pos, dof_vel, actions) omitted
    ambiguous = {f["name"] for f in d["features"]
                 if "quantity" not in f.get("source", {})}
    assert ambiguous
    # user edit step drops them (policy inputs / joint state, not sensor
    # facts the contract tracks)
    draft_path = str(tmp_path / "m.draft.yaml")
    d["features"] = [f for f in d["features"] if f["name"] not in ambiguous]
    d["raw_layout"] = [r for r in d["raw_layout"]
                       if r.get("quantity") is not None]
    d["model"]["input_size"] = sum(
        int(f.get("width", 1)) for f in d["features"])
    assert d["model"]["input_size"] == 9  # 3+3+3 remaining
    d["provenance"] = {k: v for k, v in d["provenance"].items()
                       if not any(a in k for a in ambiguous)}
    D.write_draft(d, draft_path)
    out_path = str(tmp_path / "m.yaml")
    D.confirm(draft_path, out_path, confirm_all=True)
    m = MC.load_model_contract(out_path)
    # matching sensor: full state quartet (v1 schema), orientation units
    # declared dimensionless for projected gravity. Gyro features need
    # frame: body; the user's edit step records that as confirmed.
    sensor = {"schema_version": 1,
              "state": {"position": {"frame": "world", "units": "metres"},
                        "velocity": {"frame": "world",
                                     "units": "metres_per_second"},
                        "orientation": {"representation": "quaternion",
                                        "ordering": "xyzw",
                                        "units": "dimensionless"},
                        "angular_velocity": {"frame": "body",
                                             "units": "radians_per_second"}}}
    s = C.validate_contract(sensor)
    for i, f in enumerate(m["features"]):
        if f["source"]["quantity"] == "angular_velocity":
            f["frame"] = "body"
            f["units"] = "radians_per_second"  # user confirms REP-103
        if f["source"]["quantity"] == "velocity":
            f["frame"] = "world"
            f["units"] = "metres_per_second"   # base_lin_vel is world-frame
    rep = checker.check(s, m)
    assert rep["status"] == "pass", rep["errors"]


def test_external_golden_legged_gym_scales_and_clip_recorded(tmp_path):
    """The transcribed obs_scales (ang_vel=0.25 etc.) are training-time
    multipliers the importer does NOT apply; clip_observations=100. is
    nonzero, so a real VecNormalize stats file from this lineage will
    carry clip -> the W301 limitation must be recorded, not just printed."""
    obs_path = tmp_path / "obs.json"
    stats_path = tmp_path / "stats.json"
    obs_path.write_text(json.dumps(LEGGED_GYM_OBS[:2]))
    # stats arrays sized for the 6 imported slots
    stats_path.write_text(json.dumps({
        "mean": [0.0] * 6, "var": [1.0] * 6, "epsilon": 1e-5,
        "clip_obs": [-100.0, 100.0]}))  # matches clip_observations=100.
    out = G.import_gym(str(obs_path), stats_path=str(stats_path))
    assert any(w["code"] == "W301" for w in out["warnings"])
    draft = out["draft"]
    assert draft.get("limitations"), "W301 must be retained as a limitation"
    assert any("W301" in lim.get("code", "") for lim in draft["limitations"])
    # the affine provenance also states the distribution is unverified
    norm_prov = [v for k, v in draft["provenance"].items()
                 if "normalization" in k]
    assert norm_prov
    assert any("NOT verified" in p["source"] or
               "not verified" in p["source"].lower()
               for p in norm_prov)


def test_external_golden_px4_frd_vs_ros_flu_blocks(tmp_path):
    """TRUE-POSITIVITY WATCH: PX4's FRD body frame vs ROS REP-105 FLU body
    frame must block (they are not interchangeable — the same 'body' name
    hides mirrored axes). PX4 docs: frame "base_link" = FRD. ROS REP-105:
    body FLU."""
    msg_path = tmp_path / "Imu.msg"
    msg_path.write_text(IMU_MSG)
    sensor_out = R.import_ros2(str(msg_path), "sensor_msgs/Imu")
    # model feature declares PX4's FRD body frame (different name)
    m = {
        "schema_version": 2,
        "model": {"name": "px4_policy", "input_size": 3, "dtype": "float32"},
        "raw_layout": [{"quantity": "angular_velocity", "component": c}
                       for c in "xyz"],
        "features": [
            {"name": f"gyro_{c}",
             "source": {"quantity": "angular_velocity", "component": c},
             "units": "radians_per_second", "frame": "px4_frd_body",
             "normalization": {"method": "none"}}
            for c in "xyz"],
    }
    m = MC.validate_model_contract(m)
    s = sensor_out["draft"]
    rep = checker.check(s, m)
    assert rep["status"] == "blocked"
    assert any(e["code"] in ("E301", "U302") for e in rep["errors"])


def test_gym_importer_never_emits_frame_values():
    """The gym importer cannot launder frames: its drafts contain no
    'frame' keys anywhere, so an FRD/FLU mismatch can never be papered
    over by an importer default."""
    import os
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        f.write(json.dumps([{"name": "IMU_gyro", "dim": 3}]))
        p = f.name
    try:
        out = G.import_gym(p)
        assert '"frame"' not in json.dumps(out["draft"])
    finally:
        os.unlink(p)


def test_wrongly_confirmed_frame_still_passes_but_doubt_is_retained(tmp_path):
    """Item-2 strengthening: a wrongly-confirmed frame (both sides blanket-
    confirm the name 'body' while the true stacks differ FRD vs FLU) makes
    the checker PASS — declarations are all it checks — but the sidecars
    must retain the doubt: the ROS frame provenance keeps its REP-105
    verify-TF origin, and blanket fields are listed as not individually
    verified. The pass is recorded as human-accepted convention, never as
    importer-verified fact."""
    msg_path = tmp_path / "Imu.msg"
    msg_path.write_text(IMU_MSG)
    s_draft = R.import_ros2(str(msg_path), "sensor_msgs/Imu")["draft"]
    # user fills the quartet members no .msg can provide
    s_draft["state"]["position"] = {"frame": "world", "units": "metres"}
    s_draft["state"]["velocity"] = {"frame": "world",
                                    "units": "metres_per_second"}
    s_path, s_out = str(tmp_path / "s.draft.yaml"), str(tmp_path / "s.yaml")
    D.write_draft(s_draft, s_path)
    D.confirm(s_path, s_out, confirm_all=True, kind="sensor")
    s_side = json.load(open(s_out + ".provenance.json"))
    frame_prov = s_side["provenance"]["state.angular_velocity.frame"]
    assert frame_prov["status"] == "confirmed_blanket"
    assert "REP-105" in frame_prov["source"]  # origin never rewritten
    assert "TF tree" in frame_prov["source"]
    assert ("state.angular_velocity.frame"
            in s_side["not_individually_verified"])
    # model side: declares the same name 'body' (as a PX4 user might)
    m = {
        "schema_version": 2,
        "model": {"name": "px4_policy", "input_size": 3, "dtype": "float32"},
        "raw_layout": [{"quantity": "angular_velocity", "component": c}
                       for c in "xyz"],
        "features": [
            {"name": f"gyro_{c}",
             "source": {"quantity": "angular_velocity", "component": c},
             "units": "radians_per_second", "frame": "body",
             "normalization": {"method": "none"}}
            for c in "xyz"],
    }
    m = MC.validate_model_contract(m)
    from openflight.adapters import contracts as Cmod
    s = Cmod.load_contract(s_out)
    rep = checker.check(s, m)
    # same name -> checker passes; that is declaration-consistency only
    assert rep["status"] == "pass", rep["errors"]


def test_ros_sensor_ordering_e403_not_bypassed(tmp_path):
    """Item 6: the importer's documented xyzw sensor ordering feeds the
    full consistency machinery — (a) raw_layout xyzw + declared xyzw
    passes; (b) raw_layout labelled w-first against sensor xyzw blocks
    E403 (labels cannot both be right); (c) a quat feature with no
    declared ordering is refused at schema load. Model-vs-sensor
    ordering difference with CONSISTENT raw_layout is a recorded reorder
    conversion, not a silent pass."""
    msg_path = tmp_path / "Imu.msg"
    msg_path.write_text(IMU_MSG)
    s_draft = R.import_ros2(str(msg_path), "sensor_msgs/Imu")["draft"]
    assert s_draft["state"]["orientation"]["ordering"] == "xyzw"
    s_draft["state"]["position"] = {"frame": "world", "units": "metres"}
    s_draft["state"]["velocity"] = {"frame": "world",
                                    "units": "metres_per_second"}
    s = C.validate_contract(s_draft)

    def _model(layout_order, ordering):
        feat = {"name": "quat",
                "source": {"quantity": "orientation"},
                "units": "dimensionless",
                "representation": "quaternion",
                "normalization": {"method": "none"}, "width": 4}
        if ordering is not None:
            feat["ordering"] = ordering
        m = {
            "schema_version": 2,
            "model": {"name": "q", "input_size": 4, "dtype": "float32"},
            "raw_layout": [{"quantity": "orientation", "component": c}
                           for c in layout_order],
            "features": [feat],
        }
        return MC.validate_model_contract(m)

    # (a) consistent xyzw layout + declared xyzw -> pass
    rep = checker.check(s, _model("xyzw", "xyzw"))
    assert rep["status"] == "pass", rep["errors"]
    # (b) w-first raw_layout against xyzw sensor -> E403
    rep = checker.check(s, _model("wxyz", "wxyz"))
    assert rep["status"] == "blocked"
    assert any(e["code"] == "E403" for e in rep["errors"])
    # (c) quat feature with no ordering -> the schema refuses to load it
    # (checker-side E204 covers hand-built contracts that bypass
    # validate_model_contract)
    with pytest.raises(ValueError, match="ordering"):
        _model("xyzw", None)


def test_confirm_sidecar_lists_blanket_as_not_verified(tmp_path):
    """Item 4: confirmed_blanket fields appear in the sidecar under
    not_individually_verified, and the CLI prints them."""
    obs_path = tmp_path / "obs.json"
    draft_path = tmp_path / "m.draft.yaml"
    out_path = tmp_path / "m.yaml"
    obs_path.write_text(json.dumps([{"name": "IMU_gyro", "dim": 3}]))
    G.import_gym(str(obs_path), out_path=str(draft_path))
    from openflight import cli
    rc = cli.main(["contract", "confirm", str(draft_path),
                   "--out", str(out_path), "--confirm-all"])
    assert rc == 0
    side = json.load(open(str(out_path) + ".provenance.json"))
    blanket = side["not_individually_verified"]
    assert blanket == sorted(side["blanket"]) or set(blanket) == \
        set(side["blanket"])
    assert any("features[0].source.quantity" in b for b in blanket)


def test_unknown_dim_entry_emits_per_slot_scalars():
    """A dim-12 entry must not collapse into one width-1 feature (that
    would silently corrupt input_size accounting)."""
    d = D.propose_features([{"name": "actions", "dim": 12}])
    assert d["model"]["input_size"] == 12
    assert len(d["features"]) == 12
    assert all("quantity" not in f.get("source", {})
               for f in d["features"])


# ---------------------------------------------------------- CLI wiring

def test_cli_import_and_confirm(tmp_path, capsys):
    from openflight import cli
    obs_path = tmp_path / "obs.json"
    draft_path = tmp_path / "m.draft.yaml"
    obs_path.write_text(json.dumps(OBS_SPACE[:1]))  # gyro only; a quat
    # draft rightly refuses --confirm-all without an ordering value (the
    # schema demands the human decide — covered in test_draft_layer)
    rc = cli.main(["import", "gym", "--obs", str(obs_path),
                   "--out", str(draft_path)])
    assert rc == 0 and draft_path.exists()
    out_path = tmp_path / "m.yaml"
    rc = cli.main(["contract", "confirm", str(draft_path),
                   "--out", str(out_path), "--confirm-all"])
    assert rc == 0 and out_path.exists()
    assert (tmp_path / "m.yaml.provenance.json").exists()
    clean = json.loads(out_path.read_text()) if out_path.suffix == ".json" \
        else D.load_contract_json(str(out_path))
    assert "provenance" not in clean


def test_cli_ros2_import(tmp_path):
    from openflight import cli
    msg_path = tmp_path / "Imu.msg"
    msg_path.write_text(IMU_MSG)
    out_path = tmp_path / "s.draft.yaml"
    rc = cli.main(["import", "ros2", "--msg", str(msg_path),
                   "--type", "sensor_msgs/Imu", "--out", str(out_path)])
    assert rc == 0 and out_path.exists()


def test_cli_malformed_input_diagnosed_not_traceback(tmp_path, capsys):
    from openflight import cli
    rc = cli.main(["import", "gym", "--obs", str(tmp_path / "nope.json"),
                   "--out", str(tmp_path / "x.yaml")])
    assert rc != 0
    err = capsys.readouterr().err
    assert "nope.json" in err
    assert "Traceback" not in err
