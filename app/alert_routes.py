from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from ..app.models import Alert, Watchlist, Camera, User
from ..auth import get_current_active_user, get_current_user
from ..alert_engine import AlertEngine, AlertType, AlertSeverity

router = APIRouter(prefix="/alerts", tags=["alerts"])


# Initialize alert engine (per-request or singleton)
def get_alert_engine(db: Session, user_id: int) -> AlertEngine:
    return AlertEngine(db_session=db, user_id=user_id)


@router.get("/", response_model=List[dict])
async def list_alerts(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List alerts, optionally filtered by status."""
    engine = get_alert_engine(db_session=db, user_id=current_user.id)
    alerts = engine.list_alerts(status=status)
    return [{"id": a.id, "alert_type": a.alert_type, "severity": a.severity,
             "timestamp": a.timestamp.isoformat() if hasattr(a.timestamp, 'isoformat') else str(a.timestamp)}
            for a in alerts]


@router.post("/acknowledge/{alert_id}")
async def acknowledge_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Acknowledge an alert."""
    alert = db.query(Alert).get(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.status = "ACKNOWLEDGED"
    # Add audit log entry
    from backend.app.models import AuditLog
    audit = AuditLog(
        user_id=current_user.id,
        action="alert_acknowledged",
        resource_type="alert",
        resource_id=str(alert_id),
    )
    db.add(audit)
    db.commit()
    return {"camera_id": alert.camera_id, "status": "ACKNOWLEDGED",
            "message": "Alert acknowledged successfully"}


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
    return {"camera_id": camera.id, "status": camera.status,
            "message": "Camera status retrieved successfully"}