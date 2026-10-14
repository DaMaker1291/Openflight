# OpenFlight quickstart (~5 minutes, no hardware)

```bash
pip install ./dist-openflight
openflight doctor     # confirm torch, numpy, host compiler
openflight version

# 1. Inspect the example model (6 -> 16 -> 2 demo MLP)
openflight inspect examples/quadrotor_adapter/example_weights.pt --arch mlp:6,16,2

# 2. Validate the sensor contract pair (proceeds with warnings)
openflight validate --contract examples/quadrotor_adapter/drone_contract.yaml \
  --model-contract examples/quadrotor_adapter/model_contract.yaml

# 3. Deploy: gate -> adapters -> codegen -> host parity check
openflight deploy --model examples/quadrotor_adapter/example_weights.pt \
  --arch mlp:6,16,2 \
  --contract examples/quadrotor_adapter/drone_contract.yaml \
  --model-contract examples/quadrotor_adapter/model_contract.yaml \
  --target host --output build/quickstart/

# 4. Inspect results
cat build/quickstart/deployment_report.json
```

Notes:
- `example_weights.pt` is a randomly-initialized plumbing fixture (seed
  20260701), not a trained model. Numerical parity is checked against the
  PyTorch reference, not against physical truth.
- The 12-input disturbance observer (`examples/mlp_observer/`) exercises the
  compiler without contracts; its contract pair is intentionally mismatched
  (6 vs 12) to demonstrate fail-closed E203 behavior.
- Every stage in `deployment_report.json` records status, evidence, and
  limitations. `not-run` means exactly that — not verified.
