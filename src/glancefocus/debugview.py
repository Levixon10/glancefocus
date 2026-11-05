"""Live debug window: a map of your monitors and windows with the gaze point on it."""

from __future__ import annotations

import cv2
import numpy as np

from glancefocus.geometry import Monitor, Rect, Window
from glancefocus.policy import FocusPolicy

TITLE = "glancefocus debug"
BG = (28, 24, 22)
MON = (90, 90, 90)
WIN = (70, 62, 58)
FOCUSED = (200, 140, 60)
CANDIDATE = (60, 210, 240)
GAZE = (80, 80, 255)
TEXT = (225, 225, 225)
DIM = (150, 150, 150)


class DebugView:
    def __init__(self, width: int = 1000, cam_w: int = 320):
        self.width, self.cam_w = width, cam_w
        self.cam_h = cam_w * 3 // 4
        cv2.namedWindow(TITLE, cv2.WINDOW_AUTOSIZE)

    def close(self) -> None:
        cv2.destroyWindow(TITLE)
        cv2.waitKey(1)

    def draw(
        self,
        monitors: list[Monitor],
        windows: list[Window],
        point: tuple[float, float] | None,
        raw: tuple[float, float] | None,
        policy: FocusPolicy,
        frame: np.ndarray | None,
        eye_points: np.ndarray | None,
        status: list[str],
    ) -> int:
        pad = 16
        if monitors:
            box = monitors[0].rect
            for m in monitors[1:]:
                box = box.union(m.rect)
        else:
            box = Rect(0, 0, 1920, 1080)
        scale = (self.width - 2 * pad) / max(box.w, 1)
        map_h = int(box.h * scale)
        img = np.empty((map_h + 2 * pad + self.cam_h + pad, self.width, 3), np.uint8)
        img[:] = BG

        def tr(x: float, y: float) -> tuple[int, int]:
            return int(pad + (x - box.x) * scale), int(pad + (y - box.y) * scale)

        def rect(r: Rect, color, thickness=1):
            cv2.rectangle(img, tr(r.x, r.y), tr(r.right, r.bottom), color, thickness, cv2.LINE_AA)

        for m in monitors:
            rect(m.rect, MON, 2)
            x, y = tr(m.rect.x, m.rect.y)
            cv2.putText(img, m.name, (x + 6, y + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, DIM, 1, cv2.LINE_AA)

        res = policy.last_resolution
        for w in sorted(windows, key=lambda w: -w.z):
            p1, p2 = tr(w.rect.x, w.rect.y), tr(w.rect.right, w.rect.bottom)
            cv2.rectangle(img, p1, p2, WIN, -1)
            color = FOCUSED if w.focused else (110, 110, 110)
            cv2.rectangle(img, p1, p2, color, 2 if w.focused else 1, cv2.LINE_AA)
            rect(w.rect.inset(policy.margin_for(w)), (85, 78, 72))
            label = (w.app or w.title)[:28]
            cv2.putText(img, label, (p1[0] + 6, p1[1] + 34), cv2.FONT_HERSHEY_SIMPLEX, 0.42, TEXT, 1, cv2.LINE_AA)
        if res.window is not None:
            rect(res.window.rect, CANDIDATE, 3 if res.kind == "window" else 1)

        if raw is not None:
            cv2.circle(img, tr(*raw), 3, DIM, -1, cv2.LINE_AA)
        if point is not None:
            c = tr(*point)
            acc = policy.accuracy_for(res.monitor.name) if res.monitor else policy.accuracy_for("")
            cv2.circle(img, c, max(4, int(acc * scale)), (70, 70, 160), 1, cv2.LINE_AA)
            cv2.circle(img, c, 7, GAZE, -1, cv2.LINE_AA)
            if policy.dwell_progress > 0:
                cv2.ellipse(img, c, (13, 13), -90, 0, 360 * policy.dwell_progress, CANDIDATE, 2, cv2.LINE_AA)

        # Camera thumbnail with eye landmarks.
        top = map_h + 2 * pad
        if frame is not None:
            fh, fw = frame.shape[:2]
            thumb = cv2.resize(frame, (self.cam_w, self.cam_h))
            if eye_points is not None:
                sx, sy = self.cam_w / fw, self.cam_h / fh
                for x, y in eye_points:
                    cv2.circle(thumb, (int(x * sx), int(y * sy)), 2, (0, 255, 0), -1)
            img[top : top + self.cam_h, pad : pad + self.cam_w] = thumb
        for i, line in enumerate(status):
            cv2.putText(img, line, (2 * pad + self.cam_w, top + 20 + 22 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.52, TEXT, 1, cv2.LINE_AA)

        cv2.imshow(TITLE, img)
        key = cv2.waitKey(1) & 0xFF
        try:
            if cv2.getWindowProperty(TITLE, cv2.WND_PROP_VISIBLE) < 1:
                return 27  # window was closed: treat like Esc
        except cv2.error:
            return 27
        return key
