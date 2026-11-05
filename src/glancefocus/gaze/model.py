"""Download and verify the MediaPipe Face Landmarker model (≈3.7 MB, cached)."""

from __future__ import annotations

import hashlib
import logging
import os
import urllib.request
from pathlib import Path

from glancefocus import paths

log = logging.getLogger(__name__)

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
MODEL_SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_model() -> Path:
    path = paths.cache_dir() / "face_landmarker.task"
    if path.exists() and _sha256(path) == MODEL_SHA256:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    log.info("downloading face model from %s", MODEL_URL)
    with urllib.request.urlopen(MODEL_URL, timeout=60) as resp, open(tmp, "wb") as f:
        while chunk := resp.read(1 << 16):
            f.write(chunk)
    digest = _sha256(tmp)
    if digest != MODEL_SHA256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"face model checksum mismatch (got {digest})")
    os.replace(tmp, path)
    return path
