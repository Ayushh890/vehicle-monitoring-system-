"""User model with password hashing for authentication."""

from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    Text,
    CheckConstraint,
    Index,
)
from sqlalchemy.orm import relationship

from app.models.base import Base, convention


class User(Base):
    """User model with secure password hashing."""

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

    __table_args__ = (
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="chk_user_confidence",
        ),
    )

    # Relationships
    camera_configs = relationship("CameraConfig", back_populates="owner")
    watchlist_entries = relationship("Watchlist", back_populates="owner")
    created_alerts = relationship("Alert", back_populates="creator")
    audit_logs = relationship("AuditLog", foreign_keys="AuditLog.user_id", back_populates="user")

    def verify_password(self, plain_password: str) -> bool:
        """Verify a password against the hashed password."""
        # In production, use bcrypt or similar
        # This is a placeholder - use proper password verification
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        return pwd_context.verify(plain_password, self.hashed_password)

    def get_reset_token(self):
        """Generate a password reset token."""
        # Placeholder - use JWT or similar in production
        import secrets
        return secrets.token_urlsafe(32)


# Update CameraConfig to reference owner
from app.models.cameras import CameraConfig
CameraConfig.owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
CameraConfig.owner = relationship("User", back_populates="camera_configs")