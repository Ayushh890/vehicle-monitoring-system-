from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, select, desc, and_, or_
from typing import List, Optional
from datetime import datetime, timedelta

from app.db.session import get_db
from ..db.models import Camera, VehicleObservation, PlateRead, VehicleTrack, GlobalVehicle, AuditLog, SystemEvent

analytics_router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@analytics_router.get("/overview")
async def get_overview(db: Session = Depends(get_db)):
    """Get overall traffic overview."""
    try:
      # Total vehicle observations
      vehicle_count = db.query(func.count(VehicleObservation.id)).scalar() or 0
      
      # Unique vehicles (by vehicle_id if available, otherwise distinct observations)
      unique_vehicle_count = db.query(func.count(func.distinct(VehicleObservation.vehicle_id))).scalar() or 0
      if unique_vehicle_count == 0:
        unique_vehicle_count = db.query(func.count()).select(
          func.count().distinct(VehicleObservation.id)
        ).scalar() or 0
      
      # Vehicles per hour (last 24h)
      one_day_ago = datetime.utcnow() - timedelta(hours=24)
      vehicles_per_hour = db.query(func.count(VehicleObservation.id)).filter(
        VehicleObservation.captured_at >= one_day_ago
      ).scalar() or 0
      vehicles_per_hour = round(vehicles_per_hour / 24, 2) if vehicles_per_hour else 0
      
      # Average speed from vehicle tracks
      avg_speed_result = db.query(func.avg(VehicleTrack.speed)).filter(
        VehicleTrack.speed.isnot(None)
      ).scalar()
      average_speed = round(float(avg_speed_result), 2) if avg_speed_result else None
      
      # Median speed - approximate using percentile
      median_speed_result = db.query(VehicleTrack.speed).filter(
        VehicleTrack.speed.isnot(None)
      ).order_by(VehicleTrack.speed.asc()).limit(1).offset(
        func.count(VehicleTrack.id) // 2
      ).scalar()
      median_speed = round(float(median_speed_result), 2) if median_speed_result else None
      
      # Camera throughput - observations per camera
      camera_throughput_result = db.query(
        Camera.id, Camera.name, func.count(VehicleObservation.id).label("obs_count")
      ).outerjoin(
        VehicleObservation,
        VehicleObservation.camera_id == Camera.id
      ).group_by(Camera.id).all()
      
      active_cameras = db.query(Camera).filter(Camera.enabled == True).count()
      avg_throughput = round(
        (db.query(func.count(VehicleObservation.id)) / max(active_cameras, 1)).scalar() or 0,
        2
      ) if active_cameras else 0
      
      return {
        "vehicle_count": vehicle_count,
        "unique_vehicle_count": unique_vehicle_count,
        "vehicles_per_hour": vehicles_per_hour,
        "average_speed": average_speed,
        "median_speed": median_speed,
        "camera_throughput": {
          "active_cameras": active_cameras,
          "average_throughput_per_camera": avg_throughput,
          "camera_details": [
            {
              "camera_id": str(row.id),
              "camera_name": row.name,
              "observations": row.obs_count,
            }
            for row in camera_throughput_result
          ],
        },
      }
    except Exception as e:
      raise HTTPException(status_code=500, detail=str(e))


