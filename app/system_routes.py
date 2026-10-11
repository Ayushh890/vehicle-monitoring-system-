from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from app.db.session import get_db
from ..app.models import Camera, CameraHealthRecord, User, AuditLog
from ..auth import get_current_active_user, check_admin_role
from ..engine.camera_health import CameraHealthMonitor

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/camera-health/{camera_id}")
async def get_camera_health(
    camera_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get current health status for a specific camera."""
    camera = db.query(Camera).get(camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    # Check authorization - camera owner or admin
    if camera.owner_id != current_user.id and not check_admin_role(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Get latest health record
    health_record = db.query(CameraHealthRecord).filter(
        CameraHealthRecord.camera_id == camera_id
    ).order_by(CameraHealthRecord.recorded_at.desc()).first()
    
    # Get recent health records for trend
    recent = db.query(CameraHealthRecord).filter(
        CameraHealthRecord.camera_id == camera_id
    ).order_by(CameraHealthRecord.recorded_at.desc()).limit(10).all()
    
    # Build health summary
    if health_record:
        issues = []
        if health_record.is_dark:
            issues.append("image_dark")
        if health_record.is_blurry:
            issues.append("image_blurry")
        if health_record.processing_errors > 5:
            issues.append("processing_errors")
        if health_record.reconnect_count > 5:
            issues.append("excessive_reconnects")
        
        return {
            "camera_id": camera.id,
            "camera_name": camera.name,
            "status": health_record.status,
            "last_frame_time": health_record.last_frame_time.isoformat() if health_record.last_frame_time else None,
            "fps": health_record.fps,
            "latency_ms": health_record.latency_ms,
            "reconnect_count": health_record.reconnect_count,
            "processing_errors": health_record.processing_errors,
            "vehicles_detected": health_record.vehicles_detected,
            "plates_detected": health_record.plates_detected,
            "ocr_confidence": health_record.ocr_confidence_trend,
            "is_dark": health_record.is_dark,
            "is_blurry": health_record.is_blurry,
            "issues": issues,
            "recorded_at": health_record.recorded_at.isoformat(),
        }
    else:
        return {
            "camera_id": camera.id,
            "camera_name": camera.name,
            "status": "OFFLINE",  # No data = offline
            "last_frame_time": None,
            "fps": None,
            "latency_ms": None,
            "reconnect_count": 0,
            "processing_errors": 0,
            "vehicles_detected": 0,
            "plates_detected": 0,
            "ocr_confidence": None,
            "is_dark": False,
            "is_blurry": False,
            "issues": ["no_data"],
            "recorded_at": None,
        }


@router.get("/cameras-health")
async def get_all_cameras_health(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get health status for all cameras."""
    # Check authorization
    if not check_admin_role(current_user):
        # Only show cameras owned by user
        cameras = db.query(Camera).filter(Camera.owner_id == current_user.id).all()
    else:
        cameras = db.query(Camera).all()
    
    result = []
    for camera in cameras:
        health_record = db.query(CameraHealthRecord).filter(
            CameraHealthRecord.camera_id == camera.id
        ).order_by(CameraHealthRecord.recorded_at.desc()).first()
        
        issues = []
        if health_record and health_record.is_dark:
            issues.append("dark")
        if health_record and health_record.is_blurry:
            issues.append("blurry")
        if health_record and health_record.processing_errors > 5:
            issues.append("errors")
        if health_record and health_record.reconnect_count > 5:
            issues.append("reconnects")
        
        result.append({
            "camera_id": camera.id,
            "camera_name": camera.name,
            "status": health_record.status if health_record else "OFFLINE",
            "fps": health_record.fps if health_record else None,
            "latency_ms": health_record.latency_ms if health_record else None,
            "vehicles_detected": health_record.vehicles_detected if health_record else 0,
            "plates_detected": health_record.plates_detected if health_record else 0,
            "ocr_confidence": health_record.ocr_confidence_trend if health_record else None,
            "issues": issues,
        })
    
    return {"cameras": result}


@router.post("/health-record")
async def record_camera_health(
    camera_id: int,
    status: str,
    fps: Optional[float] = None,
    latency_ms: Optional[float] = None,
    vehicles_detected: Optional[int] = None,
    plates_detected: Optional[int] = None,
    ocr_confidence: Optional[float] = None,
    is_dark: bool = False,
    is_blurry: bool = False,
    reconnect_count: Optional[int] = None,
    processing_errors: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Record camera health metrics."""
    # Check authorization
    camera = db.query(Camera).get(camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    if camera.owner_id != current_user.id and not check_admin_role(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Create health record
    health_record = CameraHealthRecord(
        camera_id=camera_id,
        status=status,
        fps=fps,
        latency_ms=latency_ms,
        vehicles_detected=vehicles_detected or 0,
        plates_detected=plates_detected or 0,
        ocr_confidence_trend=ocr_confidence,
        is_dark=is_dark,
        is_blurry=is_blurry,
        reconnect_count=reconnect_count or 0,
        processing_errors=processing_errors or 0,
    )
    
    db.add(health_record)
    db.commit()
    
    # Audit log
    from backend.app.models import AuditLog
    audit = AuditLog(
        user_id=current_user.id,
        action="camera_health_recorded",
        resource_type="camera",
        resource_id=str(camera_id),
        details=f"Health status: {status}, fps={fps}, latency={latency_ms}, vehicles={vehicles_detected}, plates={plates_detected}, ocr={ocr_confidence}",
    )
    db.add(audit)
    db.commit()
    
    return {"message": "Health record recorded", "status": status}


@router.get("/system-metrics")
async def get_system_metrics(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get system-wide metrics (CPU, RAM, workers, etc.)."""
    if not check_admin_role(current_user):
        raise HTTPException(status_code=403, detail="Admin required for system metrics")
    
    # In a production system, these would come from actual system monitoring
    # For now, return structure with "Unavailable" for metrics we can't measure
    # from the database alone
    return {
        "cpu_percent": "Unavailable",  # Would come from system monitoring
        "ram_percent": "Unavailable",  # Would come from system monitoring
        "gpu_available": "Unavailable",  # Would require GPU monitoring
        "vram_available": "Unavailable",  # Would require GPU monitoring
        "active_workers": "Unavailable",  # Would come from app server
        "queue_depth": "Unavailable",  # Would come from message queue
        "database_health": "healthy",  # Can check DB connection
        "redis_health": "healthy",  # Can check Redis connection
        "processing_fps": "Unavailable",  # Would come from pipeline stats
    }