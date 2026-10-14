#!/bin/sh
# Build the frozen OpenFlight v0.1 review snapshot.
# Contents: source, tests, firmware, examples, models, JSON reports,
# freeze manifest, repro instructions, CI workflow. No build artifacts,
# no caches. Prints the archive path and SHA-256.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/openflight-v0.1.tar.gz}"
STAGE="$(mktemp -d)/openflight-v0.1"
mkdir -p "$STAGE"
copy() { mkdir -p "$STAGE/$(dirname "$1")"; cp -r "$ROOT/$1" "$STAGE/$1"; }
copy openflight
copy tests/openflight
copy firmware
copy examples/mlp_observer
copy examples/quadrotor_adapter
copy .github/workflows/openflight.yml
# physics + exporter dependencies imported by the tests (closed under import)
cp "$ROOT/learned_observer.py" "$ROOT/macondo_hover.py" \
   "$ROOT/observer_deploy.py" "$STAGE/"
copy openrescue
mkdir -p "$STAGE/results"
for f in baseline_compare.json contract_battery_report.json firmware_harness.json \
         freeze_v0.1.json heldout_challenge.json independent_challenge.json \
         three_workflows.json; do
  cp "$ROOT/results/$f" "$STAGE/results/$f"
done
cp "$ROOT/learned_observer.pt" "$ROOT/ppo_best.pt" "$STAGE/"
find "$STAGE" \( -name __pycache__ -o -name "*.pyc" \) -exec rm -rf {} + 2>/dev/null || true
tar -czf "$OUT" -C "$(dirname "$STAGE")" openflight-v0.1
echo "archive: $OUT"
shasum -a 256 "$OUT"
