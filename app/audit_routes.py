from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from app.db.session import get_db
from ..app.models import AuditLog, User, Camera, Watchlist, Alert, EvidenceRecord
from ..auth import get_current_active_user, check_admin_role, get_current_user

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/", response_model=List[Dict[str, Any]])
async def list_audit_logs(
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    user_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List audit logs with filtering."""
    # Admin-only access for full audit log
    if not check_admin_role(current_user) and current_user.id != (user_id or 0):
        raise HTTPException(status_code=403, detail="Admin required for audit log access")
    
    query = db.query(AuditLog)
    
    if action:
        query = query.filter(AuditLog.action == action)
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)
    if user_id is not None:
        query = query.filter(AuditLog.user_id == user_id)
    
    # Date filtering
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date)
            query = query.filter(AuditLog.timestamp >= start_dt)
        except ValueError:
            pass
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date)
            query = query.filter(AuditLog.timestamp <= end_dt)
        except ValueError:
            pass
    
    logs = query.order(AuditLog.timestamp.desc()).limit(500).all()
    
    result = []
    for log in logs:
        result.append({
            "id": log.id,
            "user_id": log.user_id,
            "action": log.action,
            "resource_type": log.resource_type,
            "resource_id": log.resource_id,
            "details": log.details,
            "ip_address": log.ip_address,
            "timestamp": log.timestamp.isoformat() if hasattr(log.timestamp, 'isoformat') else str(log.timestamp),
        })
    
    return result


@router.get("/stats")
async def get_audit_stats(
    days: int = 30,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get audit log statistics."""
    if not check_admin_role(current_user):
        raise HTTPException(status_code=403, detail="Admin required")
    
    from datetime import datetime, timedelta
    start_date = datetime.utcnow() - timedelta(days=days)
    
    # Count by action
    action_counts = db.query(
        AuditLog.action, func.count(AuditLog.id)
    ).filter(AuditLog.timestamp >= start_date).group_by(AuditLog.action).all()
    
    # Count by resource type
    resource_counts = db.query(
        AuditLog.resource_type, func.count(AuditLog.id)
    ).filter(AuditLog.timestamp >= start_date).group_by(AuditLog.resource_type).all()
    
    # Count by user
    user_counts = db.query(
        AuditLog.user_id, func.count(AuditLog.id)
    ).filter(AuditLog.timestamp >= start_date).group_by(AuditLog.user_id).all()
    
    return {
        "period_days": days,
        "total_events": db.query(AuditLog).filter(AuditLog.timestamp >= start_date).count(),
        "action_breakdown": {action: count for action, count in action_counts},
        "resource_breakdown": {rt: count for rt, count in resource_counts},
        "user_breakdown": {str(uid): count for uid, count in user_counts},
    }


@router.get("/events/{event_type}")
async def get_audit_events(
    event_type: str,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get specific types of audit events."""
    if not check_admin_role(current_user):
        raise HTTPException(status_code=403, detail="Admin required")
    
    query = db.query(AuditLog).filter(AuditLog.action == event_type).order(
        AuditLog.timestamp.desc()
    ).limit(limit)
    
    results = []
    for log in limit:
        results.append({
            "id": log.id,
            "user_id": log.user_id,
            "action": log.action,
            "resource_type": log.resource_type,
            "resource_id": log.resource_id,
            "details": log.details,
            "ip_address": log.ip_address,
            "timestamp": log.timestamp.isoformat() if hasattr(log.timestamp, 'isoformat') else str(log.timestamp),
        })
    
    return {"event_type": event_type, "events": results, "count": len(results)}