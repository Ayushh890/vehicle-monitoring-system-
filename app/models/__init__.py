"""Base model and metadata configuration for SQLAlchemy/Alembic.

Also exports the CameraConfig model for convenience.
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import declarative_base

# Naming convention for indexes and constraints
# This helps Alembic generate consistent names
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

Base = declarative_base()

metadata = MetaData(naming_convention=convention)

# Export key models
from app.models.cameras import CameraConfig  # noqa: F401

__all__ = ["Base", "convention", "CameraConfig"]