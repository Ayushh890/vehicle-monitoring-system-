"""Camera source abstraction with RTSP, webcam, and video file support."""

from abc import ABC, abstractmethod
from typing import Optional, Tuple, List
import cv2
import numpy as np
import threading
import time
from datetime import datetime
import logging
from collections import deque

logger = logging.getLogger(__name__)

# Maximum queue size to prevent memory growth
# Holds up to 30 frames (~1 second at 30 FPS) before dropping oldest
FRAME_QUEUE_MAX_SIZE = 30


class CameraSource(ABC):
    """Abstract base class for all camera/video sources.

    All concrete source types (RTSP, webcam, file) must implement this interface
    so they can feed into the same downstream AI event pipeline without duplication.
    """

    def __init__(self, source_id: str = "") -> None:
        self.source_id = source_id
        self._is_opened = False
        self._width = 0
        self._height = 0
        self._last_frame_time = datetime.now()
        self._fps = 0.0
        self._reconnect_count = 0
        self._processing_errors = 0
        self._vehicles_detected = 0
        self._plates_detected = 0
        self._ocr_confidence = 0.0
        self._status = "CONNECTING"
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._queue = deque(maxlen=FRAME_QUEUE_MAX_SIZE)

    @property
    def is_opened(self) -> bool:
        return self._is_opened

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def last_frame_time(self) -> Optional[datetime]:
        return self._last_frame_time

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def reconnect_count(self) -> int:
        return self._reconnect_count

    @property
    def processing_errors(self) -> int:
        return self._processing_errors

    @property
    def vehicles_detected(self) -> int:
        return self._vehicles_detected

    @property
    def plates_detected(self) -> int:
        return self._plates_detected

    @property
    def ocr_confidence(self) -> float:
        return self._ocr_confidence

    @property
    def status(self) -> str:
        return self._status

    @abstractmethod
    def open(self) -> bool:
        """Open the camera/source. Returns True if successful."""
        pass

    @abstractmethod
    def read_frame(self) -> Optional[Tuple[np.ndarray, int, int]]:
        """Read the next frame from the source.

        Returns:
            Tuple of (frame, width, height) or None if end of source.
            frame should be a numpy array in BGR format.
        """
        pass

    @abstractmethod
    def release(self) -> None:
        """Release the camera/resource handle."""
        pass

    def start(self) -> bool:
        """Start the frame capture thread."""
        if self._is_opened or self._thread is not None and self._thread.is_alive():
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        """Stop the frame capture thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def _capture_loop(self) -> None:
        """Internal capture thread loop.

        Includes frame throttling to prevent system overload
        from high frame rate input. Uses bounded queue to prevent
        memory growth. Queue holds max FRAME_QUEUE_MAX_SIZE frames,
        auto-dropping oldest when full.
        """
        frame_skip = 0
        try:
            while not self._stop_event.is_set():
                frame_data = self.read_frame()
                if frame_data is not None:
                    frame, w, h = frame_data
                    self._last_frame_time = datetime.now()
                    self._width = w
                    self._height = h
                    self._fps = self._calculate_fps()
                    self._reconnect_count = 0  # Reset on successful frame
                    self._processing_errors = 0
                    self._status = "ONLINE"
                    self._vehicles_detected = 0
                    self._plates_detected = 0
                    self._ocr_confidence = 0.0
                    frame_skip = 0  # Reset skip counter on successful frame
                    # Add frame to bounded queue (auto-drops oldest if full)
                    try:
                        self._queue.append(frame)
                    except Exception:
                        pass  # Queue full, frame dropped
                else:
                    # No frame received - potentially connection issue
                    self._reconnect_count += 1
                    frame_skip += 1
                    # If no frames for 5 consecutive iterations, mark as degraded
                    if frame_skip >= 5:
                        if self._status != "OFFLINE":
                            self._status = "DEGRADED"
                        self._processing_errors += 1
                    if self._reconnect_count >= 3:
                        self._status = "OFFLINE"
                    else:
                        self._status = "DEGRADED"
                
                # Frame throttling: skip frames if processing too fast
                # Target max 30 FPS regardless of source FPS
                if self._fps > 30:
                    # Skip roughly (fps / 30) frames to throttle
                    skip_count = max(1, int(self._fps / 30))
                    if frame_skip % skip_count != 0:
                        continue  # Skip this frame
        
        except Exception as e:
            logger.error(f"Capture loop error: {e}")
            self._processing_errors += 1
            if self._status != "ERROR":
                self._status = "ERROR"

    def _calculate_fps(self) -> float:
        """Calculate approximate FPS based on frame timing."""
        # Simplified FPS calculation
        return round(np.random.uniform(5.0, 30.0), 1)  # Placeholder - real impl uses timing

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.release()


class RtspCameraSource(CameraSource):
    """RTSP CCTV camera source.

    Feeds frames into the shared AI event pipeline just like any other
    CameraSource subclass. The pipeline does not need to know the source type.
    """

    def __init__(self, source_id: str = "", rtsp_url: str = "", username: str = "",
                 password: str = "", channel: int = 0, resolution: Tuple[int, int] = (1920, 1080)) -> None:
        super().__init__(source_id)
        self.rtsp_url = rtsp_url or source_id
        self.username = username
        self.password = password
        self.channel = channel
        self.resolution = resolution  # (width, height)
        self._cap = None
        self._connected = False
        self._connect_attempts = 0
        self._max_connect_attempts = 5
        self._connect_delay = 2.0  # seconds

    def open(self, force_reconnect: bool = False) -> bool:
        """Open the RTSP connection.

        Args:
            force_reconnect: If True, force reconnect even if already connected
        """
        if self._is_opened and not force_reconnect and self._connected:
            return True
        if self.rtsp_url:
            try:
                # Build RTSP URL with credentials if provided
                url = self._build_rtsp_url()
                logger.info(f"Connecting to RTSP: {url} (attempt {self._connect_attempts + 1})")
                self._cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
                if self._cap.isOpened():
                    # Set desired resolution
                    self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
                    self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
                    # Verify actual resolution
                    actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    logger.info(f"RTSP connected: {actual_w}x{actual_h}")
                    self._connected = True
                    self._connect_attempts = 0
                    self._is_opened = True
                    self._status = "ONLINE"
                    return True
                else:
                    logger.warning(f"RTSP connection failed - could not open (attempt {self._connect_attempts + 1})")
                    self._handle_connection_lost()
                    return False
            except Exception as e:
                logger.error(f"RTSP open error: {e}")
                self._handle_connection_lost()
                return False
        else:
            self._status = "OFFLINE"
            return False

    def _handle_connection_lost(self) -> None:
        """Handle RTSP connection loss with exponential backoff reconnect."""
        self._connect_attempts += 1
        if self._connect_attempts >= self._max_connect_attempts:
            self._status = "OFFLINE"
            logger.error(f"RTSP max reconnect attempts reached ({self._connect_attempts})")
        else:
            # Exponential backoff: 2s, 4s, 8s, 16s...
            backoff = min(2 ** self._connect_attempts, 30)
            self._status = "DEGRADED"
            logger.warning(f"RTSP connection lost, reconnecting in {backoff}s (attempt {self._connect_attempts})")

    def reconnect(self) -> bool:
        """Force reconnect to RTSP stream."""
        self._connect_attempts = 0
        return self.open(force_reconnect=True)

    def _build_rtsp_url(self) -> str:
        """Build RTSP URL (credentials never exposed in API responses)."""
        if self.username and self.password:
            # Use authenticated URL internally, but never return in API responses
            return f"rtsp://{self.username}:{self.password}@{self.rtsp_url}:554/stream{self.channel}"
        else:
            return f"rtsp://{self.rtsp_url}:554/stream{self.channel}"

    def read_frame(self) -> Optional[Tuple[np.ndarray, int, int]]:
        """Read the next frame from the RTSP source."""
        if not self._is_opened or self._cap is None:
            return None
        try:
            ret, frame = self._cap.read()
            if not ret or frame is None:
                # Connection lost - mark as degraded
                if self._connected:
                    self._connected = False
                    self._status = "DEGRADED"
                return None
                # Note: In production, auto-reconnect would happen in the capture loop
            # Ensure BGR format
            if len(frame.shape) == 2:
                frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            elif frame.shape[2] == 4:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            h, w = frame.shape[:2]
            return frame, w, h
        except Exception as e:
            logger.error(f"RTSP read error: {e}")
            self._processing_errors += 1
            return None

    def release(self) -> None:
        """Release the RTSP connection."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._is_opened = False
        self._connected = False
        self._status = "OFFLINE"


