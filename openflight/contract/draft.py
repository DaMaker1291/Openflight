"""Draft contracts: v2 contract + provenance map; confirm -> clean contract
+ retained-provenance sidecar.

Provenance statuses:
  inferred            — name heuristic or guess
  documented          — read from a spec or convention (still a declaration)
  confirmed           — a human explicitly accepted this field
  confirmed_blanket   — accepted via --confirm-all (weaker than per-field)

Provenance is never discarded: `confirm` writes it to
`<out>.provenance.json`, which the evidence package hashes. Ambiguous
heuristics (pos, vel, ...) omit the field instead of guessing, so the
existing checker returns "unverifiable" rather than silently accepting.
"""
from __future__ import annotations

import json
import os

VALID_STATUS = ("inferred", "documented", "confirmed", "confirmed_blanket")

# Feature-level fields that require provenance when present in a draft.
# Structural fields (schema_version, model.*, raw_layout, feature identity
# width) are exempt: they come from the artifact shape, not from guesses.
_PROVENANCE_FIELDS = ("name", "source.quantity", "source.component", "units",
                      "frame", "ordering", "representation",
                      "normalization.method", "normalization.scale",
                      "normalization.offset", "width", "bias_required")

# Obs-name keywords that would guess a quantity, but whose referent is
# genuinely ambiguous (base vs joint, linear vs angular, ...). These omit
# the field instead of marking it inferred.
_AMBIGUOUS_KEYWORDS = ("pos", "vel", "obs", "state", "prop", "joint",
                       "base", "cmd", "act")

# Unambiguous keyword -> proposed quantity (each fill is status: inferred).
_QUANTITY_KEYWORDS = (
    (("gyro", "angular", "omega", "angvel", "ang_vel"), "angular_velocity"),
    (("accel",), "acceleration"),
    (("quat", "orientation", "attitude", "gravity"), "orientation"),
    (("lin_vel", "velocity", "speed", "xyz_vel"), "velocity"),
    (("position", "location", "xyz_pos"), "position"),
)


class DraftError(Exception):
    """Diagnosed draft/confirm failure — never a bare traceback."""


def _parse(path: str) -> dict:
    with open(path) as f:
        text = f.read()
    try:
        return json.loads(text)
    except Exception:
        pass
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except Exception:
        from openflight.adapters.contracts import _parse_simple_yaml
        return _parse_simple_yaml(text)


def load_draft(path: str) -> dict:
    return _parse(path)


def load_contract_json(path: str) -> dict:
    return _parse(path)


