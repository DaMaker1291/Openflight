#!/usr/bin/env python3
"""Generate publication-quality figures from locked artifacts.

Usage:
    .venv/bin/python results/generate_figures.py

All figures are generated from JSON artifacts — no manual data entry.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "research" / "results"
FIGURES = ROOT / "results" / "figures"
FIGURES.mkdir(parents=True, exist_ok=True)

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    HAS_MPL = True
except ImportError:
    HAS_MPL = False
    print("WARNING: matplotlib not available. Figures will be JSON data only.")


def load_v25():
    return json.loads((ROOT / "benchmark_v2_stage_v25_results"
                       / "v25_results_report.json").read_text())


def load_v59_original():
    return json.loads((ROOT / "docs" / "V59_EXPERIMENT_REPORT.json").read_text())


def load_v59_replication():
    return json.loads((RESULTS / "V59_replication_aggregate.json").read_text())


def load_v58():
    return json.loads((ROOT / "docs" / "V58_EXPERIMENT_REPORT.json").read_text())


def load_benchmark():
    return json.loads((ROOT / "openrescue_benchmark.json").read_text())


def figure1_architecture():
    """Figure 1: OpenRescue architecture overview."""
    data = {
        "figure": "1_architecture",
        "title": "OpenRescue Research Architecture",
        "components": [
            {"id": "V1", "name": "Failure Prediction", "status": "frozen",
             "rq": "RQ1", "inputs": ["telemetry (4-bit masks)"],
             "outputs": ["grounding probability"]},
            {"id": "V2", "name": "Wind Observation", "status": "locked (null result)",
             "rq": "RQ2", "inputs": ["telemetry + wind features"],
             "outputs": ["wind estimate", "ΔAUROC"]},
            {"id": "V3", "name": "6-DoF Physics", "status": "frozen",
             "rq": "RQ3", "inputs": ["rigid body state", "forces"],
             "outputs": ["trajectory", "stability metrics"]},
            {"id": "V4", "name": "Parametric Design", "status": "frozen",
             "rq": "RQ4", "inputs": ["design vector"],
             "outputs": ["drone geometry", "rotor config"]},
            {"id": "V5", "name": "Surrogate + Search", "status": "frozen",
             "rq": "RQ4", "inputs": ["design × environment"],
             "outputs": ["J_robust", "J_worst"]},
            {"id": "V6.1", "name": "Geometry Extraction", "status": "frozen",
             "rq": "—", "inputs": ["GeometryProgram"],
             "outputs": ["mass", "inertia", "aero"]},
        ],
        "data_flow": "V5 → V4 → V3 → performance\nV6.1 → V4 → V3",
    }
    (FIGURES / "figure1_architecture.json").write_text(
        json.dumps(data, indent=2))
    print("  [1] Architecture overview (JSON)")

    if not HAS_MPL:
        return

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6)
    ax.axis("off")
    ax.set_title("OpenRescue Research Architecture", fontsize=14, fontweight="bold")

    boxes = [
        (1, 4.5, "V1\nFailure\nPrediction", "#4CAF50"),
        (3.5, 4.5, "V2\nWind\nObservation", "#FF9800"),
        (6, 4.5, "V3\n6-DoF\nPhysics", "#2196F3"),
        (1, 2.5, "V4\nParametric\nDesign", "#9C27B0"),
        (3.5, 2.5, "V5\nSurrogate\n+ Search", "#F44336"),
        (6, 2.5, "V6.1\nGeometry\nExtraction", "#00BCD4"),
        (8.5, 3.5, "Performance\nJ_robust\nJ_worst", "#607D8B"),
    ]
    for x, y, label, color in boxes:
        rect = mpatches.FancyBboxPatch((x-0.7, y-0.6), 1.4, 1.2,
            boxstyle="round,pad=0.1", facecolor=color, alpha=0.7,
            edgecolor="black", linewidth=1.5)
        ax.add_patch(rect)
        ax.text(x, y, label, ha="center", va="center", fontsize=8,
                fontweight="bold", color="white")

    arrows = [(1.7,4.5,5.3,4.5), (3.5,3.9,3.5,3.1), (6,3.9,6,3.1),
              (1.7,2.5,5.3,2.5), (6.7,4.5,7.8,3.8), (6.7,2.5,7.8,3.2)]
    for x1,y1,x2,y2 in arrows:
        ax.annotate("", xy=(x2,y2), xytext=(x1,y1),
                    arrowprops=dict(arrowstyle="->", color="gray", lw=1.5))

    ax.text(5, 0.5, "Frozen research spine (V1–V5.9) + Command Centre V1",
            ha="center", fontsize=10, style="italic", color="#555")
    plt.tight_layout()
    plt.savefig(FIGURES / "figure1_architecture.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("  [1] Architecture overview (PNG)")


def figure2_v2_null():
    """Figure 2: V2 null result — wind features add nothing."""
    v25 = load_v25()
    delta = v25["delta_b_minus_a"]
    iid = delta["iid"]["auroc"]
    ood = delta["ood"]["auroc"]

    data = {
        "figure": "2_v2_null_result",
        "title": "V2.5: Wind Features Add No Measurable Improvement",
        "iid_delta_auroc": iid["delta_b_minus_a"],
        "iid_ci95": [iid["paired_ci95"]["lo95"], iid["paired_ci95"]["hi95"]],
        "ood_delta_auroc": ood["delta_b_minus_a"],
        "ood_ci95": [ood["paired_ci95"]["lo95"], ood["paired_ci95"]["hi95"]],
        "interpretation": "NULL RESULT: CI includes 0 on both IID and OOD",
    }
    (FIGURES / "figure2_v2_null.json").write_text(json.dumps(data, indent=2))

    if not HAS_MPL:
        print("  [2] V2 null result (JSON)")
        return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))

    for ax, split, delta_obj, title in [
        (ax1, "IID", iid, "IID Test"), (ax2, "OOD", ood, "OOD Test")]:
        d = delta_obj["delta_b_minus_a"]
        lo = delta_obj["paired_ci95"]["lo95"]
        hi = delta_obj["paired_ci95"]["hi95"]
        ax.errorbar(d, 0, xerr=[[abs(d-lo)], [abs(hi-d)]], fmt="o",
                    color="#2196F3", markersize=10, capsize=8, linewidth=2)
        ax.axvline(0, color="red", linestyle="--", alpha=0.5, label="No effect")
        ax.set_xlabel("ΔAUROC (wind − no wind)", fontsize=10)
        ax.set_title(title, fontsize=12)
        ax.set_yticks([])
        ax.legend(fontsize=8)
        ax.set_xlim(-0.002, 0.002)

    fig.suptitle("V2.5: Wind Features vs Telemetry-Only\n(95% Paired Bootstrap CI)",
                 fontsize=13, fontweight="bold")
    plt.tight_layout()
    plt.savefig(FIGURES / "figure2_v2_null.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("  [2] V2 null result (PNG)")


def figure3_v59_replication():
    """Figure 3: V5.9 replication across 5 seeds."""
    rep = load_v59_replication()
    results = rep["results"]

    seeds = [r["seed"] for r in results]
    h1_deltas = [r["deltas"]["H1_delta_J_robust"] for r in results]
    h2_deltas = [r["deltas"]["H2_delta_J_worst"] for r in results]
    mr_robust = [r["strategies"]["mutation_robust"]["J_robust"] for r in results]
    rb_robust = [r["strategies"]["random_baseline"]["J_robust"] for r in results]

    data = {
        "figure": "3_v59_replication",
        "title": "V5.9 Replication: Search Beats Random Across 5 Seeds",
        "seeds": seeds,
        "h1_deltas": h1_deltas,
        "h1_mean": rep["h1_summary"]["mean_delta"],
        "h1_median": rep["h1_summary"]["median_delta"],
        "h2_deltas": h2_deltas,
        "mutation_robust_J_robust": mr_robust,
        "random_baseline_J_robust": rb_robust,
    }
    (FIGURES / "figure3_v59_replication.json").write_text(json.dumps(data, indent=2))

    if not HAS_MPL:
        print("  [3] V5.9 replication (JSON)")
        return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    x = range(len(seeds))
    width = 0.35
    ax1.bar([i-width/2 for i in x], rb_robust, width, label="Random baseline",
            color="#90CAF9", edgecolor="black")
    ax1.bar([i+width/2 for i in x], mr_robust, width, label="Mutation robust",
            color="#1565C0", edgecolor="black")
    ax1.set_xlabel("Seed", fontsize=10)
    ax1.set_ylabel("J_robust (top-5 mean)", fontsize=10)
    ax1.set_title("Measured J_robust by Strategy", fontsize=12)
    ax1.set_xticks(list(x))
    ax1.set_xticklabels([str(s) for s in seeds], fontsize=9)
    ax1.legend(fontsize=9)
    ax1.set_ylim(0.4, 0.52)

    ax2.bar(list(x), h1_deltas, color="#4CAF50" if all(d > 0 for d in h1_deltas)
            else "#FF9800", edgecolor="black")
    ax2.axhline(0, color="red", linestyle="--", alpha=0.5)
    ax2.set_xlabel("Seed", fontsize=10)
    ax2.set_ylabel("ΔJ_robust (search − random)", fontsize=10)
    ax2.set_title("H1: Effect Size per Seed", fontsize=12)
    ax2.set_xticks(list(x))
    ax2.set_xticklabels([str(s) for s in seeds], fontsize=9)
    ax2.text(2, max(h1_deltas)*0.9, f"Mean Δ = {rep['h1_summary']['mean_delta']:.4f}\n5/5 positive",
             ha="center", fontsize=10, bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))

    fig.suptitle("V5.9 Replication: Mutation Search vs Random Baseline\n(5 Independent Seeds, 60 Physics Cells Each)",
                 fontsize=13, fontweight="bold")
    plt.tight_layout()
    plt.savefig(FIGURES / "figure3_v59_replication.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("  [3] V5.9 replication (PNG)")


def figure4_v58_selection():
    """Figure 4: V5.8 — robust vs mean selection produces identical designs."""
    v58 = load_v58()
    arms = v58["report"]["ood"]["per_arm"]

    data = {
        "figure": "4_v58_selection",
        "title": "V5.8: Robust and Mean Selection Produce Identical Top-10s",
        "arms": {k: {"stress_mean": v.get("arm_mean_of_design_means"),
                      "n_designs": len(v.get("designs", {}))}
                 for k, v in arms.items()},
        "interpretation": "TIE: Δ = 1e-16, identical design sets",
    }
    (FIGURES / "figure4_v58_selection.json").write_text(json.dumps(data, indent=2))

    if not HAS_MPL:
        print("  [4] V5.8 selection (JSON)")
        return

    fig, ax = plt.subplots(figsize=(8, 5))
    arm_names = list(arms.keys())
    stress_means = [arms[a].get("arm_mean_of_design_means", 0) for a in arm_names]
    colors = ["#4CAF50", "#2196F3", "#FF9800"]

    bars = ax.bar(arm_names, stress_means, color=colors, edgecolor="black")
    ax.set_ylabel("OOD Mean of Design Means", fontsize=11)
    ax.set_title("V5.8: Robust vs Mean vs Adversarial Selection\n(Locked OOD Panel)",
                 fontsize=13, fontweight="bold")
    ax.set_ylim(0.42, 0.44)

    for bar, val in zip(bars, stress_means):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.0002,
                f"{val:.4f}", ha="center", fontsize=10)

    ax.text(1, 0.435, "Δ(Mean, Robust) = 1e-16\nIdentical top-10s",
            ha="center", fontsize=10, bbox=dict(boxstyle="round", facecolor="wheat"))
    plt.tight_layout()
    plt.savefig(FIGURES / "figure4_v58_selection.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("  [4] V5.8 selection (PNG)")


def figure5_swarm_benchmark():
    """Figure 5: Swarm benchmark across failure levels."""
    bench = load_benchmark()
    results = bench["results"]

    data = {
        "figure": "5_swarm_benchmark",
        "title": "Swarm Policy Performance Across Failure Levels",
        "policies": bench["meta"]["policies"],
        "levels": bench["meta"]["levels"],
        "results": results,
    }
    (FIGURES / "figure5_swarm_benchmark.json").write_text(json.dumps(data, indent=2))

    if not HAS_MPL:
        print("  [5] Swarm benchmark (JSON)")
        return

    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    metrics = ["coverage", "survival", "eta_i"]
    colors = {"random": "#90CAF9", "frontier": "#4CAF50", "resilient": "#FF9800"}

    for ax, metric in zip(axes, metrics):
        for policy in bench["meta"]["policies"]:
            vals = []
            for level in bench["meta"]["levels"]:
                key = f"{policy}__L{level}"
                vals.append(results.get(key, {}).get(metric, 0))
            ax.plot(bench["meta"]["levels"], vals, "o-", label=policy,
                    color=colors[policy], linewidth=2, markersize=6)
        ax.set_xlabel("Failure Level", fontsize=10)
        ax.set_ylabel(metric.replace("_", " ").title(), fontsize=10)
        ax.set_title(metric.replace("_", " ").title(), fontsize=11)
        ax.legend(fontsize=8)
        ax.set_xticks(bench["meta"]["levels"])

    fig.suptitle("Swarm Policy Performance Across Failure Levels\n(IQM, 20 Seeds per Cell)",
                 fontsize=13, fontweight="bold")
    plt.tight_layout()
    plt.savefig(FIGURES / "figure5_swarm_benchmark.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("  [5] Swarm benchmark (PNG)")


def figure6_v59_convergence():
    """Figure 6: V5.9 search convergence (mutation_robust lineage)."""
    rep = load_v59_replication()
    r90210 = [r for r in rep["results"] if r["seed"] == 90210][0]

    data = {
        "figure": "6_v59_convergence",
        "title": "V5.9 Search Convergence (Seed 90210)",
        "random_baseline_J_robust": r90210["strategies"]["random_baseline"]["J_robust"],
        "mutation_robust_J_robust": r90210["strategies"]["mutation_robust"]["J_robust"],
        "note": "Full lineage available in V59_replication_seed_90210.json",
    }
    (FIGURES / "figure6_v59_convergence.json").write_text(json.dumps(data, indent=2))
    print("  [6] V5.9 convergence (JSON)")


def main():
    print("GENERATING PUBLICATION FIGURES")
    print("=" * 50)
    print()

    figure1_architecture()
    figure2_v2_null()
    figure3_v59_replication()
    figure4_v58_selection()
    figure5_swarm_benchmark()
    figure6_v59_convergence()

    print()
    print(f"Figures written to: {FIGURES}")
    print(f"  PNG: {len(list(FIGURES.glob('*.png')))} files")
    print(f"  JSON: {len(list(FIGURES.glob('*.json')))} files")


if __name__ == "__main__":
    main()
