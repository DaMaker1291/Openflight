"""Host-side benchmark runner.

Level 1 (host): compile generated model.cpp with cc, run differential +
timing harness. Level 2 (MCU): same firmware via serial (pyserial optional);
without hardware, runner records host results and marks target fields as
'not measured' rather than inventing numbers.
"""
from __future__ import annotations

import os
import subprocess
import tempfile

import numpy as np
import torch

from openflight.benchmark.statistics import summarize


HARNESS = r"""
#include <cstdio>
#include <ctime>
#include <cmath>
#include "model.h"
int main(int argc, char** argv) {
    const char* fin = argv[1]; const char* fout = argv[2];
    FILE* f = fopen(fin, "rb"); fseek(f,0,SEEK_END); long n = ftell(f)/sizeof(float)/{IN};
    fseek(f,0,SEEK_SET);
    float* in = new float[(size_t)n*{IN}]; float* out = new float[(size_t)n*{OUT}];
    double* lat = new double[n];
    if (fread(in,sizeof(float),(size_t)n*{IN},f)!=(size_t)n*{IN}) return 1; fclose(f);
    // warmup
    { float o[{OUT}]; for(int k=0;k<10;k++) openflight::predict(in, o); }
    for (long k=0;k<n;k++) {
        struct timespec a,b; clock_gettime(CLOCK_MONOTONIC,&a);
        openflight::predict(in+k*{IN}, out+k*{OUT});
        clock_gettime(CLOCK_MONOTONIC,&b);
        lat[k]=(b.tv_sec-a.tv_sec)*1e6+(b.tv_nsec-a.tv_nsec)/1e3;
    }
    f=fopen(fout,"wb"); fwrite(out,sizeof(float),(size_t)n*{OUT},f); fclose(f);
    FILE* fl=fopen(argv[3],"w"); for(long k=0;k<n;k++) fprintf(fl,"%.3f\n",lat[k]); fclose(fl);
    delete[] in; delete[] out; delete[] lat;
    return 0;
}
"""


def run_host(model: torch.nn.Module, builddir: str, runs: int = 1000,
             deadline_us: float | None = None, seed: int = 0,
             input_range: tuple = (-1.0, 1.0)) -> dict:
    import json as J
    if runs < 1:
        raise ValueError("runs must be >= 1")
    meta = J.load(open(os.path.join(builddir, "model_metadata.json")))
    IN, OUT = meta["input_size"], meta["output_size"]
    rng = np.random.default_rng(seed)
    X = rng.uniform(*input_range, size=(runs, IN)).astype(np.float32)
    with torch.no_grad():
        ref = model(torch.from_numpy(X)).numpy()
        if ref.ndim == 1:
            ref = ref[:, None]
    # write inputs
    tmp = tempfile.mkdtemp()
    fin = os.path.join(tmp, "in.bin"); fout = os.path.join(tmp, "out.bin")
    flat = os.path.join(tmp, "lat.csv")
    X.tofile(fin)
    harness = HARNESS.replace("{IN}", str(IN)).replace("{OUT}", str(OUT))
    hpath = os.path.join(tmp, "harness.cpp")
    with open(hpath, "w") as f:
        f.write(harness)
    exe = os.path.join(tmp, "harness")
    cc = os.environ.get("CXX", "c++")
    r = subprocess.run([cc, "-O2", "-std=c++17", "-I", builddir, hpath,
                        os.path.join(builddir, "model.cpp"), "-o", exe],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"host compile failed: {r.stderr[:2000]}")
    # static allocation check on generated model.cpp (source text only;
    # the nm -u object-symbol test is the stronger host-side check)
    from openflight.compiler.validation import scan_no_heap
    alloc_found = scan_no_heap(os.path.join(builddir, "model.cpp"))
    # time via harness (device-side equivalent: harness measures predict only)
    r2 = subprocess.run([exe, fin, fout, flat], capture_output=True, text=True)
    if r2.returncode != 0:
        raise RuntimeError(f"harness failed: {r2.stderr[:2000]}")
    got = np.fromfile(fout, dtype=np.float32).reshape(runs, OUT)
    lat = np.loadtxt(flat, ndmin=1)
    err = np.abs(got - ref)
    maxae = float(err.max())
    meanerr = float(err.mean())
    stats = summarize(lat, deadline_us)
    stats["timer"] = "clock_gettime(CLOCK_MONOTONIC); predict-only, serial excluded"
    return {"ref": ref, "got": got, "latency": stats,
            "max_abs_err": maxae, "mean_abs_err": meanerr,
            "alloc_in_generated": alloc_found,
            "raw_latency": lat.tolist()}
