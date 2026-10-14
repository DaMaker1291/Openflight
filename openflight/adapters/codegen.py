"""Generate equivalent Python + C++ sensor adapters from a contract."""
from __future__ import annotations

import os


def generate(contract: dict, py_out: str, cpp_out: str) -> dict:
    ordering = contract["state"]["orientation"]["ordering"]
    os.makedirs(os.path.dirname(py_out) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(cpp_out) or ".", exist_ok=True)
    py = f'''"""Auto-generated sensor adapter (ordering={ordering}). Do not edit."""
import numpy as np
ORDERING = "{ordering}"
def quat_to_rot(q, ordering=ORDERING):
    q = np.asarray(q, dtype=float)
    w, x, y, z = (q[3], q[0], q[1], q[2]) if ordering == "xyzw" else (q[0], q[1], q[2], q[3])
    n = float(np.sqrt(w*w+x*x+y*y+z*z))
    if n < 1e-12: raise ValueError("zero quaternion")
    w,x,y,z = w/n, x/n, y/n, z/n
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])
def accel_measurement(a_w, g_w, q, bias=None, noise=None, ordering=ORDERING):
    import numpy as np
    R = quat_to_rot(np.asarray(q,float), ordering)
    m = R.T @ (np.asarray(a_w,float)-np.asarray(g_w,float))
    if bias is not None: m = m + np.asarray(bias,float)
    if noise is not None: m = m + np.asarray(noise,float)
    return m
def gyro_measurement(omega, bias=None, noise=None):
    import numpy as np
    o = np.asarray(omega,float).copy()
    if bias is not None: o = o + np.asarray(bias,float)
    if noise is not None: o = o + np.asarray(noise,float)
    return o
'''
    cpp = f'''#pragma once
// Auto-generated sensor adapter (ordering={ordering}). Do not edit.
// float32: expect ~1e-7 agreement with the float64 Python reference.
// Zero/near-zero quaternion: guarded (leaves R unnormalized rather than
// dividing by zero); Python raises ValueError for the same input — callers
// must validate quaternions before use.
static inline void quat_to_rot_{ordering}(const float q[4], float R[3][3]) {{
    float w,x,y,z;
{"    x=q[0]; y=q[1]; z=q[2]; w=q[3];" if ordering=="xyzw" else "    w=q[0]; x=q[1]; y=q[2]; z=q[3];"}
    float n = sqrtf(w*w+x*x+y*y+z*z);
    if (n < 1e-12f) n = 1.0f;
    w/=n; x/=n; y/=n; z/=n;
    R[0][0]=1-2*(y*y+z*z); R[0][1]=2*(x*y-z*w); R[0][2]=2*(x*z+y*w);
    R[1][0]=2*(x*y+z*w); R[1][1]=1-2*(x*x+z*z); R[1][2]=2*(y*z-x*w);
    R[2][0]=2*(x*z-y*w); R[2][1]=2*(y*z+x*w); R[2][2]=1-2*(x*x+y*y);
}}
static inline void accel_measurement(const float a_w[3], const float g_w[3],
        const float q[4], const float bias[3], float out[3]) {{
    float R[3][3]; quat_to_rot_{ordering}(q, R);
    float d[3] = {{a_w[0]-g_w[0], a_w[1]-g_w[1], a_w[2]-g_w[2]}};
    for (int i=0;i<3;i++) out[i] = R[0][i]*d[0]+R[1][i]*d[1]+R[2][i]*d[2]+(bias?bias[i]:0.f);
}}
static inline void gyro_measurement(const float omega[3],
        const float bias[3], float out[3]) {{
    for (int i=0;i<3;i++) out[i] = omega[i]+(bias?bias[i]:0.f);
}}
'''
    # need math include
    cpp = "#include <math.h>\n" + cpp
    with open(py_out, "w") as f:
        f.write(py)
    with open(cpp_out, "w") as f:
        f.write(cpp)
    return {"py": py_out, "cpp": cpp_out, "ordering": ordering}