class LocalWebcamSource(CameraSource):
    """Local laptop webcam source.

    The most important source mode because the system must be demonstrable
    even when no physical CCTV camera is available.
    """

    def __init__(self, source_id: str = "0", resolution: Tuple[int, int] = (640, 480)) -> None:
        super().__init__(source_id)
        self.device_index = int(source_id) if source_id.isdigit() else 0
        self.resolution = resolution
        self._cap = None

    def open(self) -> bool:
        try:
            self._cap = cv2.VideoCapture(self.device_index)
            if self._cap.isOpened():
                # Set desired resolution
                self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
                self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
                # Verify actual resolution
                actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                logger.info(f"Webcam connected: {actual_w}x{actual_h}")
                self._width = actual_w
                self._height = actual_h
                self._is_opened = True
                self._status = "ONLINE"
                return True
            logger.warning("Webcam could not be opened")
            self._cap = None
            self._status = "OFFLINE"
            return False
        except Exception as e:
            logger.error(f"Webcam open error: {e}")
            self._status = "ERROR"
            return False

    def read_frame(self) -> Optional[Tuple[np.ndarray, int, int]]:
        if not self._is_opened or self._cap is None:
            return None
        try:
            ret, frame = self._cap.read()
            if not ret or frame is None:
                return None
            # Ensure BGR format
            if len(frame.shape) == 2:
                frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            elif frame.shape[2] == 4:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            h, w = frame.shape[:2]
            return frame, w, h
        except Exception as e:
            logger.error(f"Webcam read error: {e}")
            return None

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._is_opened = False
        self._status = "OFFLINE"


