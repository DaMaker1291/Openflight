# OpenFlight conventions table

Curated, cited rows for unit / quaternion-ordering / frame conventions.
Importer provenance strings cite row anchors (e.g. `CONVENTIONS.md#ros-quat`).
Every row: convention, source citation, common failure mode.

## Units

<a id="rep103"></a>
### rep103 — REP-103 SI mandate
- **Convention:** ROS base types use SI units: radians for angles,
  rad/s for angular rates, m/s² for linear accelerations, metres for
  positions.
- **Source:** REP-103, <https://www.ros.org/reps/rep-0103.html>.
- **Failure mode:** a driver that publishes deg/s or cm/s² passes every
  internal consistency check until the vehicle moves; OpenFlight treats
  REP-103 units as `documented` declarations, not measurements — verify
  against the actual driver.

<a id="rep105"></a>
### rep105 — REP-105 frame tree
- **Convention:** ROS body frame `base_link` is FLU (x forward, y left,
  z up); world/map is ENU.
- **Source:** REP-105, <https://www.ros.org/reps/rep-0105.html>.
- **Failure mode:** the word "body" hides mirrored axes between FLU and
  FRD stacks (see #px4-frd); frames imported from `.msg` text are always
  `inferred` — the message cannot establish the runtime TF frame.

## Quaternion ordering

<a id="ros-quat"></a>
### ros-quat — ROS geometry_msgs/Quaternion is xyzw
- **Convention:** `geometry_msgs/Quaternion` fields are declared x, y, z,
  w; the wire/memory layout is xyzw.
- **Source:** geometry_msgs/Quaternion message definition,
  <https://docs.ros.org/en/rolling/p/ros2_geometry_msgs/msg/Quaternion.html>.
- **Failure mode:** swapping with wxyz libraries (Eigen constructor,
  some optimizers) silently rotates by a non-rotation; OpenFlight checks
  declared ordering against raw_layout (E403).

<a id="eigen-quat"></a>
### eigen-quat — Eigen wxyz constructor, xyzw memory
- **Convention:** `Eigen::Quaterniond(w, x, y, z)` constructor is wxyz;
  `.coeffs()` memory order is xyzw.
- **Source:** Eigen docs, <https://eigen.tuxfamily.org/dox/classEigen_1_1Quaternion.html>.
- **Failure mode:** the classic trap — constructor order read as memory
  order; both are internally consistent until a buffer crosses libraries.

<a id="mujoco-quat"></a>
### mujoco-quat — MuJoCo body quat is wxyz
- **Convention:** MuJoCo `body quat` is (w, x, y, z).
- **Source:** MuJoCo reference, <https://mujoco.readthedocs.io/en/stable/XMLreference.html#body-quat>.
- **Failure mode:** Isaac-Lab-trained policies (wxyz) checked against
  ROS-side contracts (xyzw) pass only if raw_layout order matches the
  declared ordering; otherwise E403 blocks.

## Frames

<a id="px4-frd"></a>
### px4-frd — PX4 body is FRD, ROS body is FLU (verified against source)
- **Convention:** PX4 docs state verbatim: "Body: PX4 FRD (X Forward,
  Y Right, Z Down); ROS FLU (X Forward, Y Left, Z Up)" and "The FRD (NED)
  conventions are adopted on all PX4 topics unless explicitly specified."
  FLU↔FRD is a pi rotation about X.
- **Source:** PX4 ROS 2 User Guide, "ROS 2 & PX4 Frame Conventions"
  (docs.px4.io/main/en/ros2/user_guide.html, fetched 2026-10-14).
- **Failure mode:** FRD vs FLU is a real axis mirror, not a naming
  preference; a model declaring PX4's frame against a ROS-imported
  sensor must block (E301/U302) — and if both sides are hand-labeled
  "body" and blanket-confirmed, the checker passes on declarations
  alone; the provenance sidecar retains the REP-105 verify-TF origin as
  an unresolved doubt (see test_wrongly_confirmed_frame...).

<a id="isaac-lab"></a>
### isaac-lab — legged_gym / Isaac Lab obs conventions (verified against source)
- **Convention:** legged_gym `compute_observations()` (master@8fa29ac) is
  `base_lin_vel*2.0, base_ang_vel*0.25, projected_gravity,
  commands[:,:3], dof_pos, dof_vel*0.05, actions` (+187 height samples
  when `measure_heights=True`; `clip_observations=100.`). Projected
  gravity is an orientation quantity with dimensionless units (direction
  cosines). legged_gym `init_state.rot` is documented x,y,z,w in the
  config. Isaac Lab (the successor) exposes orientations through several
  interfaces whose ordering differs — verify per interface, do not
  assume.
- **Source:** leggedrobotics/legged_gym master@8fa29acc6fd191
  0c3d9659eef6310bdd301cde0a, `envs/base/legged_robot.py`
  `compute_observations` and `envs/base/legged_robot_config.py`.
- **Failure mode:** projected gravity rejected as implausible for
  "orientation" (fixed: dimensionless or angle allowed); obs_scales
  (0.25/2.0/…) are training-time multipliers that must not be confused
  with sensor units; the nonzero clip silently changes outlier behavior
  if the deployed pipeline omits clipping (W301 limitation).

<a id="common-imus"></a>
### common-imus — vendor IMU unit traps
- **Convention:** consumer IMUs often ship deg/s and g or cm/s² in raw
  firmware registers; flight stacks rescale to SI.
- **Source:** vendor datasheets (e.g. InvenSense ICM-series register
  maps, ST LSM6DS series datasheets).
- **Failure mode:** a contract declaring rad/s against a driver that
  publishes raw counts scales the pipeline by ~57.3 or ~9.81; unit
  declarations are `documented` at best — measure, don't trust, in
  safety-relevant deployments.
