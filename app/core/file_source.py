import cv2
import numpy as np
import os
from .source import CameraSource


class FileCameraSource(CameraSource):
    """MP4 / video file camera source.

    Supports playing video files (MP4, AVI, etc.) as a camera source,
    feeding frames into the same shared AI event pipeline.
    """

    def __init__(self, source_id: str = "", **kwargs):
        super().__init__(source_id)
        self._video_path = source_id or kwargs.get("video_path", "")
        self._cap = None
        self._frame_count = 0
        self._current_frame = 0

    def open(self) -> bool:
        if not self._video_path:
            return False
        if not os.path.exists(self._video_path):
            return False
        self._cap = cv2.VideoCapture(self._video_path)
        if self._cap.isOpened():
            self._width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self._height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self._frame_count = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self._is_opened = True
            return True
        self._is_opened = False
        return False

    def read_frame(self) -> Optional[Tuple[np.ndarray, int, int]]:
        if not self._is_opened or self._cap is None:
            return None
        ret, frame = self._cap.read()
        if not ret or frame is None:
            # End of video, reset to beginning and return first frame
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = self._cap.read()
            if not ret or frame is None:
                return None
            self._current_frame = 0
        # Ensure BGR format
        if len(frame.shape) == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        elif frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        self._current_frame += 1
        return frame, self._width, self._height

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._is_opened = False