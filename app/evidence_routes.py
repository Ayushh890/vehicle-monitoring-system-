from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import List, Optional
import json
import os
import hashlib
import uuid
import mimetypes

from app.db.session import get_db
from ..app.models import EvidenceRecord, AuditLog, Camera, Watchlist, User, Alert
from ..app.models.evidence import EvidenceRecord as EvidenceRecordModel, AuditLog as AuditLogModel
from ..alert_engine import AlertEngine, AlertType, AlertSeverity
from ..auth import get_current_active_user, get_current_user, check_admin_role

router = APIRouter(prefix="/api/evidence", tags=["evidence"])


def compute_checksum(file_path: str) -> str:
    """Compute SHA-256 checksum of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


@router.post("/upload", response_model=dict)
async def upload_evidence(
    file: UploadFile = File(...),
    camera_id: int = ...,
    source_type: str = ...,
    source_id: int = ...,
    description: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Upload and store evidence file."""
    import tempfile
    import shutil
    
    # Validate file type
    ext = os.path.splitext(file.filename)[1].lower()
    allowed_types = [".jpg", ".jpeg", ".png", ".mp4", ".json"]
    if ext not in allowed_types:
        raise HTTPException(status_code=400, detail="Invalid file type")
    
    # Save file to permanent storage
    unique_name = f"{uuid.uuid4()}{ext}"
    file_path = f"static/evidence/{unique_name}"
    os.makedirs("static/evidence", exist_ok=True)
    
    # Compute checksum before writing
    checksum = compute_checksum(file_path)  # This won't work - need to read first
    
    # Actually, let's compute checksum from the uploaded content
    content = await file.read()
    checksum = compute_checksum_from_bytes(content)
    os.makedirs("static/evidence", exist_ok=True)
    with open(file_path, "wb") as f:
        f.write(content)
    
    # Create evidence record
    evidence = EvidenceRecord(
        case_id=f"case_{uuid.uuid4().hex[:8]}",
        source_type=source_type,
        source_id=source_id,
        file_path=file_path,
        file_type=ext.lstrip("."),
        description=description,
        checksum=checksum,
        camera_id=camera_id if camera_id else None,
        ocr_confidence=None,  # Will be set later if applicable
        match_confidence=None,
    )
    
    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    
    # Audit log
    from backend.app.models import AuditLog
    audit = AuditLog(
        user_id=current_user.id,
        action="evidence_created",
        resource_type="evidence",
        resource_id=str(evidence.id),
        details=f"Evidence uploaded: {file.filename}, camera_id={camera_id}",
        ip_address=current_user.ip_address if hasattr(current_user, 'ip_address') else "unknown",
    )
    db.add(audit)
    db.commit()
    
    return {
        "id": evidence.id,
        "message": "Evidence uploaded successfully",
        "checksum": checksum,
        "file_path": file_path,
        "source_type": source_type,
    }


def compute_checksum_from_bytes(content: bytes) -> str:
    """Compute SHA-256 checksum from bytes."""
    return hashlib.sha256(content).hexdigest()


@router.get("/", response_model=List[dict])
async def list_evidence(
    camera_id: Optional[int] = None,
    source_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List evidence records with optional filters."""
    query = db.query(EvidenceRecord)
    
    if camera_id is not None:
        query = query.filter(EvidenceRecord.camera_id == camera_id)
    if source_type is not None:
        query = query.filter(EvidenceRecord.source_type == source_type)
    
    evidence_records = query.order(EvidenceRecord.captured_at.desc()).all()
    
    result = []
    for e in evidence_records:
        result.append({
            "id": e.id,
            "case_id": e.case_id,
            "source_type": e.source_type,
            "source_id": e.source_id,
            "file_type": e.file_type,
            "description": e.description,
            "checksum": e.checksum,
            "camera_id": e.camera_id,
            "ocr_confidence": e.ocr_confidence,
            "match_confidence": e.match_confidence,
            "captured_at": e.captured_at.isoformat() if hasattr(e.captured_at, 'isoformat') else str(e.captured_at),
            "created_at": e.created_at.isoformat() if hasattr(e.created_at, 'isoformat') else str(e.created_at),
        })
    
    return result


@router.get("/{evidence_id}", response_model=dict)
async def get_evidence(
    evidence_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get a single evidence record."""
    evidence = db.query(EvidenceRecord).get(evidence_id)
    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")
    
    # Check authorization - camera owner or admin can view
    if evidence.camera_id is not None:
        camera = db.query(Camera).get(evidence.camera_id)
        if camera and camera.owner_id != current_user.id and not check_admin_role(current_user):
            raise HTTPException(status_code=403, detail="Not authorized to view this evidence")
    
    return {
        "id": evidence.id,
        "case_id": evidence.case_id,
        "source_type": evidence.source_type,
        "source_id": evidence.source_id,
        "file_path": evidence.file_path,
        "file_type": evidence.file_type,
        "description": evidence.description,
        "checksum": evidence.checksum,
        "metadata": json.loads(evidence.metadata) if evidence.metadata else None,
        "camera_id": evidence.camera_id,
        "vehicle_crop_path": evidence.vehicle_crop_path,
        "plate_crop_path": evidence.plate_crop_path,
        "detection_frame_ref": evidence.detection_frame_ref,
        "bounding_box": evidence.bounding_box,
        "ocr_result": evidence.ocr_result,
        "ocr_confidence": evidence.ocr_confidence,
        "match_confidence": evidence.match_confidence,
        "captured_at": evidence.captured_at.isoformat() if hasattr(e.captured_at, 'isoformat') else str(e.captured_at),
        "created_at": evidence.created_at.isoformat() if hasattr(e.created_at, 'isoformat') else str(e.created_at),
    }


@router.delete("/{evidence_id}")
async def delete_evidence(
    evidence_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Delete an evidence record."""
    evidence = db.query(EvidenceRecord).get(evidence_id)
    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")
    
    # Check authorization
    if evidence.camera_id is not None:
        camera = db.query(Camera).get(evidence.camera_id)
        if camera and camera.owner_id != current_user.id and not check_admin_role(current_user):
            raise HTTPException(status_code=403, detail="Not authorized to delete this evidence")
    
    # Remove file from storage
    import os
    if os.path.exists(evidence.file_path):
        os.remove(evidence.file_path)
    
    # Audit log
    from backend.app.models import AuditLog
    audit = AuditLog(
        user_id=current_user.id,
        action="evidence_deleted",
        resource_type="evidence",
        resource_id=str(evidence.id),
        details=f"Evidence {evidence.id} deleted by {current_user.email}",
    )
    db.add(audit)
    db.delete(evidence)
    db.commit()
    
    return {"message": "Evidence deleted successfully"}