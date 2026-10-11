"""Camera health monitoring and system observability."""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    CheckConstraint,
    Index,
)
from sqlalchemy.orm import relationship

from backend.app.models.base import Base, convention


class CameraHealthRecord(Base):
    """Health record for a camera, tracking status and metrics over time."""

    __tablename__ = "camera_health"

    id = Column(Integer, primary_key=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False)
    status = Column(
        String(20),
        nullable=False,
    )  # ONLINE, CONNECTING, DEGRADED, OFFLINE, ERROR
    last_frame_time = Column(DateTime(timezone=True), nullable=True)
    fps = Column(Float, nullable=True)
    latency_ms = Column(Float, nullable=True)  # Average latency in milliseconds
    reconnect_count = Column(Integer, nullable=False, default=0)
    processing_errors = Column(Integer, nullable=False, default=0)
    vehicles_detected = Column(Integer, nullable=False, default=0)
    plates_detected = Column(Integer, nullable=False, default=0)
    ocr_confidence_trend = Column(Float, nullable=True)  # Average OCR confidence (0-1)
    # Quality flags
    is_dark = Column(Boolean, nullable=False, default=False)
    is_blurry = Column(Boolean, nullable=False, default=False)
    # Timestamps
    recorded_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.utcnow(),
    )

    __table_args__ = (
        Index("ix_camera_health_camera_id", "camera_id"),
        Index("ix_camera_health_status", "status"),
        Index("ix_camera_health_recorded_at", "recorded_at"),
        Index("ix_camera_health_last_frame", "last_frame_time"),
        CheckConstraint(
            "status IN ('ONLINE', 'CONNECTING', 'DEGRADED', 'OFFLINE', 'ERROR')",
            name="chk_camera_health_status",
        ),
    )

    # Relationships
    camera = relationship("Camera", back_populates="health_records")