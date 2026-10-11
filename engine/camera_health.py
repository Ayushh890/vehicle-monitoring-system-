"""Camera health monitoring service.

Tracks per-camera health metrics and detects quality problems
such as stream stops, FPS drops, latency issues, darkness, blurriness,
and OCR confidence degradation.
"""

import numpy as np
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from backend.app.models.camera_health import CameraHealthRecord
from backend.app.models import Camera


class CameraHealthMonitor:
    """Monitors camera health and detects quality problems."""

    # Health status thresholds
    FPS_THRESHOLD_LOW = 5.0  # FPS below this is considered low
    FPS_THRESHOLD_DEGRADED = 10.0  # FPS below this is degraded
    LATENCY_THRESHOLD_WARN = 200.0  # ms, warn above this
    LATENCY_THRESHOLD_ERROR = 500.0  # ms, error above this
    DARK_THRESHOLD = 0.3  # Average pixel value below this (0-1) is dark
    BLUR_THRESHOLD = 100.0  # Laplacian variance below this is blurry
    OCR_CONFIDENCE_THRESHOLD = 0.6  # Below this is degraded
    OCR_CONFIDENCE_DEGRADED = 0.4  # Severely degraded

    def __init__(self, db_session, camera: Camera):
        self.db_session = db_session
        self.camera = camera
        self.last_health_check = datetime.utcnow()

    def update_health(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Update camera health with new metrics and return health status.

        Args:
            metrics: Dict with keys like:
                - fps: float
                - latency_ms: float
                - vehicles_detected: int
                - plates_detected: int
                - ocr_confidence: float (0-1)
                - is_dark: bool
                - is_blurry: bool
                - reconnect_count: int (change since last update)
                - processing_errors: int (new errors since last update)

        Returns:
            Dict with health status and detected issues
        """
        now = datetime.utcnow()
        last_frame_time = metrics.get("last_frame_time")
        fps = metrics.get("fps")
        latency_ms = metrics.get("latency_ms")
        vehicles_detected = metrics.get("vehicles_detected", 0)
        plates_detected = metrics.get("plates_detected", 0)
        ocr_confidence = metrics.get("ocr_confidence")
        is_dark = metrics.get("is_dark", False)
        is_blurry = metrics.get("is_blurry", False)
        reconnect_count = metrics.get("reconnect_count", 0)
        processing_errors = metrics.get("processing_errors", 0)

        # Calculate time since last frame
        time_since_last = None
        if last_frame_time:
            if isinstance(last_frame_time, str):
                last_frame_dt = datetime.fromisoformat(last_frame_time)
            else:
                last_frame_dt = last_frame_time
            time_since_last = (now - last_frame_dt).total_seconds()

        # Determine health status
        status = self._determine_status(
            fps, latency_ms, ocr_confidence, is_dark, is_blurry,
            time_since_last, reconnect_count, processing_errors
        )

        # Create health record
        health_record = CameraHealthRecord(
            camera_id=self.camera.id,
            status=status,
            last_frame_time=last_frame_time,
            fps=fps,
            latency_ms=latency_ms,
            reconnect_count=reconnect_count,
            processing_errors=processing_errors,
            vehicles_detected=vehicles_detected,
            plates_detected=plates_detected,
            ocr_confidence_trend=ocr_confidence,
            is_dark=is_dark,
            is_blurry=is_blurry,
        )

        self.db_session.add(health_record)
        self.db_session.commit()

        # Detect specific issues
        issues = self._detect_issues(
            fps, latency_ms, ocr_confidence, is_dark, is_blurry,
            time_since_last, reconnect_count, processing_errors
        )

        return {
            "status": status,
            "issues": issues,
            "metrics": {
                "fps": fps,
                "latency_ms": latency_ms,
                "vehicles_detected": vehicles_detected,
                "plates_detected": plates_detected,
                "ocr_confidence": ocr_confidence,
                "is_dark": is_dark,
                "is_blurry": is_blurry,
                "time_since_last_frame_s": round(time_since_last, 1) if time_since_last else None,
            },
            "recorded_at": health_record.recorded_at.isoformat(),
        }

    def _determine_status(
        self, fps, latency_ms, ocr_confidence, is_dark, is_blurry,
        time_since_last, reconnect_count, processing_errors
    ) -> str:
        """Determine the camera health status.

        Status hierarchy (from best to worst):
        ONLINE > CONNECTING > DEGRADED > OFFLINE > ERROR
        """
        # Check for severe issues first
        if processing_errors > 10 or (time_since_last is not None and time_since_last > 300):
            # No frame for 5+ seconds or many errors = ERROR
            return "ERROR"
        if time_since_last is not None and time_since_last > 60:
            # No frame for 1+ minute = OFFLINE
            return "OFFLINE"
        if is_dark or is_blurry:
            # Quality issues = DEGRADED
            return "DEGRADED"
        if fps is not None and fps < self.FPS_THRESHOLD_LOW:
            # Very low FPS = DEGRADED
            return "DEGRADED"
        if fps is not None and fps < self.FPS_THRESHOLD_DEGRADED:
            # Low FPS = CONNECTING or DEGRADED
            return "CONNECTING" if reconnect_count > 0 else "DEGRADED"
        if ocr_confidence is not None and ocr_confidence < self.OCR_CONFIDENCE_THRESHOLD:
            # Low OCR confidence = DEGRADED
            return "DEGRADED"

        # Default: ONLINE
        return "ONLINE"

    def _detect_issues(
        self, fps, latency_ms, ocr_confidence, is_dark, is_blurry,
        time_since_last, reconnect_count, processing_errors
    ) -> List[Dict[str, Any]]:
        """Detect specific quality problems and return list of issue dicts."""
        issues = []

        # Stream stopped: no frame for 5+ seconds
        if time_since_last is not None and time_since_last > 300:
            issues.append({
                "type": "stream_stopped",
                "description": "No frame received for over 5 minutes",
                "severity": "high",
                "metric_value": time_since_last,
                "threshold": 300,
            })

        # FPS suddenly dropped
        if fps is not None and fps < self.FPS_THRESHOLD_LOW:
            issues.append({
                "type": "fps_dropped",
                "description": f"FPS {fps:.1f} below threshold {self.FPS_THRESHOLD_LOW:.1f}",
                "severity": "medium" if fps >= self.FPS_THRESHOLD_DEGRADED else "high",
                "metric_value": fps,
                "threshold": self.FPS_THRESHOLD_LOW,
            })

        # Excessive frame latency
        if latency_ms is not None and latency_ms > self.LATENCY_THRESHOLD_ERROR:
            issues.append({
                "type": "excessive_latency",
                "description": f"Latency {latency_ms:.0f}ms exceeds error threshold {self.LATENCY_THRESHOLD_ERROR:.0f}ms",
                "severity": "high",
                "metric_value": latency_ms,
                "threshold": self.LATENCY_THRESHOLD_ERROR,
            })
        elif latency_ms is not None and latency_ms > self.LATENCY_THRESHOLD_WARN:
            issues.append({
                "type": "high_latency",
                "description": f"Latency {latency_ms:.0f}ms warning threshold {self.LATENCY_THRESHOLD_WARN:.0f}ms",
                "severity": "medium",
                "metric_value": latency_ms,
                "threshold": self.LATENCY_THRESHOLD_WARN,
            })

        # Image too dark
        if is_dark:
            issues.append({
                "type": "image_dark",
                "description": "Image analysis indicates dark lighting conditions",
                "severity": "medium",
                "metric_value": "pixel_mean_below_threshold",
                "threshold": self.DARK_THRESHOLD,
            })

        # Image too blurry
        if is_blurry:
            issues.append({
                "type": "image_blurry",
                "description": "Image analysis indicates blurry conditions",
                "severity": "medium",
                "metric_value": "laplacian_variance_below_threshold",
                "threshold": self.BLUR_THRESHOLD,
            })

        # OCR confidence degraded
        if ocr_confidence is not None and ocr_confidence < self.OCR_CONFIDENCE_THRESHOLD:
            issues.append({
                "type": "ocr_degraded",
                "description": f"OCR confidence {ocr_confidence:.2f} below threshold {self.OCR_CONFIDENCE_THRESHOLD:.2f}",
                "severity": "high" if ocr_confidence < self.OCR_CONFIDENCE_DEGRADED else "medium",
                "metric_value": ocr_confidence,
                "threshold": self.OCR_CONFIDENCE_THRESHOLD,
            })

        # Excessive reconnects
        if reconnect_count > 5:
            issues.append({
                "type": "excessive_reconnects",
                "description": f"{reconnect_count} reconnects in recent period",
                "severity": "high",
                "metric_value": reconnect_count,
            })

        # Too many processing errors
        if processing_errors > 10:
            issues.append({
                "type": "processing_errors",
                "description": f"{processing_errors} processing errors in recent period",
                "severity": "high",
                "metric_value": processing_errors,
            })

        return issues

    def get_health_summary(self) -> Dict[str, Any]:
        """Get a summary of the camera's health over recent period."""
        # Get recent health records
        recent = self.db_session.query(CameraHealthRecord).filter(
            CameraHealthRecord.camera_id == self.camera.id
        ).order_by(CameraHealthRecord.recorded_at.desc()).limit(10).all()

        if not recent:
            return {
                "status": "UNKNOWN",
                "last_check": never,
                "metrics": {},
                "issues": [],
            }

        # Calculate trends
        latest = recent[0]
        oldest = recent[-1]

        fps_values = [r.fps for r in recent if r.fps is not None]
        latency_values = [r.latency_ms for r in recent if r.latency_ms is not None]
        ocr_values = [r.ocr_confidence_trend for r in recent if r.ocr_confidence_trend is not None]

        return {
            "status": latest.status,
            "last_check": latest.recorded_at.isoformat(),
            " trends": {
                "fps_avg": round(np.mean(fps_values), 2) if fps_values else None,
                "fps_trend": "improving" if len(fps_values) >= 2 and fps_values[-1] > fps_values[0] else "declining",
                "latency_avg": round(np.mean(latency_values), 2) if latency_values else None,
                "ocr_confidence_avg": round(np.mean(ocr_values), 3) if ocr_values else None,
            },
            "latest_metrics": {
                "status": latest.status,
                "fps": latest.fps,
                "latency_ms": latest.latency_ms,
                "vehicles_detected": latest.vehicles_detected,
                "plates_detected": latest.plates_detected,
                "ocr_confidence": latest.ocr_confidence_trend,
                "is_dark": latest.is_dark,
                "is_blurry": latest.is_blurry,
                "reconnect_count": latest.reconnect_count,
                "processing_errors": latest.processing_errors,
            },
            "total_records": len(recent),
        }


# Export
__all__ = ["CameraHealthMonitor"]