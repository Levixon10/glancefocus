"""Turn MediaPipe Face Landmarker output into a gaze feature vector.

The vector combines three kinds of signal, because none is good enough alone:

* iris position inside each eye (where the eyes point relative to the head),
* MediaPipe's eyeLook* blendshapes (a learned estimate of the same thing),
* head pose (where the head points, and where it is relative to the camera).

The calibration model (``mapping.py``) learns how this vector maps to a point on
the desktop, so the exact conventions here only need to be smooth and consistent.
This module depends on numpy only so it can be unit tested without MediaPipe.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# Landmark indices in the 478-point face mesh. Eyes are named by where they appear
# in the *image*; the camera sees you mirrored, so the image-left eye is your right.
IMAGE_LEFT_EYE = {"left": 33, "right": 133, "top": 159, "bottom": 145, "iris": 468}
IMAGE_RIGHT_EYE = {"left": 362, "right": 263, "top": 386, "bottom": 374, "iris": 473}
EYE_DRAW_POINTS = (33, 133, 159, 145, 468, 362, 263, 386, 374, 473)

BLENDSHAPES = (
    "eyeLookInLeft", "eyeLookOutLeft", "eyeLookUpLeft", "eyeLookDownLeft",
    "eyeLookInRight", "eyeLookOutRight", "eyeLookUpRight", "eyeLookDownRight",
)

FEATURE_NAMES = (
    "gaze_h", "gaze_v",
    "img_left_eye_h", "img_left_eye_v", "img_right_eye_h", "img_right_eye_v",
    "img_left_eye_open", "img_right_eye_open",
    *BLENDSHAPES,
    "head_fx", "head_fy", "head_roll", "head_tx", "head_ty", "head_tz",
)
# Features that also get pairwise products in the calibration model.
CORE_FEATURES = ("gaze_h", "gaze_v", "head_fx", "head_fy", "head_tx", "head_ty")
N_FEATURES = len(FEATURE_NAMES)
BLINK_THRESHOLD = 0.5


@dataclass
class FaceObservation:
    features: np.ndarray  # shape (N_FEATURES,)
    blink: bool
    eye_points: np.ndarray  # (len(EYE_DRAW_POINTS), 2) pixel coords, for debug drawing


def eye_features(points: np.ndarray, eye: dict[str, int]) -> tuple[float, float, float] | None:
    """Iris offset from the eye centre, in units of eye width, plus eye openness.

    Returns (horizontal, vertical, openness); horizontal is positive towards the
    image's right, vertical positive towards the image's bottom.
    """
    a, b = points[eye["left"]], points[eye["right"]]
    axis = b - a
    width = float(math.hypot(axis[0], axis[1]))
    if width < 1e-6:
        return None
    u = axis / width
    v = np.array([-u[1], u[0]])
    d = points[eye["iris"]] - (a + b) / 2
    openness = float(math.hypot(*(points[eye["top"]] - points[eye["bottom"]]))) / width
    return float(d @ u) / width, float(d @ v) / width, openness


def head_pose(matrix) -> tuple[float, float, float, float, float, float]:
    """(forward_x, forward_y, roll, tx, ty, tz) from the 4x4 facial transformation matrix."""
    m = np.asarray(matrix, dtype=float).reshape(4, 4)
    r = m[:3, :3]
    forward = r @ np.array([0.0, 0.0, 1.0])
    roll = math.atan2(r[1, 0], r[0, 0])
    return float(forward[0]), float(forward[1]), roll, float(m[0, 3]), float(m[1, 3]), float(m[2, 3])


def build_features(
    points: np.ndarray,
    blendshapes: dict[str, float],
    pose: tuple[float, float, float, float, float, float],
) -> FaceObservation | None:
    left = eye_features(points, IMAGE_LEFT_EYE)
    right = eye_features(points, IMAGE_RIGHT_EYE)
    if left is None or right is None:
        return None
    vec = np.array(
        [
            (left[0] + right[0]) / 2, (left[1] + right[1]) / 2,
            left[0], left[1], right[0], right[1],
            left[2], right[2],
            *(blendshapes.get(name, 0.0) for name in BLENDSHAPES),
            *pose,
        ],
        dtype=float,
    )
    blink = (blendshapes.get("eyeBlinkLeft", 0.0) + blendshapes.get("eyeBlinkRight", 0.0)) / 2 > BLINK_THRESHOLD
    return FaceObservation(vec, blink, points[list(EYE_DRAW_POINTS)].copy())


def from_landmarker_result(result, width: int, height: int) -> FaceObservation | None:
    """Adapter for mediapipe.tasks FaceLandmarkerResult."""
    if not result.face_landmarks:
        return None
    landmarks = result.face_landmarks[0]
    if len(landmarks) < 478:  # model without iris refinement
        return None
    points = np.array([(p.x * width, p.y * height) for p in landmarks], dtype=float)
    blend = {c.category_name: c.score for c in result.face_blendshapes[0]} if result.face_blendshapes else {}
    pose = (
        head_pose(result.facial_transformation_matrixes[0])
        if result.facial_transformation_matrixes
        else (0.0,) * 6
    )
    return build_features(points, blend, pose)
