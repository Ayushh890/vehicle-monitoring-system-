import numpy as np
from typing import Optional, List, Dict, Any, Tuple


class Detection:
    """Represents a detected object with bounding box and class info."""
    def __init__(self, class_id: int, class_name: str, confidence: float,
                 bbox: Tuple[float, float, float, float]) -> None:
        self.class_id = class_id
        self.class_name = class_name
        self.confidence = confidence
        self.bbox = bbox  # (x1, y1, x2, y2) in pixel coordinates


class TrackedObject:
    """Represents a tracked object across frames."""
    def __init__(self, obj_id: int, detection: Detection, center: Tuple[float, float]) -> None:
        self.obj_id = obj_id
        self.detection = detection
        self.center = center  # (cx, cy)
        self.history: List[Tuple[float, float]] = [center]


class AIEvent:
    """Base class for AI-generated events."""
    def __init__(self, event_type: str, severity: float, description: str, metadata: Dict[str, Any] = None) -> None:
        self.event_type = event_type
        self.severity = severity
        self.description = description
        self.metadata = metadata or {}


class AnomalyEvent(AIEvent):
    """Event generated when an anomalous activity is detected."""
    def __init__(self, class_name: str, severity: float, region: Tuple[float, float, float, float], metadata: Dict[str, Any] = None) -> None:
        super().__init__("anomaly", severity, f"Anomalous activity: {class_name}", metadata)
        self.class_name = class_name
        self.region = region


class CongestionEvent(AIEvent):
    """Event generated when crowd congestion is detected."""
    def __init__(self, density: float, region: Tuple[float, float, float, float], metadata: Dict[str, Any] = None) -> None:
        super().__init__("congestion", density, f"Crowd congestion detected (density: {density:.2f})", metadata)
        self.density = density


class PipelineResult:
    """Result from running the AI pipeline on a single frame."""
    def __init__(self, frame: np.ndarray, detections: List[Detection] = None,
                 tracked_objects: List[TrackedObject] = None,
                 events: List[AIEvent] = None) -> None:
        self.frame = frame
        self.detections = detections or []
        self.tracked_objects = tracked_objects or []
        self.events = events or []


class AIEventPipeline:
    """Shared AI event pipeline that processes frames from any CameraSource.

    This pipeline is source-agnostic - it doesn't care whether the frame
    comes from RTSP, webcam, or file. All three source types feed into this
    same pipeline.
    """

    def __init__(self, confidence_threshold: float = 0.5, nms_threshold: float = 0.4) -> None:
        self.confidence_threshold = confidence_threshold
        self.nms_threshold = nms_threshold
        # Placeholder detectors - in a real implementation these would be loaded models
        self.detector_names = ["yolo", "ssd", "faster-rcnn"]
        self._initialized = False

    def _preprocess(self, frame: np.ndarray) -> np.ndarray:
        """Preprocess frame for the neural network."""
        # Resize, normalize, etc.
        # For now, just make a copy
        return frame

    def _detect_objects(self, frame: np.ndarray) -> List[Detection]:
        """Run object detection on the frame.

        In a real implementation, this would call a DNN model.
        For now, return dummy detections.
        """
        # TODO: Replace with actual model inference
        h, w = frame.shape[:2]
        # Dummy detections for testing
        detections = [
            Detection(
                class_id=0, class_name="person", confidence=0.85,
                bbox=(100, 100, 300, 500)
            ),
            Detection(
                class_id=1, class_name="car", confidence=0.72,
                bbox=(200, 200, 400, 450)
            ),
        ]
        return detections

    def _track_objects(self, detections: List[Detection], frame: np.ndarray) -> List[TrackedObject]:
        """Track objects across frames.

        In a real implementation, this would use a tracker (DeepSORT, etc.).
        For now, return dummy tracked objects.
        """
        tracked = []
        for i, det in enumerate(detections):
            h, w = frame.shape[:2]
            cx = (det.bbox[0] + det.bbox[2]) / 2
            cy = (det.bbox[1] + det.bbox[3]) / 2
            tracked.append(TrackedObject(obj_id=i, detection=det, center=(cx, cy)))
        return tracked

    def _generate_events(self, tracked_objects: List[TrackedObject],
                        frame_shape: Tuple[int, int]) -> List[AIEvent]:
        """Generate AI events from tracked objects.

        Produces anomaly, congestion, and other events.
        """
        events = []
        h, w = frame_shape[:2]

        # Check for anomaly events (e.g., person moving in restricted area)
        for obj in tracked_objects:
            if obj.detection.class_name == "person" and obj.detection.confidence > 0.7:
                # Simple anomaly: person detected in upper region
                x1, y1, x2, y2 = obj.detection.bbox
                if y1 < h / 2:  # Person in top half of frame
                    events.append(AnomalyEvent(
                        class_name="person",
                        severity=0.6,
                        region=obj.detection.bbox,
                        metadata={"obj_id": obj.obj_id}
                    ))

        # Check for congestion events
        person_count = sum(1 for obj in tracked_objects if obj.detection.class_name == "person")
        if person_count > 5:
            events.append(CongestionEvent(
                density=person_count / max(h, 1),
                region=(0, 0, w, h),
                metadata={"person_count": person_count}
            ))

        return events

    def run(self, frame: np.ndarray) -> PipelineResult:
        """Run the full AI pipeline on a single frame.

        This is the common interface that all CameraSource types feed into.
        The pipeline is completely source-agnostic.
        """
        # Preprocess
        preprocessed = self._preprocess(frame)

        # Detect objects
        detections = self._detect_objects(preprocessed)

        # Track objects
        tracked = self._track_objects(detections, preprocessed)

        # Generate events
        events = self._generate_events(tracked, frame.shape)

        return PipelineResult(
            frame=frame,
            detections=detections,
            tracked_objects=tracked,
            events=events
        )