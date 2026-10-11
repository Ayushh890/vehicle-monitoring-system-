"""Origin-Destination analytics and travel-time anomaly detection.

Builds on the existing camera topology and trajectory engine to provide
city-wide traffic intelligence: OD matrices, ranked routes, and anomaly
detection based on historical travel-time baselines.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple

from collections import defaultdict

from sqlalchemy import func, and_

from backend.engine.trajectory_engine import (
    CameraTopologyEngine,
    TrajectoryPoint,
    GlobalVehicleTrajectory,
    MatchStatus,
)
from backend.ml.ocr.plate_ocr import PlateRead, PlateNormalizer
from backend.app.models import Camera, VehicleTrack, GlobalVehicle


def compute_od_matrix(
    trajectories: Dict[int, GlobalVehicleTrajectory],
    camera_names: Dict[int, str],
) -> List[Dict[str, Any]]:
    """Compute origin-destination matrix from trajectory data.

    Args:
        trajectories: Dict of global_vehicle_id -> GlobalVehicleTrajectory
        camera_names: Dict of camera_id -> camera name

    Returns:
        List of OD entries with origin, destination, and vehicle_count
    """
    od_counts: Dict[Tuple[int, int], int] = defaultdict(int)

    for _global_id, trajectory in trajectories.items():
        observations = trajectory.observations
        if len(observations) < 2:
            continue

        # Get origin and destination cameras (first and last observed cameras)
        origin_camera = observations[0].camera_id
        dest_camera = observations[-1].camera_id

        # Only count if origin and destination are different
        if origin_camera != dest_camera:
            od_counts[(origin_camera, dest_camera)] += 1

    # Build result list
    od_matrix = []
    for (origin_id, dest_id), count in od_counts.items():
        od_matrix.append(
            {
                "origin": {
                    "camera_id": origin_id,
                    "camera_name": camera_names.get(origin_id, f"Camera {origin_id}"),
                },
                "destination": {
                    "camera_id": dest_id,
                    "camera_name": camera_names.get(dest_id, f"Camera {dest_id}"),
                },
                "vehicle_count": count,
            }
        )

    # Sort by vehicle count descending
    od_matrix.sort(key=lambda x: x["vehicle_count"], reverse=True)

    return od_matrix


def compute_baseline_travel_time(
    topology_engine: CameraTopologyEngine,
    camera_a_id: int,
    camera_b_id: int,
    window_hours: int = 24,
) -> Optional[Dict[str, Any]]:
    """Compute baseline travel time between two cameras from historical observations.

    Args:
        topology_engine: CameraTopologyEngine with database access
        camera_a_id: Source camera ID
        camera_b_id: Destination camera ID
        window_hours: Historical window in hours

    Returns:
        Baseline travel time info or None if insufficient data
    """
    from sqlalchemy import select

    window_start = datetime.utcnow() - timedelta(hours=window_hours)

    # Get vehicle tracks that pass through camera A and then camera B
    # by matching global_vehicle_id sequences
    baseline_result = {"average_minutes": None, "median_minutes": None, "observations": 0}

    # Query all global vehicles with observations in the time window
    # that pass through both cameras
    subquery = (
        select(VehicleTrack.global_vehicle_id, VehicleTrack.camera_id, VehicleTrack.created_at)
        .where(VehicleTrack.created_at >= window_start)
        .subquery()
    )

    # Find vehicles that visited both cameras
    from sqlalchemy import outerjoin

    # Simplified approach: get all tracks and analyze sequences
    all_tracks = (
        topology_engine.db_session.query(VehicleTrack)
        .filter(VehicleTrack.created_at >= window_start)
        .all()
    )

    # Group by global_vehicle_id
    vehicle_sequences: Dict[int, List[VehicleTrack]] = defaultdict(list)
    for track in all_tracks:
        if track.global_vehicle_id is not None:
            vehicle_sequences[track.global_vehicle_id].append(track)

    # For each vehicle that went through both cameras, find the A->B segment
    travel_durations: List[float] = []

    for _vid, tracks_list in vehicle_sequences.items():
        # Sort by timestamp
        tracks_list.sort(key=lambda t: t.created_at)

        # Get the sequence of camera IDs
        camera_ids_seen = [t.camera_id for t in tracks_list]

        # Check if both cameras appear in sequence
        if camera_a_id not in camera_ids_seen or camera_b_id not in camera_ids_seen:
            continue

        # Find indices of A and B in the trajectory
        idx_a_list = [i for i, cid in enumerate(camera_ids_seen) if cid == camera_a_id]
        idx_b_list = [i for i, cid in enumerate(camera_ids_seen) if cid == camera_b_id]

        if not idx_a_list or not idx_b_list:
            continue

        # For each combination of A and B appearances, check if A comes before B
        for idx_a in idx_a_list:
            for idx_b in idx_b_list:
                # Only count if A appears before B in the trajectory
                if idx_a < idx_b:
                    # Get travel time between these two points
                    time_a = tracks_list[idx_a].created_at
                    time_b = tracks_list[idx_b].created_at

                    if time_a and time_b:
                        duration = (time_b - time_a).total_seconds() / 60.0  # minutes

                        # Reasonable travel time filter: 1 min to 2 hours
                        if 1.0 <= duration <= 120.0:
                            travel_durations.append(duration)

    if travel_durations:
        travel_durations.sort()
        n = len(travel_durations)
        baseline_result["average_minutes"] = round(sum(travel_durations) / n, 2)
        baseline_result["median_minutes"] = round(travel_durations[n // 2], 2)
        baseline_result["observations"] = n

        # Compute percentiles if enough data
        if n >= 20:
            idx_75 = int(0.75 * (n - 1))
            idx_25 = int(0.25 * (n - 1))
            baseline_result["p75_minutes"] = round(travel_durations[idx_75], 2)
            baseline_result["p25_minutes"] = round(travel_durations[idx_25], 2)

    # Only return baseline if we have sufficient observations
    if baseline_result["observations"] < 3:
        return None

    return baseline_result


def detect_travel_time_anomaly(
    current_travel_time: float,
    baseline: Dict[str, Any],
    confidence: float = 0.5,
) -> Optional[Dict[str, Any]]:
    """Detect if current travel time is anomalous compared to baseline.

    Uses IQR-based method: anomaly if current time exceeds P75 + 1.5*IQR
    (or falls below P25 - 1.5*IQR for unusually fast travel).

    Args:
        current_travel_time: Observed travel time in minutes
        baseline: Baseline dict from compute_baseline_travel_time
        confidence: Current confidence in the reading (0-1)

    Returns:
        Anomaly dict if anomalous, None if within normal range
    """
    if baseline is None:
        # Insufficient history - cannot detect anomalies
        return {
            "anomaly_type": "INSUFFICIENT_HISTORY",
            "current_travel_time": current_travel_time,
            "baseline_travel_time": None,
            "difference": None,
            "percentage_change": None,
            "confidence": 0.0,
            "reason": "Not enough historical data to establish baseline",
        }

    baseline_avg = baseline["average_minutes"]
    baseline_median = baseline.get("median_minutes", baseline_avg)
    p75 = baseline.get("p75_minutes", baseline_avg)
    p25 = baseline.get("p25_minutes", baseline_avg)
    observations = baseline.get("observations", 0)

    # Calculate difference from baseline
    difference = current_travel_time - baseline_avg
    pct_change = (difference / baseline_avg * 100) if baseline_avg > 0 else 0

    # IQR-based anomaly detection
    iqr = p75 - p25
    upper_threshold = p75 + 1.5 * iqr  # Anomaly if above this
    lower_threshold = p25 - 1.5 * iqr  # Anomaly if below this (unusually fast)

    anomaly_type = None
    is_anomaly = False
    severity = 0.0

    if current_travel_time > upper_threshold:
        # Significantly slower than normal - anomaly
        anomaly_type = "TRAVEL_TIME_ANOMALY"
        is_anomaly = True
        # Severity: how far above threshold, normalized
        severity = min(1.0, (current_travel_time - upper_threshold) / max(upper_threshold, 1.0) * 0.5 + 0.5)
    elif current_travel_time < lower_threshold and observations > 20:
        # Unusually fast - also flag as anomaly type
        anomaly_type = "UNUSUALLY_FAST_TRAVEL"
        is_anomaly = True
        severity = min(1.0, (lower_threshold - current_travel_time) / max(baseline_avg * 0.3, 1.0) * 0.5 + 0.5)
    else:
        # Within normal range
        is_anomaly = False
        severity = 0.0
        anomaly_type = None

    if is_anomaly:
        return {
            "anomaly_type": anomaly_type,
            "current_travel_time": round(current_travel_time, 2),
            "baseline_travel_time": round(baseline_avg, 2),
            "difference": round(difference, 2),
            "percentage_change": round(pct_change, 1),
            "confidence": round(min(confidence + 0.1, 1.0), 2),
            "baseline_observations": observations,
            "baseline_p25": round(p25, 2),
            "baseline_p75": round(p75, 2),
            "iqr": round(iqr, 2),
            "upper_threshold": round(upper_threshold, 2),
            "lower_threshold": round(lower_threshold, 2),
            "severity": round(severity, 2),
            "reason": (
                f"Travel time {round(current_travel_time - baseline_avg, 1)}min "
                f"({'slower' if difference > 0 else 'faster'} than baseline)"
            ),
        }

    return None


def get_travel_time_anomalies(
    topology_engine: "CameraTopologyEngine",
    current_travel_times: Dict[Tuple[int, int], float],
    baseline_cache: Optional[Dict[Tuple[int, int], Dict]] = None,
    window_hours: int = 24,
) -> Tuple[List[Dict[str, Any]], Dict[Tuple[int, int], Dict]]:
    """Detect travel-time anomalies for multiple camera pairs.

    Args:
        topology_engine: CameraTopologyEngine with database access
        current_travel_times: Dict of (camera_a_id, camera_b_id) -> current travel time in mins
        baseline_cache: Pre-computed baselines (None = compute new)
        window_hours: Historical baseline window

    Returns:
        Tuple of (anomalies list, baseline_cache dict)
    """
    if baseline_cache is None:
        baseline_cache = {}

    anomalies = []

    # Get camera names for display
    from backend.app.models import Camera

    try:
        all_cameras = (
            topology_engine.db_session.query(Camera)
            .filter(Camera.is_active == True)
            .all()
        )
        camera_name_map = {c.id: c.name for c in all_cameras}
    except Exception:
        camera_name_map = {}

    # Get all camera pairs that have current travel times
    for (camera_a_id, camera_b_id), current_tt in current_travel_times.items():
        # Get or compute baseline
        if (camera_a_id, camera_b_id) not in baseline_cache:
            baseline = compute_baseline_travel_time(
                topology_engine, camera_a_id, camera_b_id, window_hours
            )
            baseline_cache[(camera_a_id, camera_b_id)] = baseline
        else:
            baseline = baseline_cache[(camera_a_id, camera_b_id)]

        # Detect anomaly
        anomaly = detect_travel_time_anomaly(current_tt, baseline, confidence=0.7)
        if anomaly is not None:
            anomaly["camera_pair"] = {
                "from_camera_id": camera_a_id,
                "to_camera_id": camera_b_id,
                "from_camera_name": camera_name_map.get(camera_a_id),
                "to_camera_name": camera_name_map.get(camera_b_id),
            }
            anomalies.append(anomaly)

    # Filter out None anomalies (no anomaly detected)
    valid_anomalies = [a for a in anomalies if a is not None]

    return valid_anomalies, baseline_cache


def compute_congestion_score(
    vehicle_count: int,
    average_speed: Optional[float],
    baseline_vehicle_count: Optional[int] = None,
    baseline_average_speed: Optional[float] = None,
) -> Dict[str, Any]:
    """Compute congestion score from actual measurements.

    Score = speed_component (0 to 0.5) + volume_component (0 to 0.5)

    - speed_component: higher when average_speed is low (0 at >60km/h, 0.5 at <20km/h)
    - volume_component: higher when volume increased significantly

    Returns:
        Dict with congestion_score (0-1), level, and explanation
    """
    # Speed component: inversely related to speed
    # 0.5 when speed < 20 km/h (highly congested)
    # 0 when speed > 60 km/h (free flow)
    if average_speed is not None and average_speed > 0:
        speed_component = max(0, min(0.5, (60 - average_speed) / 40 * 0.5 + 0.25))
        # Clamp to 0-0.5 range
        speed_component = max(0, min(0.5, speed_component))
    else:
        speed_component = 0.25  # Neutral when no speed data

    # Volume component: based on change from baseline
    volume_component = 0.0
    if baseline_vehicle_count is not None and baseline_vehicle_count > 0:
        if vehicle_count > baseline_vehicle_count:
            pct_increase = (vehicle_count - baseline_vehicle_count) / baseline_vehicle_count * 100
            # 0.5 scale: 0 at 0% increase, 0.5 at >50% increase
            volume_component = min(0.5, max(0, 0.5 * pct_increase / 50))
        # If volume decreased, component is 0

    congestion_score = round(speed_component + volume_component, 2)

    # Determine level
    if congestion_score >= 0.6:
        level = "HIGH"
    elif congestion_score >= 0.3:
        level = "MEDIUM"
    elif congestion_score > 0:
        level = "LOW"
    else:
        level = "NONE"

    # Build explanation parts
    explanation_parts = []
    if speed_component > 0:
        explanation_parts.append(
            f"average speed {average_speed:.0f} km/h contributes {speed_component:.1f} to score"
        )
    if volume_component > 0:
        explanation_parts.append(
            f"volume change contributes {volume_component:.1f} to score"
        )

    explanation = ". ".join(explanation_parts) + "." if explanation_parts else "No significant factors"

    return {
        "congestion_score": congestion_score,
        "congestion_level": level,
        "speed_component": round(speed_component, 3),
        "volume_component": round(volume_component, 3),
        "average_speed": average_speed,
        "explanation": explanation,
    }


# Export all functions
__all__ = [
    "compute_od_matrix",
    "compute_baseline_travel_time",
    "detect_travel_time_anomaly",
    "get_travel_time_anomalies",
    "compute_congestion_score",
]