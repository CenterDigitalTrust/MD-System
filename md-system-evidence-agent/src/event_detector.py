"""
Minimal event detector.

This stands in for the real AI/CV model (motion/person/vehicle/tamper
detection via TensorRT/DeepStream, per the pilot guide section 4 & 13). It
uses OpenCV background subtraction so the golden-path pipeline is fully
testable on a laptop webcam or a sample video with no GPU and no model
weights. Swap `MotionEventDetector.check()` for a real model call later —
everything downstream (evidence package, hashing, batching, anchoring)
does not need to change.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional, Tuple

import cv2
import numpy as np

from .evidence import QualityMetrics


@dataclass
class DetectedEvent:
    event_type: str
    confidence: float
    clip_frames: List[np.ndarray]
    fps: float
    pre_event_buffer_s: float
    post_event_buffer_s: float
    quality_metrics: QualityMetrics


class MotionEventDetector:
    def __init__(
        self,
        fps: float,
        min_contour_area: int = 1500,
        cooldown_seconds: float = 3.0,
        pre_buffer_frames: int = 15,
        post_buffer_frames: int = 15,
    ):
        self.fps = fps
        self.min_contour_area = min_contour_area
        self.cooldown_seconds = cooldown_seconds
        self.pre_buffer_frames = pre_buffer_frames
        self.post_buffer_frames = post_buffer_frames

        self._bg_sub = cv2.createBackgroundSubtractorMOG2(history=200, varThreshold=32, detectShadows=False)
        self._ring: Deque[np.ndarray] = deque(maxlen=pre_buffer_frames)
        self._last_event_at = 0.0
        self._dropped_frames = 0

    @staticmethod
    def _quality(frame: np.ndarray) -> Tuple[float, float]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        brightness = float(gray.mean())
        return sharpness, brightness

    def check(self, frame: np.ndarray) -> Optional[DetectedEvent]:
        """
        Feed one frame at a time. Returns a DetectedEvent (with pre+post
        buffer already attached) once a motion event has fully resolved,
        otherwise None.
        """
        self._ring.append(frame)

        mask = self._bg_sub.apply(frame)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        largest = max((cv2.contourArea(c) for c in contours), default=0.0)

        now = time.time()
        if largest < self.min_contour_area:
            return None
        if now - self._last_event_at < self.cooldown_seconds:
            return None

        self._last_event_at = now
        confidence = min(0.99, 0.5 + largest / (self.min_contour_area * 10))
        sharpness, brightness = self._quality(frame)

        # pre-buffer is whatever we already have in the ring; post-buffer
        # is captured by the caller (agent.py) grabbing the next N frames.
        pre_frames = list(self._ring)

        return DetectedEvent(
            event_type="motion",
            confidence=round(confidence, 3),
            clip_frames=pre_frames,  # caller appends post-event frames
            fps=self.fps,
            pre_event_buffer_s=round(len(pre_frames) / self.fps, 2),
            post_event_buffer_s=0.0,  # filled in by caller once post frames are appended
            quality_metrics=QualityMetrics(
                sharpness=round(sharpness, 2),
                brightness=round(brightness, 2),
                dropped_frames=self._dropped_frames,
            ),
        )


def encode_clip(frames: List[np.ndarray], fps: float, out_path: str) -> bytes:
    """Write frames to an mp4 file and return its raw bytes (for hashing/storage)."""
    if not frames:
        raise ValueError("no frames to encode")
    h, w = frames[0].shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(out_path, fourcc, max(fps, 1.0), (w, h))
    for f in frames:
        writer.write(f)
    writer.release()
    with open(out_path, "rb") as f:
        return f.read()
