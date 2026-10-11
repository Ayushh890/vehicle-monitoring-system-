"""Evidence and audit logging models for SIH26127."""

from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
    CheckConstraint,
    Index,
    func,
)
from sqlalchemy.orm import relationship

from backend.app.models.base import Base, convention


class EvidenceRecord(Base):
    """Evidence records linked to alerts or events.

    Stores physical evidence such as vehicle crops, plate crops,
    detection frames, and OCR results with integrity metadata.
    """

    __tablename__ = "evidence"

    id = Column(Integer, primary_key=True)
    case_id = Column(String(100), nullable=True)
    source_type = Column(String(50), nullable=False)  # e.g., "CAMERA", "PLATE_READ", "TRACK"
    source_id = Column(Integer, nullable=True)  # ID of the source camera/table
    file_path = Column(String(500), nullable=False)  # Path to stored file
    file_type = Column(String(100), nullable=False)  # e.g., "jpg", "mp4", "json"
    description = Column(Text, nullable=True)
    # Integrity metadata
    checksum = Column(String(64), nullable=True)  # SHA-256 hash of the file
    metadata = Column(Text, nullable=True)  # JSON string for additional fields
    # Core evidence fields
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=True)
    vehicle_crop_path = Column(String(500), nullable=True)  # Path to vehicle crop image
    plate_crop_path = Column(String(500), nullable=True)  # Path to plate crop image
    detection_frame_ref = Column(String(100), nullable=True)  # Frame ID or timestamp reference
    bounding_box = Column(String(100), nullable=True)  # JSON string: "(x1, y1, x2, y2)"
    ocr_result = Column(String(255), nullable=True)  # Raw OCR output
    ocr_confidence = Column(Float, nullable=True)  # 0.0 to 1.0
    match_confidence = Column(Float, nullable=True)  # Cross-camera or model confidence
    # Timestamps
    captured_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_evidence_camera_id", "camera_id"),
        Index("ix_evidence_source_type", "source_type"),
        Index("ix_evidence_source_id", "source_id"),
        Index("ix_evidence_case_id", "case_id"),
        Index("ix_evidence_checksum", "checksum"),
        Index("ix_evidence_captured_at", "captured_at"),
        CheckConstraint(
            "ocr_confidence >= 0.0 AND ocr_confidence <= 1.0",
            name="chk_evidence_ocr_conf",
        ),
        CheckConstraint(
            "match_confidence >= 0.0 AND match_confidence <= 1.0",
            name="chk_evidence_match_conf",
        ),
    )

    # Relationships
    camera = relationship("Camera", back_populates="evidence_records")


class AuditLog(Base):
    """Audit log for system operations and user actions.

    Tracks all significant events for compliance and security.
    Does NOT log secrets or sensitive JWT tokens.
    """

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(100), nullable=False)  # e.g., "evidence_view", "alert_acknowledged"
    resource_type = Column(String(50), nullable=True)  # e.g., "evidence", "alert", "watchlist"
    resource_id = Column(String(100), nullable=True)  # ID of the affected resource
    details = Column(Text, nullable=True) # Description of what changed
    ip_address = Column(String(45), nullable=True)  # IPv4 or IPv6
    timestamp = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Ensure we don't store secrets in the details field
    __table_args__ = (
        Index("ix_audit_logs_timestamp", "timestamp"),
        Index("ix_audit_logs_user_id", "user_id"),
        Index("ix_audit_logs_action", "action"),
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
        CheckConstraint(
            "action NOT LIKE '%secret%' AND action NOT LIKE '%token%' AND action NOT LIKE '%password%'",
            name="chk_audit_no_secrets",
        ),
    )

    # Relationships
    user = relationship("User", back_populates="audit_entries")