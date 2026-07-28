#!/usr/bin/env python3
"""
ether_seed.py -- populate a TRIAL store with a scripted history.

  python3 ether_seed.py                       # seeds .claude/ether-trial
  python3 ether_seed.py --dir /tmp/ltm-trial  # anywhere else
  python3 ether_seed.py --reset               # wipe and reseed

Offline and deterministic: no model calls. Events are written exactly
as the hook and consolidator would have written them, then the sketch
is rebuilt from the log -- which also re-proves sketch = f(log) (F19).

The scenario is a three-week robotics project, chosen so the trial
exercises every mechanism you'd want to see before trusting the system:

  frequency vs salience   quaternion work recurs across many sessions;
                          the lidar sign-error happened ONCE but was
                          pinned -- both should score high, for
                          different reasons (F10.3)
  canonicalization        the same concept appears as "quaternion",
                          "quat", "rotation representation", "wxyz
                          order" -- all must land on one key (F18)
  supersession            an assumption about IMU drift is later
                          retracted; BOTH must remain visible (F11)
  parked threads          one tempting direction is set aside and must
                          not be re-proposed
  provenance ranking      declaration > testimony > reconstruction on
                          the same topic (F15)
  query traffic           reads reinforce (min>0) and are themselves
                          logged as behaviour (F12, F15)
  aging                   an aging pass mid-history; recently used
                          concepts should survive it better (F12)
  honest misses           a topic never discussed must return 0 --
                          definitely never seen, no false negatives
"""

import argparse
import datetime as dt
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ether_consolidate import rebuild  # noqa: E402
from ether_store import EtherStore, keys_of  # noqa: E402

TRIAL_ALIASES = {
    "_meta": {"purpose": "trial-domain alias table (robotics project)",
              "provenance": "declaration", "version": 1},
    "canonical": {
        "quaternion": {
            "label": "Quaternion", "kind": "concept",
            "aliases": ["quat", "quats", "quaternions", "wxyz order",
                        "rotation representation", "unit quaternion"]},
        "gimbal-lock": {
            "label": "Gimbal lock", "kind": "concept",
            "aliases": ["gimbal", "euler singularity",
                        "orientation singularity"]},
        "ekf": {
            "label": "EKF", "kind": "concept",
            "aliases": ["extended kalman filter", "kalman filter",
                        "state estimator"]},
        "lidar-calibration": {
            "label": "Lidar calibration", "kind": "concept",
            "aliases": ["lidar extrinsics", "lidar extrinsic calibration",
                        "laser calibration", "extrinsic calibration"]},
        "ros2": {
            "label": "ROS 2", "kind": "concept",
            "aliases": ["ros 2", "ros-2", "rclpy", "tf2"]},
        "matlab-codegen": {
            "label": "MATLAB codegen", "kind": "concept",
            "aliases": ["matlab code generation", "codegen",
                        "matlab coder"]},
        "pose-estimation": {
            "label": "Pose estimation", "kind": "concept",
            "aliases": ["pose estimator", "pose tracking",
                        "6dof estimation"]},
    },
}


def ts(days_ago, hour=10):
    d = dt.datetime.now() - dt.timedelta(days=days_ago)
    return d.replace(hour=hour, minute=0, second=0).strftime(
        "%Y-%m-%dT%H:%M:%S")


def user(day, verb, prov, kind, weight, text, keys, defeasible=False):
    return {"ts": ts(day), "session_id": "trial-d%d" % day,
            "type": "user_manifest", "author": "user", "verb": verb,
            "provenance": prov, "kind": kind, "weight": weight,
            "defeasible": defeasible, "text": text,
            "entity_keys": [{"key": k, "w": 1.0} for k in keys]}


def episode(day, gist, keys, pairs=()):
    """A consolidated reconstruction manifest. Surface forms are used
    deliberately -- canonicalization happens on replay."""
    return {"ts": ts(day, 15), "session_id": "trial-d%d" % day,
            "capture_id": "trial%02d" % day,
            "type": "reconstruction_manifest", "author": "agent",
            "provenance": "reconstruction",
            "note": "self-report; reconstruction, not readout (F14)",
            "manifests": [{"episode_gist": gist,
                           "entity_keys": [{"key": k, "w": w}
                                           for k, w in keys],
                           "pair_keys": [{"key": p, "w": 2.0}
                                         for p in pairs],
                           "novelty": [], "encoder": "trial-seed"}],
            "consistency": {"jaccard": 0.86, "shared": [k for k, _ in keys],
                            "only_first": [], "only_second": [],
                            "mean_weight_diff_on_shared": 0.4}}


def query(day, text, keys):
    return {"ts": ts(day, 17), "session_id": "trial-d%d" % day,
            "type": "query", "author": "user", "provenance": "readout",
            "text": text, "keys": keys, "familiarity": {}}


