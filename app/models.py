"""User model with secure password hashing for authentication."""

from datetime import datetime, timedelta

from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    CheckConstraint,
    Index,
)
from sqlalchemy.orm import relationship

from app.models.base import Base, convention


class User(Base):
    """User model with secure password hashing for authentication."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True, index=True)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    is_staff = Column(Boolean, default=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.utcnow(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.utcnow(),
        onupdate=lambda: datetime.utcnow(),
    )

    # Full-text search vector for username/email
    search_vector = Column(
        "search_vector",
        "pgsearch",
        nullable=True,
    )

    # Constraints
    __table_args__ = (
        Index("ix_users_username", "username", unique=True),
        Index("ix_users_email", "email", unique=True),
        CheckConstraint(
            "is_active IN (TRUE, FALSE)",
            name="chk_user_active",
        ),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="chk_user_confidence",
        ),
    )

    # Relationships
    camera_configs = relationship("CameraConfig", back_populates="owner", cascade="all, delete-orphan")
    watchlist_entries = relationship("Watchlist", back_populates="owner", cascade="all, delete-orphan")
    created_alerts = relationship("Alert", back_populates="creator", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", foreign_keys="AuditLog.user_id", back_populates="user")

    def verify_password(self, plain_password: str) -> bool:
        """Verify a password against the hashed password."""
        from ..auth import verify_password as verify_pwd
        return verify_pwd(plain_password, self.hashed_password)

    def get_reset_token(self) -> str:
        """Generate a password reset token."""
        import secrets
        return secrets.token_urlsafe(32)

    @property
    def is_active(self) -> bool:
        return self._is_active

    @property
    def is_admin(self) -> bool:
        return self.is_superuser


# Update CameraConfig to reference owner
from app.models.camera_config import CameraConfig
CameraConfig.owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
CameraConfig.owner = relationship("User", back_populates="camera_configs")