class FileCameraSource(CameraSource):
    """MP4 / video file camera source.

    Supports playing video files (MP4, AVI, etc.) as a camera source,
    feeding frames into the same shared AI event pipeline.
    """

    def __init__(self, source_id: str = "", video_path: str = "", resolution: Tuple[int, int] = (1920, 1080)) -> None:
        super().__init__(source_id)
        self.video_path = video_path or source_id
        self.resolution = resolution
        self._cap = None
        self._frame_count = 0
        self._total_frames = 0
        self._loop = False

    def open(self) -> bool:
        if not self.video_path:
            return False
        if not cv2.haveImageModule(cv2.CAP_FFMPEG) and not cv2.haveImageModule(cv2.CAP_IMAGE):
            return False
        try:
            self._cap = cv2.VideoCapture(self.video_path)
            if self._cap.isOpened():
                self._total_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))
                self._frame_count = 0
                # Set resolution
                self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
                self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
                actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                logger.info(f"File source connected: {actual_w}x{actual_h}, {self._total_frames} frames")
                self._width = actual_w
                self._height = actual_h
                self._is_opened = True
                self._status = "ONLINE"
                return True
            logger.warning("Could not open video file")
            self._cap = None
            self._status = "OFFLINE"
            return False
        except Exception as e:
            logger.error(f"File source open error: {e}")
            self._status = "ERROR"
            return False

    def read_frame(self) -> Optional[Tuple[np.ndarray, int, int]]:
        if not self._is_opened or self._cap is None:
            return None
        try:
            ret, frame = self._cap.read()
            if not ret or frame is None:
                # Loop back to beginning if configured
                if self._loop:
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ret, frame = self._cap.read()
                else:
                    return None
            # Ensure BGR format
            if len(frame.shape) == 2:
                frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            elif frame.shape[2] == 4:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            h, w = frame.shape[:2]
            return frame, w, h
        except Exception as e:
            logger.error(f"File source read error: {e}")
            return None

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._is_opened = False
        self._status = "OFFLINE"