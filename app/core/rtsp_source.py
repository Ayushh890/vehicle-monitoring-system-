import cv2
import numpy as np
from .source import CameraSource


class RtspCameraSource(CameraSource):
    """RTSP CCTV camera source.

    Feeds frames into the shared AI event pipeline just like any other
    CameraSource subclass. The pipeline does not need to know the source type.
    """

    def __init__(self, source_id: str = "", rtsp_url: str = "") -> None:
        super().__init__(source_id)
        self.rtsp_url = rtsp_url or source_id
        self._cap = None

    def open(self) -> bool:
        if not self.rtsp_url:
            return False
        self._cap = cv2.VideoCapture(self.rtsp_url)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if self._cap.isOpened():
            self._width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self._height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
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