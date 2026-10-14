"""Task 2 (2026-10-14): draft layer — provenance map, confirm, sidecar.

A draft is a normal v2 contract plus a top-level `provenance:` map keyed by
dotted field path. Statuses: inferred (name heuristic), documented (spec or
convention), confirmed (a human accepted a specific field), confirmed_blanket
(accepted via --confirm-all — strictly weaker). Provenance is never
discarded: confirm writes it to a sidecar file alongside the clean contract.
Ambiguous heuristics (pos, vel) omit the field instead of guessing.
"""
import json
import os

import pytest

from openflight.contract import draft as D
from openflight.contract import checker


SENSOR = "examples/quadrotor_adapter/drone_contract.yaml"


def _quat_draft():
    """Minimal draft model contract with full provenance."""
    return {
        "schema_version": 2,
        "model": {"name": "q", "input_size": 4, "dtype": "float32"},
        "raw_layout": [{"quantity": "orientation", "component": c}
                       for c in "wxyz"],  # must match sensor's wxyz (E403)
        "features": [{"name": "quat", "source": {"quantity": "orientation"},
                      "units": "dimensionless", "representation": "quaternion",
                      "ordering": "wxyz",
                      "normalization": {"method": "none"}, "width": 4}],
        "provenance": {
            "features[0].ordering": {"status": "inferred",
                                     "source": "obs key 'quat' default"},
            "features[0].units": {"status": "documented",
                                  "source": "REP-103 SI mandate"},
        },
    }


def test_every_nonconfirmed_field_carries_provenance():
    d = _quat_draft()
    missing = D.missing_provenance(d)
    # ordering + units are covered; every other non-obvious field is not
    assert "features[0].ordering" not in missing
    assert "features[0].units" not in missing
    # raw/structural fields need no provenance; feature identity does
    assert "features[0].name" in missing


def test_confirm_roundtrip_checker_accepts(tmp_path):
    d = _quat_draft()
    draft_path = str(tmp_path / "m.draft.yaml")
    out_path = str(tmp_path / "m.yaml")
    D.write_draft(d, draft_path)
    result = D.confirm(draft_path, out_path,
                       confirm=["features[0].ordering"])
    assert result["confirmed"] == ["features[0].ordering"]
    assert result["blanket"] == []
    # clean contract: no provenance key, checker-valid
    clean = D.load_contract_json(out_path)
    assert "provenance" not in clean
    # sidecar exists, retains full provenance, records confirm mode
    side = json.load(open(out_path + ".provenance.json"))
    assert side["provenance"]["features[0].ordering"]["status"] == "confirmed"
    assert side["provenance"]["features[0].units"]["status"] == "documented"
    assert side["confirm_mode"] == "per-field"
    # the emitted contract passes the real checker against the shipped sensor
    from openflight.adapters import contracts as C
    from openflight.contract import model_contract as MC
    import shutil as sh
    sp = str(tmp_path / "s.yaml")
    sh.copy(SENSOR, sp)
    s = C.load_contract(sp)
    m = MC.load_model_contract(out_path)
    assert checker.check(s, m)["status"] == "pass"


def test_confirm_all_records_blanket(tmp_path):
    d = _quat_draft()
    draft_path = str(tmp_path / "m.draft.yaml")
    out_path = str(tmp_path / "m.yaml")
    D.write_draft(d, draft_path)
    result = D.confirm(draft_path, out_path, confirm_all=True)
    assert "features[0].ordering" in result["blanket"]
    side = json.load(open(out_path + ".provenance.json"))
    assert side["provenance"]["features[0].ordering"]["status"] == \
        "confirmed_blanket"
    assert side["confirm_mode"] == "blanket"
    # documented fields stay documented — blanket only upgrades inferred
    assert side["provenance"]["features[0].units"]["status"] == "documented"


def test_confirm_all_prints_what_is_accepted(tmp_path, capsys):
    d = _quat_draft()
    draft_path = str(tmp_path / "m.draft.yaml")
    out_path = str(tmp_path / "m.yaml")
    D.write_draft(d, draft_path)
    D.confirm(draft_path, out_path, confirm_all=True)
    out = capsys.readouterr().out
    assert "features[0].ordering" in out
    assert "confirmed_blanket" in out or "blanket" in out.lower()


def test_confirm_refuses_unconfirmed_inferred_without_flag(tmp_path):
    d = _quat_draft()
    draft_path = str(tmp_path / "m.draft.yaml")
    out_path = str(tmp_path / "m.yaml")
    D.write_draft(d, draft_path)
    with pytest.raises(D.DraftError, match="inferred"):
        D.confirm(draft_path, out_path, confirm=[])  # nothing confirmed
    assert not os.path.exists(out_path)


def test_ambiguous_names_omit_field():
    """pos/vel-class keys must leave the field empty, never guess."""
    entry = {"name": "obs_pos", "dim": 3}
    out = D.propose_features([entry])
    for f in out["features"]:
        assert "quantity" not in f.get("source", {}) or \
            f["source"].get("quantity") is None
    # unambiguous keyword still proposes (marked inferred in provenance)
    entry2 = {"name": "IMU_gyro", "dim": 3}
    out2 = D.propose_features([entry2])
    assert out2["features"][0]["source"].get("quantity") == "angular_velocity"
    assert any("gyro" in v.get("source", "")
               for v in out2["provenance"].values())


def test_propose_marks_every_filled_field():
    out = D.propose_features([{"name": "IMU_gyro", "dim": 3}])
    prov = out["provenance"]
    assert prov["features[0].source.quantity"]["status"] == "inferred"
    assert "heuristic" in prov["features[0].source.quantity"]["source"] or \
        "keyword" in prov["features[0].source.quantity"]["source"]


def test_draft_write_is_roundtrippable_yaml_or_json(tmp_path):
    d = _quat_draft()
    p = str(tmp_path / "m.draft.json")
    D.write_draft(d, p)
    again = D.load_draft(p)
    assert again["provenance"] == d["provenance"]
    assert again["features"] == d["features"]
