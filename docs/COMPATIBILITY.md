# OpenFlight compatibility matrix (v0.2 — derived from implementation + tests)

Entries describe what the software establishes, not aspirations.
Unsupported items are refused fail-closed, never silently approximated.

## Model operations

| Operation | Support | Semantics / limits |
|---|---|---|
| Linear (bias=True) | supported | float32 only; arbitrary in/out dims; validated before compilation |
| Linear (bias=False) | refused | explicit error naming the location; use bias=True |
| ReLU | supported | exact |
| Tanh | supported | float32 `tanhf`; differential-tested incl. saturation |
| Sigmoid | supported | float32 logistic; differential-tested incl. saturation |
| LayerNorm / BatchNorm | refused | named-operator error (demonstrated with PPO encoder) |
| Conv / recurrent / attention | refused | named-operator error |
| Functional ops (`F.relu` etc.) | refused | must use module form so the graph extractor sees them |

## Shapes and types

| Capability | Behavior |
|---|---|
| Input/output dims | validated before compilation; contract widths must equal compiled input dim (E203) |
| Batch | batch-1 only; anything else is rejected, never silently misinterpreted |
| dtype | float32 throughout; other dtypes refused |
| Quantization | not supported (documented, not silent) |

## Memory planning

| Claim | Evidence level |
|---|---|
| Static buffer sizes | generated code derives buffer sizes from the plan (tested) |
| No heap in predict path | source scan + object-symbol check on host; target proof outstanding |
| Flash/SRAM totals | estimates until linker-map measurement on hardware |
| WCET | never claimed; observed maxima reported as observed maxima |

## Contracts

Units (registry in `contract/units.py`), frames, quaternion orderings
(wxyz|xyzw), affine/none normalization, feature layouts: checked, with
unknown/ambiguous cases blocking (U-codes). Declaration-vs-reality
(a consistently lying sensor) is out of scope — see EVALUATION.md §5.1.