def write_draft(draft: dict, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if path.endswith((".yaml", ".yml")):
        try:
            import yaml  # type: ignore
            with open(path, "w") as f:
                yaml.safe_dump(draft, f, sort_keys=False)
            return
        except ImportError:
            pass  # fall through: JSON content regardless of extension
    with open(path, "w") as f:
        json.dump(draft, f, indent=2)


def missing_provenance(draft: dict) -> list[str]:
    """Dotted paths of provenance-relevant fields not covered by the map.

    v2 model drafts: the per-feature _PROVENANCE_FIELDS list. v1 sensor
    drafts: every scalar leaf under the quantity groups (schema_version
    and the provenance map itself are structural).
    """
    prov = draft.get("provenance", {}) or {}
    if "features" not in draft:
        missing = []

        def walk(node, prefix):
            if not isinstance(node, dict):
                return
            for k, v in node.items():
                if k in ("schema_version", "limitations") or (
                        prefix == "" and k == "provenance"):
                    continue
                path = f"{prefix}.{k}" if prefix else k
                if isinstance(v, dict):
                    walk(v, path)
                else:
                    if path not in prov:
                        missing.append(path)

        walk(draft, "")
        return missing
    missing = []
    for i, feat in enumerate(draft.get("features", []) or []):
        if not isinstance(feat, dict):
            continue
        for field in _PROVENANCE_FIELDS:
            # only require provenance for fields actually present
            node = feat
            for part in field.split("."):
                if not isinstance(node, dict) or part not in node:
                    node = None
                    break
                node = node[part]
            if node is None:
                continue
            path = f"features[{i}].{field}"
            if path not in prov:
                missing.append(path)
    return missing


def _get_path(draft: dict, path: str):
    node = draft
    for part in path.replace("]", "").replace("[", ".").split("."):
        if part == "":
            continue
        if isinstance(node, list):
            node = node[int(part)]
        elif isinstance(node, dict):
            if part not in node:
                raise DraftError(f"provenance path not in draft: {path!r}")
            node = node[part]
        else:
            raise DraftError(f"provenance path not in draft: {path!r}")
    return node


def confirm(draft_path: str, out_path: str, confirm: list[str] | None = None,
            confirm_all: bool = False, kind: str = "model") -> dict:
    """Promote inferred fields, emit clean contract + provenance sidecar.

    Per-field confirm: each named path becomes status 'confirmed'.
    --confirm-all: every remaining 'inferred' becomes 'confirmed_blanket'
    (weaker; printed exactly). 'documented' fields are never upgraded by
    blanket. Fails if inferred fields remain unconfirmed without the flag.
    """
    draft = load_draft(draft_path)
    if "provenance" not in draft or not isinstance(draft["provenance"], dict):
        raise DraftError(f"{draft_path} has no provenance map; not a draft")
    prov = {k: dict(v) for k, v in draft["provenance"].items()}
    for path, meta in prov.items():
        if meta.get("status") not in VALID_STATUS:
            raise DraftError(
                f"provenance[{path!r}] status {meta.get('status')!r} "
                f"not in {VALID_STATUS}")

    confirmed: list[str] = []
    for path in (confirm or []):
        if path not in prov:
            raise DraftError(f"--confirm path not in provenance: {path!r}")
        _get_path(draft, path)  # must exist in the contract body too
        prov[path]["status"] = "confirmed"
        confirmed.append(path)

    blanket: list[str] = []
    if confirm_all:
        for path, meta in prov.items():
            if meta.get("status") == "inferred":
                meta["status"] = "confirmed_blanket"
                blanket.append(path)
        if blanket:
            print("confirm --confirm-all: accepting the following inferred "
                  "fields as confirmed_blanket (weaker than per-field):")
            for path in sorted(blanket):
                print(f"  {path}  (was: {prov[path].get('source', '?')})")
    else:
        remaining = sorted(p for p, m in prov.items()
                           if m.get("status") == "inferred")
        if remaining:
            raise DraftError(
                "draft still has inferred fields; confirm them explicitly "
                "(--confirm path ...) or accept all with --confirm-all: "
                + ", ".join(remaining))

    clean = {k: v for k, v in draft.items()
             if k not in ("provenance", "limitations")}
    limitations = draft.get("limitations") or []
    try:
        if kind == "model":
            from openflight.contract import model_contract as MC
            clean = MC.validate_model_contract(clean)
        elif kind == "sensor":
            from openflight.adapters import contracts as C
            clean = C.validate_contract(clean)
        else:
            raise DraftError(f"unknown contract kind {kind!r}")
    except ValueError as e:
        raise DraftError(f"confirmed contract fails schema validation: {e}")

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    write_draft(clean, out_path)  # clean contract (no provenance/limits)
    sidecar = {"schema_version": 1,
               "confirm_mode": "blanket" if confirm_all else "per-field",
               "confirmed": confirmed, "blanket": blanket,
               "not_individually_verified": sorted(blanket),
               "limitations": limitations,
               "provenance": prov}
    with open(out_path + ".provenance.json", "w") as f:
        json.dump(sidecar, f, indent=2)
    if blanket:
        print("not individually verified (confirmed_blanket; listed in "
              "the sidecar under not_individually_verified):")
        for path in sorted(blanket):
            print(f"  {path}")
    if limitations:
        print("unresolved limitations carried into the sidecar "
              "(must appear in any evidence package):")
        for lim in limitations:
            print(f"  [{lim.get('code', '?')}] {lim.get('reason', '')}")
    return {"confirmed": confirmed, "blanket": blanket,
            "limitations": limitations,
            "out": out_path, "sidecar": out_path + ".provenance.json"}


# --------------------------------------------------------------- propose

def _propose_quantity(name: str) -> str | None:
    """Quantity from obs-name keywords; None when ambiguous or unknown.

    Specificity order: an unambiguous keyword wins even inside a name that
    also contains an ambiguous token (base_ang_vel -> angular_velocity);
    only names with no unambiguous match are omitted for ambiguity.
    """
    low = name.lower()
    for keys, qty in _QUANTITY_KEYWORDS:
        if any(k in low for k in keys):
            return qty
    if any(k in low for k in _AMBIGUOUS_KEYWORDS):
        return None  # omit — never guess pos/vel-class names
    return None


def propose_features(entries: list[dict]) -> dict:
    """Obs-space entries -> draft features + raw_layout + provenance.

    dim-3 vectors split into scalar x/y/z (v2 schema allows width 1 or
    quat-4 only); quat-ish dim-4 names become width-4 quaternion features
    with ordering OMITTED (ambiguous across Eigen/SciPy/MuJoCo — the user
    must confirm; the checker blocks U102/E204 until then). Ambiguous
    names omit source entirely (confirm's schema check then demands the
    human fill it). Every field the importer fills gets an inferred
    provenance entry with the heuristic named.
    """
    features: list[dict] = []
    raw_layout: list[dict] = []
    prov: dict[str, dict] = {}

    _DEFAULT_SRC = {
        "name": "obs key name from the obs-space dump",
        "units": "default dimensionless until user confirms units",
        "normalization.method": "no normalization until VecNormalize "
                                "stats are provided",
        "width": "obs entry dimension",
        "source.component": "obs vector component split (x/y/z)",
    }

    def note_feature(i: int, feat: dict, src_note: str,
                     extras: dict | None = None) -> None:
        for field in _PROVENANCE_FIELDS:
            node = feat
            for part in field.split("."):
                node = node.get(part) if isinstance(node, dict) else None
                if node is None:
                    break
            if node is None:
                continue
            path = f"features[{i}].{field}"
            if path in prov:
                continue
            prov[path] = {"status": "inferred",
                          "source": (extras or {}).get(field)
                          or _DEFAULT_SRC.get(field, src_note)}

    for entry in entries:
        name = str(entry.get("name", "obs"))
        dim = int(entry.get("dim", 1))
        qty = _propose_quantity(name)
        src_note = f"keyword heuristic on obs name {name!r}"
        if dim == 4 and qty == "orientation":
            i = len(features)
            feat = {"name": name, "source": {"quantity": "orientation"},
                    "units": "dimensionless",
                    "representation": "quaternion",
                    "normalization": {"method": "none"}, "width": 4}
            features.append(feat)
            note_feature(i, feat, src_note, {
                "units": "quaternion magnitude is dimensionless by "
                         "definition",
                "representation":
                    "dim-4 quat-shaped obs entry; ordering intentionally "
                    "omitted — Eigen/SciPy/MuJoCo disagree "
                    "(CONVENTIONS.md#eigen-quat)",
                "source.quantity": src_note})
            for c in "xyzw":
                raw_layout.append({"quantity": "orientation", "component": c})
        elif dim == 3:
            for c in "xyz":
                i = len(features)
                feat = {"name": f"{name}_{c}",
                        "source": {"quantity": qty, "component": c},
                        "units": "dimensionless",
                        "normalization": {"method": "none"}}
                if qty is None:
                    feat["source"] = {}  # ambiguous: omit, never guess
                features.append(feat)
                note_feature(i, feat, src_note)
                raw_layout.append({"quantity": qty, "component": c}
                                  if qty is not None else {})
        else:  # dim 1, or unrecognized dim -> one scalar per slot so
            # input_size accounting stays honest (a dim-12 actions entry
            # must not collapse into a single width-1 feature)
            slots = dim if dim > 1 else 1
            for j in range(slots):
                i = len(features)
                sname = name if slots == 1 else f"{name}_{j}"
                comp = "x" if slots == 1 else str(j)
                feat = {"name": sname,
                        "source": {"quantity": qty, "component": comp},
                        "units": "dimensionless",
                        "normalization": {"method": "none"}}
                if qty is None:
                    feat["source"] = {}
                features.append(feat)
                note_feature(i, feat, src_note)
                raw_layout.append({"quantity": qty, "component": comp}
                                  if qty is not None else {})

    width = sum(int(f.get("width", 1)) for f in features)
    draft = {"schema_version": 2,
             "model": {"name": "imported", "input_size": width,
                       "dtype": "float32"},
             "raw_layout": raw_layout, "features": features,
             "provenance": prov}
    return draft
