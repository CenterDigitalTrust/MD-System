"""
Frame source abstraction. Works with:
  - an integer webcam index (e.g. 0)
  - a local video file path (for testing without hardware)
  - an RTSP/ONVIF URL string ("rtsp://...")

Used for the "golden path" stand: 1 camera -> Jetson/laptop -> events.
"""

from __future__ import annotations

import time
from typing import Iterator, Tuple, Union

import cv2
import numpy as np

Frame = Tuple[np.ndarray, float]  # (frame, unix_timestamp)


class FrameSource:
    def __init__(self, source: Union[int, str], reconnect_delay_s: float = 2.0):
        self.source = source
        self.reconnect_delay_s = reconnect_delay_s
        self._cap: cv2.VideoCapture | None = None
        self._open()

    def _open(self) -> None:
        self._cap = cv2.VideoCapture(self.source)
        if not self._cap.isOpened():
            raise RuntimeError(f"could not open video source: {self.source!r}")

    @property
    def fps(self) -> float:
        assert self._cap is not None
        fps = self._cap.get(cv2.CAP_PROP_FPS)
        return fps if fps and fps > 1 else 15.0

    def frames(self) -> Iterator[Frame]:
        """
        Yields (frame, timestamp) forever. For RTSP sources, attempts a
        reconnect on read failure instead of raising — mirrors the
        STEALTH/offline-resilience behaviour described for MD-CAM.
        Video-file sources stop (StopIteration) at end of file.
        """
        is_file = isinstance(self.source, str) and not self.source.startswith(("rtsp://", "http://", "https://"))
        while True:
            assert self._cap is not None
            ok, frame = self._cap.read()
            if not ok:
                if is_file:
                    return  # end of file, no more frames
                # transient network source failure: try to reconnect
                self._cap.release()
                time.sleep(self.reconnect_delay_s)
                try:
                    self._open()
                except RuntimeError:
                    continue
                continue
            yield frame, time.time()

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
