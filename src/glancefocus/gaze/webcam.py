"""Background webcam + MediaPipe Face Landmarker loop producing GazeSamples."""

from __future__ import annotations

import logging
import sys
import threading
import time
from dataclasses import dataclass

import numpy as np

from glancefocus.gaze.features import FaceObservation, from_landmarker_result
from glancefocus.gaze.model import ensure_model

log = logging.getLogger(__name__)


class CameraError(RuntimeError):
    pass


@dataclass
class GazeSample:
    t: float  # time.monotonic() when the frame was captured
    observation: FaceObservation | None  # None: no face found

    @property
    def face(self) -> bool:
        return self.observation is not None

    @property
    def usable(self) -> bool:
        return self.observation is not None and not self.observation.blink


def load_mediapipe():
    """Import MediaPipe's vision tasks without its optional audio stack.

    `mediapipe.tasks.python` imports `sounddevice` when available. On PipeWire
    systems initialising PortAudio this way can get the whole process SIGKILLed,
    and glancefocus never needs audio, so make that import fail fast instead.
    """
    if "sounddevice" not in sys.modules:
        sys.modules["sounddevice"] = None  # type: ignore[assignment]
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision

    return mp, vision, BaseOptions


def open_camera(spec: str, width: int, height: int, fps: int):
    import cv2

    source: int | str = int(spec) if str(spec).isdigit() else spec
    if sys.platform.startswith("linux"):
        cap = cv2.VideoCapture(source, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    elif sys.platform == "win32":
        cap = cv2.VideoCapture(source, cv2.CAP_DSHOW)
    else:
        cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise CameraError(f"cannot open camera {spec!r}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)
    ok, _ = cap.read()
    if not ok:
        cap.release()
        raise CameraError(f"camera {spec!r} opened but returned no frames (is another app using it?)")
    return cap


class WebcamTracker:
    def __init__(self, camera: str = "0", width: int = 640, height: int = 480, fps: int = 30, keep_frame: bool = False):
        self.camera, self.width, self.height, self.fps_request = camera, width, height, fps
        self.keep_frame = keep_frame
        self._lock = threading.Lock()
        self._sample: GazeSample | None = None
        self._frame: np.ndarray | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None
        self.fps = 0.0

    def start(self) -> None:
        mp, vision, BaseOptions = load_mediapipe()
        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(ensure_model())),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=True,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)
        self._mp = mp
        self._cap = open_camera(self.camera, self.width, self.height, self.fps_request)
        self._thread = threading.Thread(target=self._loop, name="glancefocus-camera", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        import cv2

        t0 = time.monotonic()
        last_ms = -1
        frames, fps_t = 0, time.monotonic()
        try:
            while not self._stop.is_set():
                ok, frame = self._cap.read()
                now = time.monotonic()
                if not ok:
                    time.sleep(0.05)
                    continue
                ms = max(int((now - t0) * 1000), last_ms + 1)  # must strictly increase
                last_ms = ms
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                result = self._landmarker.detect_for_video(self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb), ms)
                obs = from_landmarker_result(result, frame.shape[1], frame.shape[0])
                with self._lock:
                    self._sample = GazeSample(now, obs)
                    if self.keep_frame:
                        self._frame = frame
                frames += 1
                if now - fps_t >= 1.0:
                    self.fps = frames / (now - fps_t)
                    frames, fps_t = 0, now
        except BaseException as e:  # noqa: BLE001 - surfaced via latest()
            self._error = e

    def latest(self) -> GazeSample | None:
        if self._error:
            raise CameraError(f"camera thread died: {self._error}") from self._error
        with self._lock:
            return self._sample

    def latest_frame(self) -> np.ndarray | None:
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if getattr(self, "_cap", None) is not None:
            self._cap.release()
        if getattr(self, "_landmarker", None) is not None:
            self._landmarker.close()

    def __enter__(self) -> WebcamTracker:
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
