from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Dict, List, Optional, Any, Tuple

from app.db.session import get_db
from ..app.models import Camera, VehicleObservation, VehicleTrack, GlobalVehicle
from ..engine.od_anomaly import (
    compute_od_matrix,
    compute_baseline_travel_time,
    detect_travel_time_anomaly,
    get_travel_time_anomalies,
    compute_congestion_score,
)


od_anomaly_router = APIRouter(prefix="/api/analytics", tags=["advanced-analytics"])


@od_anomaly_router.get("/od-matrix")
async def get_od_matrix(
  hours: int = 1,
  db: Session = Depends(get_db),
):
    """Get origin-destination matrix for specified hours."""
    try:
      delta = timedelta(hours=hours)
      since = datetime.utcnow() - delta

      # Get camera names
      cameras = db.query(Camera).filter(Camera.enabled == True).all()
      camera_name_map = {c.id: c.name for c in cameras}

      # Get vehicle observations in the time window
      observations = (
          db.query(VehicleObservation)
          .filter(VehicleObservation.captured_at >= since)
          .all()
      )

      # Build trajectories from observations grouped by vehicle_id
      # (Using VehicleObservation which has vehicle_id)
      vehicle_sequences: Dict[int, List] = defaultdict(list)
      for obs in observations:
        if obs.vehicle_id is not None:
          vehicle_sequences[obs.vehicle_id].append(obs)

      # Build trajectory: first and last camera for each vehicle
      trajectories: Dict[int, Any] = {}
      from backend.engine.trajectory_engine import GlobalVehicleTrajectory

      for vid, obs_list in vehicle_sequences.items():
        # Sort by captured_at
        obs_list.sort(key=lambda o: o.captured_at)
        first_obs = obs_list[0]
        last_obs = obs_list[-1]

        # Create a simple trajectory object
        class SimpleTrajectory:
          def __init__(self, obs_list):
            self.observations = obs_list

        trajectories[vid] = SimpleTrajectory(obs_list)

      # Compute OD matrix
      od_matrix = compute_od_matrix(trajectories, camera_name_map)

      # Sort by vehicle count and limit
      od_matrix.sort(key=lambda x: x["vehicle_count"], reverse=True)

      return {
        "hours": hours,
        "od_matrix": od_matrix,
        "total_od_pairs": len(od_matrix),
        "total_vehicles": len(vehicle_sequences),
      }
    except Exception as e:
      raise HTTPException(status_code=500, detail=str(e))


@od_anomaly_router.get("/travel-time-anomalies")
async def get_travel_time_anomalies(
  window_hours: int = 24,
  db: Session = Depends(get_db),
):
    """Get travel-time anomalies compared to historical baseline."""
    try:
      from backend.engine.od_anomaly import get_travel_time_anomalies as detect_anomalies

      # Get current travel times from recent VehicleTrack data
      # Calculate travel times between camera pairs from recent tracks
      current_travel_times: Dict[Tuple[int, int], float] = {}

      # Get recent tracks grouped by camera pairs
      recent_cutoff = datetime.utcnow() - timedelta(hours=1)  # Last hour

      tracks = (
          db.query(VehicleTrack.camera_id, VehicleTrack.global_vehicle_id, VehicleTrack.created_at)
          .filter(VehicleTrack.created_at >= recent_cutoff)
          .all()
      )

      # Group by global_vehicle_id to find sequences
      from collections import defaultdict as dd
      vehicle_sequences: Dict[int, List] = dd(list)
      for track in tracks:
        if track.global_vehicle_id is not None:
          vehicle_sequences[track.global_vehicle_id].append(track)

      # For each vehicle sequence, find camera pairs and compute travel times
      for vid, seq in vehicle_sequences.items():
        # Sort by timestamp
        seq.sort(key=lambda t: t.created_at)

        # Get camera IDs in sequence
        cam_ids = [t.camera_id for t in seq]

        # Find consecutive camera pairs
        for i in range(len(cam_ids) - 1):
          cam_a = cam_ids[i]
          cam_b = cam_ids[i + 1]

          if cam_a is not None and cam_b is not None:
            # Check if we already have a travel time for this pair
            pair_key = (cam_a, cam_b)
            if pair_key in current_travel_times:
              # Average with existing
              existing = current_travel_times[pair_key]
              current_travel_times[pair_key] = (existing + (seq[-1].created_at - seq[0].created_at).total_seconds() / 60) / 2
            else:
              # Compute travel time for this segment
              duration = (seq[-1].created_at - seq[0].created_at).total_seconds() / 60.0
              if 1.0 <= duration <= 120.0:  # Reasonable range
                current_travel_times[pair_key] = duration

      # Detect anomalies using historical baseline
      anomalies, baseline_cache = detect_anomalies(
          topology_engine=None,  # Will use simplified approach
          current_travel_times=current_travel_times,
          baseline_cache=None,
          window_hours=window_hours,
      )

      # Attach camera names
      for anomaly in anomalies:
        if anomaly and "camera_pair" in anomaly:
          cn = camera_name_map
          anomaly["camera_pair"]["from_camera_name"] = cn.get(anomaly["camera_pair"]["from_camera_id"])
          anomaly["camera_pair"]["to_camera_name"] = cn.get(anomaly["camera_pair"]["to_camera_id"])

      return {
        "window_hours": window_hours,
        "anomalies": anomalies,
        "total_pairs_checked": len(current_travel_times),
        "anomaly_count": len([a for a in anomalies if a is not None]),
      }
    except Exception as e:
      raise HTTPException(status_code=500, detail=str(e))


