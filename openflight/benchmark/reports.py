"""Publication-ready reports: CSV/JSON/HTML/TeX + experiment manifest."""
from __future__ import annotations

import csv
import json
import os


def write_reports(outdir: str, latency: dict, correctness: dict,
                  memory: dict, manifest: dict) -> dict:
    os.makedirs(outdir, exist_ok=True)
    raw = os.path.join(outdir, "raw_latency.csv")
    with open(raw, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["run", "latency_us"])
        for i, v in enumerate(latency.get("raw", [])):
            w.writerow([i, v])
    summary = {"latency": latency["stats"], "correctness": correctness,
               "memory": memory}
    with open(os.path.join(outdir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    with open(os.path.join(outdir, "memory_report.json"), "w") as f:
        json.dump(memory, f, indent=2)
    with open(os.path.join(outdir, "correctness_report.json"), "w") as f:
        json.dump(correctness, f, indent=2)
    with open(os.path.join(outdir, "experiment_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    html = f"""<html><head><title>OpenFlight benchmark</title></head><body>
<h1>OpenFlight benchmark report</h1>
<h2>Latency (us)</h2><pre>{json.dumps(latency['stats'], indent=2)}</pre>
<h2>Correctness</h2><pre>{json.dumps(correctness, indent=2)}</pre>
<h2>Memory</h2><pre>{json.dumps(memory, indent=2)}</pre>
<h2>Manifest</h2><pre>{json.dumps(manifest, indent=2)}</pre>
</body></html>"""
    with open(os.path.join(outdir, "benchmark_report.html"), "w") as f:
        f.write(html)
    s = latency["stats"]
    tex = ("\\begin{tabular}{lr}\n\\toprule\nMetric & Value \\\\\n\\midrule\n"
           f"Median latency ($\\mu$s) & {s.get('median_us', float('nan')):.1f} \\\\\n"
           f"p95 latency ($\\mu$s) & {s.get('p95_us', float('nan')):.1f} \\\\\n"
           f"p99 latency ($\\mu$s) & {s.get('p99_us', float('nan')):.1f} \\\\\n"
           f"Max observed ($\\mu$s) & {s.get('max_us', float('nan')):.1f} \\\\\n"
           "\\bottomrule\n\\end{tabular}\n")
    with open(os.path.join(outdir, "benchmark_table.tex"), "w") as f:
        f.write(tex)
    return {"dir": outdir, "files": sorted(os.listdir(outdir))}