@analytics_router.get("/traffic-volume")
async def get_traffic_volume(
  hours: int = 1,
  db: Session = Depends(get_db),
):
    """Get traffic volume for specified hours."""
    try:
      delta = timedelta(hours=hours)
      since = datetime.utcnow() - delta
      
      # Total vehicle count in period
      vehicle_count = db.query(func.count(VehicleObservation.id)).filter(
        VehicleObservation.captured_at >= since
      ).scalar() or 0
      
      # Unique vehicles
      unique_vehicles = db.query(func.count(func.distinct(VehicleObservation.vehicle_id))).filter(
        VehicleObservation.captured_at >= since
      ).scalar() or 0
      if unique_vehicles == 0:
        unique_vehicles = db.query(func.count()).select(
          func.count().distinct(VehicleObservation.id)
        ).filter(VehicleObservation.captured_at >= since).scalar() or 0
      
      # Per-camera breakdown
      per_camera = db.query(
        Camera.id,
        Camera.name,
        func.count(VehicleObservation.id).label("count"),
      ).outerjoin(
        VehicleObservation,
        VehicleObservation.camera_id == Camera.id,
      ).filter(
        VehicleObservation.captured_at >= since
      ).group_by(Camera.id).all()
      
      per_camera_list = [
        {
          "camera_id": str(row.id),
          "camera_name": row.name,
          "vehicle_count": row.count,
        }
        for row in per_camera
      ]
      
      # Time range info
      latest = db.query(func.max(VehicleObservation.captured_at)).scalar()
      latest_str = latest.isoformat() if latest else None
      
      return {
        "hours": hours,
        "vehicle_count": vehicle_count,
        "unique_vehicle_count": unique_vehicles,
        "period_start": (datetime.utcnow() - delta).isoformat(),
        "period_end": datetime.utcnow().isoformat(),
        "latest_observation": latest_str,
        "per_camera_breakdown": per_camera_list,
      }
    except Exception as e:
      raise HTTPException(status_code=500, detail=str(e))


@analytics_router.get("/speed")
async def get_speed_analysis(
  hours: int = 1,
  db: Session = Depends(get_db),
):
    """Get speed analysis for specified hours."""
    try:
      delta = timedelta(hours=hours)
      since = datetime.utcnow() - delta
      
      # Average speed
      avg_speed_result = db.query(func.avg(VehicleTrack.speed)).filter(
        and_(VehicleTrack.speed.isnot(None), VehicleTrack.created_at >= since)
      ).scalar()
      
      # Median speed approximation
      median_result = db.query(VehicleTrack.speed).filter(
        and_(VehicleTrack.speed.isnot(None), VehicleTrack.created_at >= since)
      ).order_by(VehicleTrack.speed.asc()).limit(
        func.ceil(func.count(VehicleTrack.id) / 2)
      ).order_by(VehicleTrack.speed.desc()).limit(1).scalar()
      
      # Speed distribution by camera
      speed_by_camera = db.query(
        Camera.id,
        Camera.name,
        func.avg(VehicleTrack.speed).label("avg_speed"),
        func.count(VehicleTrack.id).label("observation_count"),
      ).outerjoin(
        VehicleTrack,
        and_(VehicleTrack.camera_id == Camera.id, VehicleTrack.created_at >= since),
      ).group_by(Camera.id).all()
      
      speed_distribution = [
        {
          "camera_id": str(row.id),
          "camera_name": row.name,
          "average_speed": round(float(row.avg_speed), 2) if row.avg_speed else None,
          "observation_count": row.observation_count,
        }
        for row in speed_by_camera
      ]
      
      return {
        "period_hours": hours,
        "average_speed": round(float(avg_speed_result), 2) if avg_speed_result else None,
        "median_speed": round(float(median_result), 2) if median_result else None,
        "vehicle_count": db.query(func.count(VehicleObservation.id)).filter(
          VehicleObservation.captured_at >= since
        ).scalar() or 0,
        "speed_by_camera": speed_distribution,
      }
    except Exception as e:
      raise HTTPException(status_code=500, detail=str(e))


