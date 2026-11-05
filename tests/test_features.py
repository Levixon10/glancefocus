import numpy as np

from glancefocus.gaze.features import (
    FEATURE_NAMES,
    IMAGE_LEFT_EYE,
    IMAGE_RIGHT_EYE,
    N_FEATURES,
    build_features,
    eye_features,
    head_pose,
)


def face_points(iris_shift=(0.0, 0.0)):
    pts = np.zeros((478, 2))
    for eye, cx in ((IMAGE_LEFT_EYE, 200.0), (IMAGE_RIGHT_EYE, 400.0)):
        pts[eye["left"]] = (cx - 30, 300)
        pts[eye["right"]] = (cx + 30, 300)
        pts[eye["top"]] = (cx, 290)
        pts[eye["bottom"]] = (cx, 310)
        pts[eye["iris"]] = (cx + iris_shift[0], 300 + iris_shift[1])
    return pts


def test_iris_centered():
    h, v, openness = eye_features(face_points(), IMAGE_LEFT_EYE)
    assert abs(h) < 1e-9 and abs(v) < 1e-9
    assert openness == 20 / 60


def test_iris_shift_signs():
    h, v, _ = eye_features(face_points((6, 3)), IMAGE_LEFT_EYE)
    assert h == 6 / 60 and v == 3 / 60


def test_degenerate_eye():
    pts = np.zeros((478, 2))
    assert eye_features(pts, IMAGE_LEFT_EYE) is None


def test_head_pose_identity():
    fx, fy, roll, tx, ty, tz = head_pose(np.eye(4))
    assert (fx, fy, roll) == (0.0, 0.0, 0.0)


def test_build_features_layout_and_blink():
    obs = build_features(face_points((6, 0)), {"eyeBlinkLeft": 0.9, "eyeBlinkRight": 0.8, "eyeLookInLeft": 0.4}, (0.1, 0.2, 0, 1, 2, -50))
    assert obs.features.shape == (N_FEATURES,)
    assert obs.blink
    f = dict(zip(FEATURE_NAMES, obs.features, strict=True))
    assert f["gaze_h"] == 0.1 and f["eyeLookInLeft"] == 0.4 and f["head_tz"] == -50
    assert not build_features(face_points(), {}, (0,) * 6).blink
