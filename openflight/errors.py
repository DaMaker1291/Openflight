"""Structured errors: every failure says what, where, why, and what to do.

Exit codes (stable):
  0  success (or validation PASS where applicable)
  2  usage error / contract blocked / invalid input files (argparse also uses 2)
  3  code generation or host compilation failure
  4  numerical parity failure
  5  required toolchain missing for the requested operation
"""
from __future__ import annotations


class OpenFlightError(Exception):
    """A diagnosed failure, never a bare traceback."""

    def __init__(self, stage: str, code: str, what: str, where: str,
                 why: str, action: str, exit_code: int = 2):
        super().__init__(what)
        self.stage = stage
        self.code = code
        self.what = what
        self.where = where
        self.why = why
        self.action = action
        self.exit_code = exit_code

    def render(self) -> str:
        return (f"openflight: [{self.stage}] {self.code}: {self.what}\n"
                f"  where:  {self.where}\n"
                f"  why:    {self.why}\n"
                f"  action: {self.action}")


# Action guidance per contract diagnostic code. Kept next to the CLI so the
# checker core stays dependency-free; checker merely carries the strings.
CODE_ACTIONS = {
    "E001": "Fix the sensor contract file (check YAML/JSON syntax and "
            "schema_version), then re-run validate.",
    "E002": "Fix the model contract file (schema_version 2, raw_layout, "
            "features with units and normalization), then re-run validate.",
    "E101": "Align the units: either declare the sensor's true units so a "
            "conversion can be generated, or correct the model contract. "
            "No artifacts were generated.",
    "E102": "The unit is registered but implausible for the declared "
            "quantity (e.g. a length unit on an angular-velocity channel). "
            "Fix the quantity or the unit — both sides can agree and still "
            "both be wrong.",
    "E201": "Fix the normalization on the model contract feature: method "
            "affine with numeric, finite, nonzero scale and offset, or "
            "method none.",
    "E202": "Add units: <unit string> to the model contract feature. Every "
            "feature must declare units, including quaternion features "
            "(use dimensionless).",
    "E203": "Make the contract feature widths sum to the compiled model's "
            "input size, or point deploy at the matching model file.",
    "E204": "Add ordering: wxyz|xyzw to the quaternion feature in the model "
            "contract.",
    "E205": "Replace the zero (or non-finite) affine scale with a nonzero "
            "finite value; a zero scale collapses the feature and is never "
            "generated.",
    "E301": "Provide compatible frame declarations on both sides, or an "
            "explicitly defined transformation supported by this version. "
            "OpenFlight will not guess the rotation.",
    "E302": "Add a bias configuration for the quantity in the sensor "
            "contract, or drop bias_required from the model feature.",
    "E303": "Replace the ambiguous frame value with a concrete frame name "
            "(body/world/...), or — model side only — 'independent' to "
            "declare frame-irrelevance, or omit the field to block as "
            "unverifiable. OpenFlight never interprets 'none'/'any' as a "
            "frame.",
    "E401": "Bind the feature to a quantity the sensor contract describes, "
            "or extend the sensor contract. Check QUANTITY_PATHS spelling.",
    "E402": "Add the referenced (quantity, component) entry to raw_layout "
            "so feature order is fully determined.",
    "E403": "Reconcile raw_layout's component order for this quantity with "
            "the sensor contract's declared quaternion ordering (or fix the "
            "labels). OpenFlight will not guess which side is right.",
    "U101": "Document the sensor's units (or the model feature's units) "
            "explicitly. Compatibility cannot be verified from an "
            "undocumented unit, so deployment stays blocked.",
    "U102": "Document the sensor quaternion ordering (wxyz|xyzw).",
    "U301": "Document the sensor frame for this quantity, or remove the "
            "frame requirement from the model feature if it is genuinely "
            "frame-independent.",
    "U302": "Declare the frame the model feature expects. A model that "
            "declares no frame cannot be verified against a sensor that "
            "documents one, so deployment stays blocked.",
}
