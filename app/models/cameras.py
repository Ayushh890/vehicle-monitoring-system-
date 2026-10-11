"""Camera configuration models."""

from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    CheckConstraint,
    Index,
    Text,
    UniqueConstraint,
    ForeignKey,
)
from sqlalchemy.orm import relationship

from app.models.base import Base, convention


class CameraConfig(Base):
    """Camera configuration with RTSP credentials securely stored.

    Credentials are never exposed in API responses - only a camera_id reference
    is returned. Access is controlled via role-based permissions.
    """

    __tablename__ = "camera_configs"

    id = Column(Integer, primary_key=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False, unique=True)
    rtsp_url = Column(String(255), nullable=False)  # Internal URL only
    username = Column(String(100), nullable=True)  # Internal only
    password = Column(String(100), nullable=True)  # Never returned in API responses
    channel = Column(Integer, nullable=False, default=0)
    resolution = Column(String(50), nullable=False, default="1920x1080")  # stored as string
    processing_fps = Column(Integer, nullable=False, default=25)
    # Status tracking
    is_active = Column(Boolean, nullable=False, default=True)
    last_connected = Column(DateTime(timezone=True), nullable=True)
    last_disconnected = Column(DateTime(timezone=True), nullable=True)
    # Audit
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.utcnow(),
    )
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        Index("ix_camera_configs_camera_id", "camera_id"),
        Index("ix_camera_configs_active", "is_active"),
        CheckConstraint(
            "processing_fps > 0", name="chk_config_fps_positive"
        ),
    )