@od_anomaly_router.get("/congestion")
async def get_congestion_endpoint(
  hours: int = 1,
  db: Session = Depends(get_db),
):
    """Get congestion analysis with score and explanation."""
    try:
      delta = timedelta(hours=hours)
      since = datetime.utcnow() - delta

      # Get vehicle observations in period
      vehicle_count = (
          db.query(func.count(VehicleObservation.id))
          .filter(VehicleObservation.captured_at >= since)
          .scalar() or 0
      )

      # Get average speed from VehicleTrack in period
      avg_speed_result = (
          db.func.avg(VehicleTrack.speed)
          .filter(
              and_(VehicleTrack.speed.isnot(None), VehicleTrack.created_at >= since)
          )
          .scalar()
      )
      average_speed = round(float(avg_speed_result), 2) if avg_speed_result else None

      # Get previous period for comparison
      prev_delta = timedelta(hours=hours)
      prev_since = datetime.utcnow() - (delta * 2)
      prev_vehicle_count = (
          db.query(func.count(VehicleObservation.id))
          .filter(
              and_(
                  VehicleObservation.captured_at >= prev_since,
                  VehicleObservation.captured_at < since,
              )
          )
          .scalar() or 0
      )

      # Get camera throughput
      camera_count = db.query(func.count(Camera.id)).scalar() or 1

      # Compute congestion score
      congestion_data = compute_congestion_score(
          vehicle_count=vehicle_count,
          average_speed=average_speed,
          baseline_vehicle_count=prev_vehicle_count,
          baseline_average_speed=None,  # Could compute separately
      )

      return {
        "hours": hours,
        "vehicle_count": vehicle_count,
        "average_speed": average_speed,
        "previous_period_vehicle_count": prev_vehicle_count,
        "volume_change_percent": round(
          (vehicle_count - prev_vehicle_count) / max(prev_vehicle_count, 1) * 100, 2
        ),
        "congestion": congestion_data,
        "camera_count": camera_count,
      }
    except Exception as e:
      raise HTTPException(status_code=500, detail=str(e))


@od_anomaly_router.get("/od-summary")
async def get_od_summary(
  hours: int = 1,
  db: Session = Depends(get_db),
):
    """Get OD summary with ranked routes."""
    try:
      delta = timedelta(hours=hours)
      since = datetime.utcnow() - delta

      from backend.engine.od_anomaly import compute_od_matrix

      # Get camera names
      cameras = db.query(Camera).filter(Camera.enabled == True).all()
      camera_name_map = {c.id: c.name for c in cameras}

      # Get observations
      observations = (
          db.query(VehicleObservation)
          .filter(VehicleObservation.captured_at >= since)
          .all()
      )

      # Build simple trajectories by vehicle_id
      from collections import defaultdict
      vehicle_sequences: Dict[int, List] = defaultdict(list)
      for obs in observations:
        if obs.vehicle_id is not None:
          vehicle_sequences[obs.vehicle_id].append(obs)

      # Build simple trajectory container
      class SimpleTrajectory:
        def __init__(self, obs_list):
          self.observations = obs_list

      trajectories: Dict[int, Any] = {}
      for vid, obs_list in vehicle_sequences.items():
        trajectories[vid] = SimpleTrajectory(obs_list)

      # Compute OD matrix
      od_matrix = compute_od_matrix(trajectories, camera_name_map)

      # Take top 10 routes
      top_routes = od_matrix[:10]

      return {
        "hours": hours,
        "total_routes": len(od_matrix),
        "top_routes": top_routes,
        "total_observed_vehicles": len(vehicle_sequences),
      }
    except Exception as e:
      raise HTTPException(status_code=500, detail=str(e))