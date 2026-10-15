"""Staged deployment outcomes: every stage records status + evidence + limits.

Statuses: pass | fail | skipped | not-run.
A "pass" at an early stage never implies later stages. In particular,
code generation passing is not verification — only the numerical_parity
and hardware stages speak to behavior, and only on the target they ran on.
"""
from __future__ import annotations

import json
import os

STAGES = ("contract_validation", "adapter_generation", "inference_codegen",
          "host_compilation", "numerical_parity", "cross_compilation",
          "firmware_simulation", "hardware")


class StageReport:
    def __init__(self):
        self.stages = {s: {"status": "not-run", "evidence": None,
                           "limitation": None} for s in STAGES}

    def record(self, stage: str, status: str, evidence=None,
               limitation=None):
        assert stage in self.stages, stage
        assert status in ("pass", "fail", "skipped", "not-run"), status
        self.stages[stage] = {"status": status, "evidence": evidence,
                              "limitation": limitation}

    def failed(self) -> bool:
        return any(v["status"] == "fail" for v in self.stages.values())

    def to_dict(self, meta: dict) -> dict:
        # overall verdict: "failed" whenever any recorded stage failed,
        # so a report from an aborted deploy can never read as a valid
        # deployment (audit round 4)
        return {"schema_version": 1, "meta": meta, "stages": self.stages,
                "result": "failed" if self.failed() else "passed"}

    def write(self, path: str, meta: dict) -> dict:
        d = self.to_dict(meta)
        with open(path, "w") as f:
            json.dump(d, f, indent=2)
        return d

    def render(self) -> str:
        lines = ["", "OPENFLIGHT DEPLOYMENT STAGES", ""]
        for s in STAGES:
            v = self.stages[s]
            line = f"  {s:<22}{v['status'].upper()}"
            if v["evidence"]:
                line += f"  ({v['evidence']})"
            lines.append(line)
            if v["limitation"]:
                lines.append(f"    limitation: {v['limitation']}")
        lines.append("")
        return "\n".join(lines)