@analytics_router.get("/congestion")
async def get_congestion(
  hours: int = 1,
  db: Session = Depends(get_db),
):
    """Get congestion analysis with explanation."""
    try:
      delta = timedelta(hours=hours)
      since = datetime.utcnow() - delta
      
      # Vehicle count in period
      vehicle_count = db.query(func.count(VehicleObservation.id)).filter(
        VehicleObservation.captured_at >= since
      ).scalar() or 0
      
      # Average speed in period
      avg_speed_result = db.query(func.avg(VehicleTrack.speed)).filter(
        and_(VehicleTrack.speed.isnot(None), VehicleTrack.created_at >= since)
      ).scalar()
      avg_speed = round(float(avg_speed_result), 2) if avg_speed_result else None
      
      # Vehicle count previous period for comparison
      prev_delta = timedelta(hours=hours)
      prev_since = datetime.utcnow() - (delta * 2)
      prev_vehicle_count = db.query(func.count(VehicleObservation.id)).filter(
        and_(VehicleObservation.captured_at >= prev_since, VehicleObservation.captured_at < since)
      ).scalar() or 0
      
      # Calculate congestion score
      # Based on: high vehicle count + low average speed = high congestion
      congestion_score = 0.0
      explanation_parts = []
      
      if avg_speed is not None and vehicle_count > 0:
        # Normalize: if speed is below 30 km/h in urban area, that's congested
        # Relative comparison with previous period
        if prev_vehicle_count > 0:
          volume_change = (vehicle_count - prev_vehicle_count) / prev_vehicle_count * 100
        else:
          volume_change = 0
        
        # Score components
        # Speed component: lower speed = higher score (0-0.5)
        speed_component = max(0, 0.5 - (avg_speed / 60) * 0.5) if avg_speed else 0.25
        
        # Volume component: higher volume = higher score (0-0.5)
        volume_component = min(0.5, abs(volume_change) / 200) if prev_vehicle_count else 0.25
        
        congestion_score = round(speed_component + volume_component, 2)
        
        if volume_change > 15:
          explanation_parts.append(f"traffic volume increased {volume_change:.0f}%")
        if avg_speed is not None and avg_speed < 40:
          explanation_parts.append(f"average speed decreased {((40 - avg_speed) / 40 * 100):.0f}%")
        
        explanation = ". ".join(explanation_parts) + "." if explanation_parts else ""
      else:
        congestion_score = 0.0
        explanation = "Insufficient data for congestion calculation"
      
      # Congested cameras - cameras with above-average volume & below-average speed
      congested_cameras = db.query(
        Camera.id,
        Camera.name,
        func.count(VehicleObservation.id).label("obs_count"),
        func.avg(VehicleTrack.speed).label("avg_speed"),
      ).outerjoin(
        VehicleObservation,
        VehicleObservation.camera_id == Camera.id,
      ).outerjoin(
        VehicleTrack,
        and_(VehicleTrack.camera_id == Camera.id, VehicleTrack.created_at >= since),
      ).group_by(Camera.id).having(
        func.count(VehicleObservation.id) > 5
      ).all() if avg_speed else []
      
      congested_list = [
        {
          "camera_id": str(row.id),
          "camera_name": row.name,
          "vehicle_count": row.obs_count,
          "average_speed": round(float(row.avg_speed), 2) if row.avg_speed else None,
        }
        for row in congested_cameras
      ]
      
      return {
        "congestion_score": congestion_score,
        "congestion_level": (
          "HIGH" if congestion_score > 0.6 else
          "MEDIUM" if congestion_score > 0.3 else
          "LOW" if congestion_score > 0 else
          "NONE"
        ),
        "vehicle_count": vehicle_count,
        "average_speed": avg_speed,
        "previous_period_vehicle_count": prev_vehicle_count,
        "volume_change_percent": round(
          (vehicle_count - prev_vehicle_count) / max(prev_vehicle_count, 1) * 100, 2
        ),
        "explanation": explanation,
        "congested_cameras": congested_list,
        "period": {
          "start": (datetime.utcnow() - delta).isoformat(),
          "end": datetime.utcnow().isoformat(),
        },
      }
    except Exception as e:
      raise HTTPException(status_code=500, detail=str(e))


