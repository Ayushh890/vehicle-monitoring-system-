import cv2
import numpy as np
from .source import CameraSource


class LocalWebcamSource(CameraSource):
    """Local laptop webcam source.

    The most important source mode because the system must be demonstrable
    even when no physical CCTV camera is available.
    """

    def __init__(self, source_id: str = "0", **kwargs):
        super().__init__(source_id)
        self.device_index = int(source_id) if source_id.isdigit() else 0
        self._cap = None
        self._width = 640
        self._height = 480

    def open(self) -> bool:
        self._cap = cv2.VideoCapture(self.device_index)
        if self._cap.isOpened():
            self._width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self._height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            # Reduce buffer size to minimize latency
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self._is_opened = True
            return True
        self._is_opened = False
        return False

    def read_frame(self) -> Optional[Tuple[np.ndarray, int, int]]:
        if not self._is_opened or self._cap is None:
            return None
        ret, frame = self._cap.read()
        if not ret or frame is None:
            return None
        # Ensure BGR format
        if len(frame.shape) == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        elif frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        return frame, self._width, self._height

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._is_opened = False