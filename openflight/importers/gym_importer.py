"""SB3 / Isaac Lab importer: obs-space JSON + optional VecNormalize stats
-> model-contract draft with provenance. Fully offline."""
from __future__ import annotations

import hashlib
import json
import math

from openflight.contract import draft as D


def _load_json(path: str):
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise D.DraftError(f"{path}: cannot read obs space: {e}")
    # accept {"observation_space": [...]} wrappers too
    if isinstance(data, dict) and "observation_space" in data:
        data = data["observation_space"]
    if not isinstance(data, list):
        raise D.DraftError(
            f"{path}: obs space must be a JSON list of "
            "{name, dim, index?} entries")
    return data


def _stats_index_map(entries: list[dict]) -> list[int]:
    """Per-output-feature source index in the obs vector (stat arrays are
    indexed by raw obs position, not by split-feature position)."""
    idx: list[int] = []
    cursor = 0
    for e in entries:
        dim = int(e.get("dim", 1))
        base = e.get("index")
        for j in range(dim):
            idx.append(int(base[j]) if base else cursor + j)
        cursor += dim
    return idx


def import_gym(obs_path: str, stats_path: str | None = None,
               net_arch: str | None = None, out_path: str | None = None
               ) -> dict:
    entries = _load_json(obs_path)
    draft = D.propose_features(entries)
    warnings = []

    # duplicate (quantity, component) slots would silently collapse in the
    # checker's raw_index (e.g. a quat AND projected_gravity both labelling
    # orientation x) — diagnose, never let the binding go ambiguous
    seen_slots: set[tuple] = set()
    for r in draft["raw_layout"]:
        key = (r.get("quantity"), r.get("component"))
        if r.get("quantity") is not None and key in seen_slots:
            warnings.append({
                "code": "W303",
                "reason": f"raw slot {key!r} appears more than once; "
                          "duplicate (quantity, component) labels collapse "
                          "in the checker's raw_index — relabel or drop one "
                          "before confirming"})
        seen_slots.add(key)

    if stats_path is not None:
        try:
            with open(stats_path) as f:
                stats = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            raise D.DraftError(f"cannot read VecNormalize stats: {e}")
        for key in ("mean", "var"):
            if key not in stats:
                raise D.DraftError(
                    f"{stats_path}: VecNormalize stats missing {key!r}")
        mean = list(stats["mean"])
        var = list(stats["var"])
        eps = float(stats.get("epsilon", 1e-5))
        clip = stats.get("clip_obs", stats.get("clip", [0.0, 0.0]))
        try:
            clip_max = max(abs(float(c)) for c in (clip or [0.0]))
        except (TypeError, ValueError):
            clip_max = 0.0
        if clip_max > 0.0:
            warnings.append({
                "code": "W301",
                "reason": f"VecNormalize clip_obs={clip} does not fit an "
                          "affine map; the generated pipeline will not "
                          "clip — handle clipping in firmware or accept "
                          "the mismatch"})
        shash = hashlib.sha256(
            open(stats_path, "rb").read()).hexdigest()[:8]
        src_idx = _stats_index_map(entries)
        feats = draft["features"]
        if len(src_idx) != len(feats):
            raise D.DraftError(
                "internal: feature/index map mismatch "
                f"({len(feats)} features vs {len(src_idx)} indices)")
        for i, f in enumerate(feats):
            j = src_idx[i]
            if j >= len(mean) or j >= len(var):
                raise D.DraftError(
                    f"{stats_path}: stats arrays shorter than obs "
                    f"index {j}")
            scale = 1.0 / math.sqrt(var[j] + eps)
            offset = -mean[j] * scale
            f["normalization"] = {"method": "affine",
                                  "scale": scale, "offset": offset}
            draft["provenance"][f"features[{i}].normalization"] = {
                "status": "documented",
                "source": f"VecNormalize statistics {stats_path} "
                          f"(sha256:{shash}) obs[{j}]: "
                          "scale=1/sqrt(var+eps), offset=-mean*scale"}

    if net_arch is not None:
        draft["provenance"]["model.input_size"] = {
            "status": "documented",
            "source": f"obs-space width (--net-arch {net_arch} recorded "
                      "for the later E203 check)"}

    if out_path:
        D.write_draft(draft, out_path)
    return {"draft": draft, "warnings": warnings}