def aging(day, factor):
    return {"ts": ts(day, 23), "type": "aging", "author": "system",
            "provenance": "readout", "factor": factor}


def history():
    """Chronological. Told as a project, not a fixture."""
    return [
        # --- week 1: conventions laid down, pose work begins -----------
        user(21, "declare", "declaration", "ruling", 8.0,
             "all poses are in the world frame, quaternions in wxyz order",
             ["quaternion", "wxyz order", "world frame"]),
        episode(21, "refactored the pose estimator from euler angles to "
                    "quaternions to eliminate gimbal lock",
                [("pose estimator", 5.0), ("quaternion", 5.0),
                 ("gimbal lock", 4.0), ("matlab coder", 2.0)],
                ["quaternion x gimbal lock"]),
        user(20, "note", "testimony", "note", 2.0,
             "the tf2 transform conventions confuse me every single time",
             ["tf2", "transform", "conventions"]),
        episode(19, "tuned the EKF process noise for the warehouse robot",
                [("extended kalman filter", 5.0), ("process noise", 3.0),
                 ("pose tracking", 2.0)]),

        # --- week 2: an assumption, recurring quaternion work ----------
        user(18, "assume", "declaration", "assumption", 4.0,
             "IMU drift is negligible over 60 second windows",
             ["imu", "drift"], defeasible=True),
        episode(17, "debugged slerp interpolation producing a flipped "
                    "rotation at the antipode",
                [("slerp", 4.0), ("quat", 5.0), ("interpolation", 3.0)]),
        episode(15, "ported the rotation representation helpers to C++ "
                    "and matched the MATLAB reference",
                [("rotation representation", 4.0), ("matlab codegen", 3.0),
                 ("c++", 2.0)]),
        episode(14, "wrote unit tests for unit quaternion normalisation "
                    "drift over long trajectories",
                [("unit quaternion", 4.0), ("unit tests", 2.0)]),

        # --- THE BUG: one occurrence, high salience -------------------
        episode(12, "spent the day chasing a sign error in the lidar "
                    "extrinsic calibration; the yaw term was negated",
                [("lidar extrinsic calibration", 6.0), ("sign error", 5.0),
                 ("yaw", 3.0)],
                ["lidar extrinsic calibration x sign error"]),
        user(12, "remember", "declaration", "pin", 5.0,
             "lidar extrinsics: yaw sign is negated relative to the "
             "datasheet convention -- cost a full day",
             ["lidar extrinsics", "yaw", "sign"]),

        # --- reads, corrections, parked directions --------------------
        query(10, "what is our quaternion convention",
              ["quaternion", "convention"]),
        user(8, "retract", "declaration", "retraction", 8.0,
             "IMU drift is NOT negligible: measured 3 degrees over 60s "
             "on the new unit -- supersedes the day-18 assumption",
             ["imu", "drift"]),
        user(7, "park", "declaration", "parked", 6.0,
             "neural implicit mapping for the warehouse robot -- "
             "interesting but out of scope this quarter",
             ["neural implicit mapping", "warehouse robot"]),
        aging(5, 0.8),

        # --- week 3: different work; quaternions go untouched ----------
        episode(4, "restructured the ROS 2 launch files and parameter "
                   "yaml layout",
                [("ros 2", 5.0), ("launch files", 4.0), ("yaml", 2.0)]),
        episode(2, "added a rclpy lifecycle node for the sensor bringup",
                [("rclpy", 5.0), ("lifecycle node", 4.0)]),
        query(1, "lidar calibration sign convention",
              ["lidar-calibration", "sign", "convention"]),
    ]


def main():
    ap = argparse.ArgumentParser(description="seed a trial LTM store")
    ap.add_argument("--dir", default=os.path.join(".claude", "ether-trial"))
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()

    base = os.path.abspath(args.dir)
    if args.reset and os.path.isdir(base):
        shutil.rmtree(base)
    os.makedirs(base, exist_ok=True)
    with open(os.path.join(base, "concept_aliases.json"), "w") as f:
        json.dump(TRIAL_ALIASES, f, indent=2)

    os.environ["ETHER_DIR"] = base
    with EtherStore(base) as store:
        if store.stats()["events"]:
            print("store already has events; use --reset to start over.")
            return
        events = history()
        for rec in events:
            store.append(rec, keys=keys_of(rec))
        # sketch is a fold over the log, so build it the honest way
        rebuild(store, base)
        print("seeded %d events into %s" % (len(events), base))

    print("""
try these:
  python3 ether_inspect.py --dir %(d)s
  python3 ether_inspect.py --dir %(d)s --key quaternion
  python3 ether_inspect.py --dir %(d)s --key lidar-calibration
  python3 ether_inspect.py --dir %(d)s --key kubernetes      # never seen
  python3 ether_consolidate.py --dir %(d)s --rebuild
""" % {"d": base})


if __name__ == "__main__":
    main()
