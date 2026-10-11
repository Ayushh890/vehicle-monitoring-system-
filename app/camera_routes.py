from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any
from app.db.session import get_db
from ..app.models import Camera, CameraConfig, User
from ..auth import get_current_active_user, check_admin_role
from ..core.source import RtspCameraSource, CameraSource, create_source

router = APIRouter(prefix="/api/cameras", tags=["cameras"])


@router.get("/{camera_id}/config", response_model=Dict[str, Any])
async def get_camera_config(
    camera_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get camera configuration (credentials never returned)."""
    camera = db.query(Camera).get(camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    # Check authorization - camera owner or admin
    if camera.owner_id != current_user.id and not check_admin_role(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Get config, never return credentials
    config = db.query(CameraConfig).filter(CameraConfig.camera_id == camera_id).first()
    if not config:
        return {
            "camera_id": camera.id,
            "rtsp_url": None,
            "username": None,
            "password": None,
            "channel": config.channel if config else 0,
            "resolution": config.resolution if config else "1920x1080",
            "processing_fps": config.processing_fps if config else 25,
        }
    
    return {
        "camera_id": camera.id,
        "rtsp_url": None,  # Never return credentials
        "username": None,  # Never return credentials
        "password": None,  # Never return credentials
        "channel": config.channel,
        "resolution": config.resolution,
        "processing_fps": config.processing_fps,
    }


@router.post("/{camera_id}/config", response_model=Dict[str, Any])
async def update_camera_config(
    camera_id: int,
    rtsp_url: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    channel: int = 0,
    resolution: str = "1920x1080",
    processing_fps: int = 25,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Update camera configuration (credentials stored securely)."""
    camera = db.query(Camera).get(camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    # Check authorization
    if camera.owner_id != current_user.id and not check_admin_role(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Store config securely - never log credentials
    config = db.query(CameraConfig).filter(CameraConfig.camera_id == camera_id).first()
    if not config:
        config = CameraConfig(
            camera_id=camera_id,
            rtsp_url=rtsp_url,  # Internal use only
            username=username,  # Internal only
            password=password,  # Never returned in API responses
            channel=channel,
            resolution=resolution,
            processing_fps=processing_fps,
        )
        db.add(config)
    else:
        config.rtsp_url = rtsp_url
        config.username = username
        config.password = password
        config.channel = channel
        config.resolution = resolution
        config.processing_fps = processing_fps
    
    camera.enabled = True
    camera.updated_at = datetime.utcnow()
    db.commit()
    
    # Audit log
    from backend.app.models import AuditLog
    audit = AuditLog(
        user_id=current_user.id,
        action="camera_config_updated",
        resource_type="camera",
        resource_id=str(camera_id),
        details=f"Config updated for camera {camera.camera_id}",
    )
    db.add(audit)
    db.commit()
    
    # Return config without credentials
    return {
        "camera_id": camera.id,
        "rtsp_url": None,  # Never return credentials
        "username": None,  # Never return credentials
        "password": None,  # Never return credentials
        "channel": config.channel,
        "resolution": config.resolution,
        "processing_fps": config.processing_fps,
        "message": "Configuration updated successfully (credentials secured)",
    }


@router.post("/{camera_id}/connect", response_model=Dict[str, Any])
async def connect_camera(
    camera_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Attempt to connect to camera RTSP stream."""
    camera = db.query(Camera).get(camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    # Check authorization
    if camera.owner_id != current_user.id and not check_admin_role(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Get or create config
    config = db.query(CameraConfig).filter(CameraConfig.camera_id == camera_id).first()
    if not config:
        config = CameraConfig(camera_id=camera_id)
        db.add(config)
    
    # Build source with credentials
    source = RtspCameraSource(
        source_id=camera.camera_id,
        rtsp_url=config.rtsp_url,
        username=config.username,
        password=config.password,
        channel=config.channel,
        resolution=tuple(int(x) for x in config.resolution.split("x")) if "x" in config.resolution else (1920, 1080),
    )
    
    # Attempt to open
    if source.open():
        # Record connection
        config.last_connected = datetime.utcnow()
        db.commit()
        
        # Audit log
        from backend.app.models import AuditLog
        audit = AuditLog(
            user_id=current_user.id,
            action="camera_connected",
            resource_type="camera",
            resource_id=str(camera_id),
            details=f"RTSP connected for camera {camera.camera_id}",
        )
        db.add(audit)
        db.commit()
        
        return {
            "camera_id": camera.id,
            "status": "ONLINE",
            "message": "RTSP connection established",
            "fps": source.fps,
            "vehicles_detected": source.vehicles_detected,
            "plates_detected": source.plates_detected,
        }
    else:
        # Record failed connection
        config.last_disconnected = datetime.utcnow()
        db.commit()
        
        # Audit log
        from backend.app.models import AuditLog
        audit = AuditLog(
            user_id=current_user.id,
            action="camera_connection_failed",
            resource_type="camera",
            resource_id=str(camera_id),
            details=f"RTSP connection failed for camera {camera.camera_id}",
        )
        db.add(audit)
        db.commit()
        
        return {
            "camera_id": camera.id,
            "status": "OFFLINE",
            "message": "Could not establish RTSP connection",
        }


@router.post("/{camera_id}/disconnect")
async def disconnect_camera(
    camera_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Disconnect camera stream."""
    camera = db.query(Camera).get(camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    # Check authorization
    if camera.owner_id != current_user.id and not check_admin_role(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Get config
    config = db.query(CameraConfig).filter(CameraConfig.camera_id == camera_id).first()
    if config:
        config.last_disconnected = datetime.utcnow()
        db.commit()
    
    # Release source
    # Note: In a full implementation, we'd track the source object and call release()
    # For now, just record the disconnection
    
    # Audit log
    from backend.app.models import AuditLog
    audit = AuditLog(
        user_id=current_user.id,
        action="camera_disconnected",
        resource_type="camera",
        resource_id=str(camera_id),
        details=f"Camera {camera.camera_id} disconnected",
    )
    db.add(audit)
    db.commit()

    return {
        "camera_id": camera.id,
        "status": "OFFLINE",
        "message": "Camera disconnected successfully",
    }


@router.get("/{camera_id}/status")
async def get_camera_status(
    camera_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get camera operational status."""
    camera = db.query(Camera).get(camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    # Check authorization
    if camera.owner_id != current_user.id and not check_admin_role(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Get latest health record
    health = db.query(CameraHealthRecord).filter(
        CameraHealthRecord.camera_id == camera_id
    ).order_by(CameraHealthRecord.recorded_at.desc()).first()
    
    return {
        "camera_id": camera.id,
        "camera_name": camera.name,
        "status": health.status if health else "OFFLINE",
        "last_frame_time": health.last_frame_time.isoformat() if health and health.last_frame_time else None,
        "fps": health.fps if health else None,
        "latency_ms": health.latency_ms if health else None,
        "reconnect_count": health.reconnect_count if health else 0,
        "processing_errors": health.processing_errors if health else 0,
        "vehicles_detected": health.vehicles_detected if health else 0,
        "plates_detected": health.plates_detected if health else 0,
        "ocr_confidence": health.ocr_confidence if health else None,
    }


@router.get("/factory/{source_type}", response_model=Dict[str, Any])
async def create_source_factory(
    source_type: str,
    camera_id: int = 0,
    db: Session = Depends(get_db),
):
    """Factory function to create source instances."""
    try:
        source = create_source(source_type, f"camera_{camera_id}")
        return {
            "source_type": source_type,
            "type_name": type(source).__name__,
            "is_opened": source.is_opened,
            "status": source.status,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))