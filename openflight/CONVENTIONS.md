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
### px4-frd — PX4 base_link is FRD / NED world
- **Convention:** PX4 `base_link` is FRD (x forward, y right, z down);
  navigation world is NED.
- **Source:** PX4 devguide coordinate conventions,
  <https://docs.px4.io/main/en/ros2/user_guide.html#coordinate-frames>.
- **Failure mode:** FRD vs REP-105 FLU is a real axis mirror, not a
  naming preference; a model declaring PX4's frame against a ROS-imported
  sensor must block (E301/U302), which the checker does by name mismatch.

<a id="isaac-lab"></a>
### isaac-lab — Isaac Lab obs conventions
- **Convention:** legged-gym-lineage obs include base angular velocity
  (rad/s) and projected gravity (dimensionless direction cosines);
  quaternion orientations are wxyz (MuJoCo lineage).
- **Source:** Isaac Lab / legged_gym public repositories,
  <https://github.com/isaac-sim/isaacslab>,
  <https://github.com/leggedrobotics/legged_gym>.
- **Failure mode:** projected gravity is an orientation quantity with
  dimensionless units — earlier OpenFlight versions rejected it as
  implausible (now allowed: dimensionless or angle, Task-1 fix).

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