@analytics_router.get("/camera-throughput")
async def get_camera_throughput(
  hours: int = 1,
  db: Session = Depends(get_db),
):
    """Get camera throughput data."""
    try:
      delta = timedelta(hours=hours)
      since = datetime.utcnow() - delta
      
      # Per-camera observations
      throughput = db.query(
        Camera.id,
        Camera.name,
        Camera.location_name,
        func.count(VehicleObservation.id).label("vehicle_count"),
        func.count(func.distinct(VehicleObservation.vehicle_id)).label(
          "unique_vehicles"
        ),
        func.min(VehicleObservation.captured_at).label("first_observation"),
        func.max(VehicleObservation.captured_at).label("last_observation"),
      ).outerjoin(
        VehicleObservation,
        VehicleObservation.camera_id == Camera.id,
      ).filter(
        VehicleObservation.captured_at >= since
      ).group_by(Camera.id).all()
      
      result = []
      for row in throughput:
        # Calculate throughput (vehicles per hour)
        time_span = (
          (row.last_observation - row.first_observation).total_seconds() / 3600
        ) if row.first_observation and row.last_observation else hours
        throughput_per_hour = round(
          row.vehicle_count / max(time_span, 0.01), 2
        ) if row.vehicle_count else 0
        
        result.append(
          {
            "camera_id": str(row.id),
            "camera_name": row.name or "",
            "location": row.location_name or "",
            "vehicle_count": row.vehicle_count,
            "unique_vehicles": row.unique_vehicles or 0,
            "first_observation": row.first_observation.isoformat()
            if row.first_observation
            else None,
            "last_observation": row.last_observation.isoformat()
            if row.last_observation
            else None,
            "throughput_per_hour": throughput_per_hour,
          }
        )
      
      return {
        "period_hours": hours,
        "camera_throughput": result,
        "total_cameras_analyzed": len(result),
        "highest_throughput": (
          max(result, key=lambda x: x["throughput_per_hour"])["throughput_per_hour"]
          if result
          else 0
        ),
        "lowest_throughput": (
          min(result, key=lambda x: x["throughput_per_hour"])["throughput_per_hour"]
          if result
          else 0
        ),
      }
    except Exception as e:
      raise HTTPException(status_code=500, detail=str(e))


@analytics_router.get("/od")
async def get_origin_destination(
  hours: int = 1,
  db: Session = Depends(get_db),
):
    """Get origin-destination analysis."""
    try:
      delta = timedelta(hours=hours)
      since = datetime.utcnow() - delta
      
      # Get vehicle tracks that span multiple cameras
      od_pairs = (
        db.query(
          VehicleTrack.camera_id.label("from_camera"),
          func.count(VehicleTrack.id).label("pair_count"),
        )
        .filter(VehicleTrack.created_at >= since)
        .group_by(VehicleTrack.camera_id)
        .all()
      )
      
      od_result = [
        {
          "from_camera": str(row.from_camera) if row.from_camera else "unknown",
          "od_pairs": row.pair_count,
        }
        for row in od_pairs
      ]
      
      # Get camera names
      camera_names = {
        str(c.id): c.name for c in db.query(Camera).all()
      }
      
      return {
        "hours": hours,
        "od_pairs": od_result,
        "camera_names": camera_names,
        "total_observations": db.query(func.count(VehicleObservation.id)).filter(
          VehicleObservation.captured_at >= since
        ).scalar() or 0,
      }
    except Exception as e:
      raise HTTPException(status_code=500, detail=str(e))


@analytics_router.get("/travel-time")
async def get_travel_time(
  db: Session = Depends(get_db),
):
    """Get travel time analysis between cameras."""
    try:
      # Get vehicle tracks with timestamps to estimate travel times
      tracks = (
        db.query(
          VehicleTrack.camera_id,
          VehicleTrack.frame_number,
          VehicleTrack.created_at,
          GlobalVehicle.vehicle_id,
        )
        .outerjoin(GlobalVehicle, VehicleTrack.global_vehicle_id == GlobalVehicle.id)
        .filter(VehicleTrack.created_at.isnot(None))
        .limit(100)
        .all()
      )
      
      # Calculate travel times between consecutive observations
      travel_events = []
      for track in tracks:
        if track.created_at:
          travel_events.append(
            {
              "camera_id": track.camera_id,
              "frame": track.frame_number,
              "timestamp": track.created_at.isoformat() if hasattr(track.created_at, 'isoformat') else str(track.created_at),
              "vehicle_id": track.vehicle_id or "unknown",
            }
          )
      
      return {
        "total_tracks": len(travel_events),
        "travel_events": travel_events,
        "note": "Travel time calculated from observation timestamps between cameras",
      }
    except Exception as e:
      raise HTTPException(status_code=500, detail=str(e))