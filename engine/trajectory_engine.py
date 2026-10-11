"""Camera topology and trajectory engine.

Manages camera connections as a graph and reconstructs vehicle
trajectories across multiple cameras.

Key components:
- Camera edges: directed/connections between cameras with travel time estimates
- Trajectory engine: reconstructs vehicle paths across cameras
- Validation: time ordering, connectivity, physically plausible travel
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict

import numpy as np

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    ForeignKey,
    Text,
    Index,
    CheckConstraint,
)


# ============================================================
# Database Models for Camera Topology
# ============================================================


class CameraEdge(TimeStampedModel, Base):
    """Represents a directed camera connection with travel time estimates.

    Each edge represents a plausible movement path between two cameras,
    typically on the same road or in sequence.
    """

    __tablename__ = "camera_edges"

    id = Column(Integer, primary_key=True)
    source_camera_id = Column(
        Integer, ForeignKey("cameras.id"), nullable=False
    )
    dest_camera_id = Column(
        Integer, ForeignKey("cameras.id"), nullable=False
    )
    road_name = Column(String(255), nullable=True)
    direction = Column(String(20), nullable=True)  # N, S, E, W, NE, etc.

    # Travel time estimates (minutes)
    estimated_min_travel_time = Column(Float, nullable=False, default=1.0)
    estimated_normal_travel_time = Column(Float, nullable=False, default=2.0)
    max_travel_time = Column(Float, nullable=False, default=5.0)

    # Operational info
    is_bidirectional = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)

    __table_args__ = (
        Index("ix_camera_edges_source", "source_camera_id"),
        Index("ix_camera_edges_dest", "dest_camera_id"),
        Index("ix_camera_edges_route", "source_camera_id", "dest_camera_id"),
        Index("ix_camera_edges_active", "is_active"),
        CheckConstraint(
            "estimated_min_travel_time > 0",
            name="chk_edge_travel_time_positive",
        ),
        CheckConstraint(
            "estimated_normal_travel_time >= estimated_min_travel_time",
            name="chk_edge_normal_ge_min",
        ),
    )


@dataclass
class TrajectoryPoint:
    """A single point in a vehicle trajectory."""

    camera_id: int
    camera_name: str
    timestamp: datetime
    # Position within camera frame (optional)
    point_2d: Optional[Tuple[float, float]] = None
    # Detection confidence at this point
    detection_confidence: Optional[float] = None
    # Plate read if available
    plate_number: Optional[str] = None
    # Vehicle type if known
    vehicle_type: Optional[str] = None


@dataclass
class TrajectorySegment:
    """A segment of trajectory between two cameras."""

    from_camera_id: int
    to_camera_id: int
    from_timestamp: datetime
    to_timestamp: datetime
    # Estimated travel distance (km)
    estimated_distance_km: Optional[float] = None
    # Confidence in this segment (0-1)
    segment_confidence: float = 1.0
    # Reason for inclusion/acceptance
    match_reason: str = "plausible"


@dataclass
class GlobalVehicleTrajectory:
    """Complete trajectory for a global vehicle ID."""

    global_vehicle_id: int
    observations: List[TrajectoryPoint]
    segments: List[TrajectorySegment]
    # Overall trajectory confidence (0-1)
    trajectory_confidence: float = 1.0
    # Summary match reason
    match_reason: str = "reconstructed"
    # Number of camera transitions
    num_transitions: int = 0
    # Total travel time (minutes)
    total_travel_time_minutes: float = 0.0


class CameraTopologyEngine:
    """Manages camera connections and validates trajectory feasibility.

    Treats cameras as nodes in a graph, with camera_edges as directed edges.
    Validates that vehicle trajectories respect both temporal and topological
    constraints of the camera network.
    """

    def __init__(self, db_session=None):
        self.db_session = db_session

    def add_edge(
        self,
        source_camera_id: int,
        dest_camera_id: int,
        road_name: str = "",
        direction: str = "",
        min_travel_time: float = 1.0,
        normal_travel_time: float = 2.0,
        max_travel_time: float = 5.0,
        bidirectional: bool = False,
    ) -> CameraEdge:
        """Add a camera connection edge.

        Args:
            source_camera_id: ID of the source camera
            dest_camera_id: ID of the destination camera
            road_name: Name of the road connecting them
            direction: Primary direction of travel
            min_travel_time: Minimum estimated travel time (minutes)
            normal_travel_time: Normal estimated travel time (minutes)
            max_travel_time: Maximum plausible travel time (minutes)
            bidirectional: Whether the connection works both ways

        Returns:
            Created CameraEdge object
        """
        from backend.app.models import CameraEdge as EdgeModel

        edge = EdgeModel(
            source_camera_id=source_camera_id,
            dest_camera_id=dest_camera_id,
            road_name=road_name,
            direction=direction,
            estimated_min_travel_time=min_travel_time,
            estimated_normal_travel_time=normal_travel_time,
            max_travel_time=max_travel_time,
            is_bidirectional=bidirectional,
        )

        if self.db_session:
            self.db_session.add(edge)
            self.db_session.commit()

        return edge

    def remove_edge(self, edge_id: int) -> bool:
        """Remove a camera connection edge.

        Returns True if removed, False if not found.
        """
        from backend.app.models import CameraEdge as EdgeModel

        edge = self.db_session.query(EdgeModel).get(edge_id) if self.db_session else None
        if edge:
            self.db_session.delete(edge)
            self.db_session.commit()
            return True
        return False

    def get_camera_edges(self, camera_id: int = None) -> List[Any]:
        """Get camera edges, optionally filtered by camera.

        Returns edges where camera is source or destination.
        """
        from backend.app.models import CameraEdge as EdgeModel

        if camera_id:
            edges = (
                self.db_session.query(EdgeModel)
                .filter(
                    (EdgeModel.source_camera_id == camera_id)
                    | (EdgeModel.dest_camera_id == camera_id)
                )
                .all()
            )
        else:
            edges = self.db_session.query(EdgeModel).filter(
                EdgeModel.is_active == True
            ).all()

        return edges

    def validate_trajectory(
        self,
        points: List[TrajectoryPoint],
        camera_edges: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        """Validate a vehicle trajectory against topology and temporal constraints.

        Args:
            points: List of trajectory points in chronological order
            camera_edges: Known camera connections (loaded if None)

        Returns:
            Validation result dict with:
                - valid: bool
                - reason: str
                - segments: List of validated segments
                - confidence: float 0-1
                - errors: List of error strings
        """
        if not points:
            return {
                "valid": False,
                "reason": "empty_trajectory",
                "segments": [],
                "confidence": 0.0,
                "errors": ["No trajectory points provided"],
            }

        if camera_edges is None:
            camera_edges = self.get_camera_edges()

        errors = []
        validated_segments = []
        total_travel_time = 0.0
        high_confidence_count = 0

        # Sort points by timestamp to ensure chronological order
        sorted_points = sorted(points, key=lambda p: p.timestamp)

        # Check that we have at least 2 points for a meaningful trajectory
        if len(sorted_points) < 2:
            return {
                "valid": False,
                "reason": "insufficient_points",
                "segments": [],
                "confidence": 0.0,
                "errors": ["Need at least 2 trajectory points"],
            }

        # Validate each consecutive pair
        for i in range(len(sorted_points) - 1):
            point_a = sorted_points[i]
            point_b = sorted_points[i + 1]

            # Find connecting edge
            edge = self._find_edge(
                point_a.camera_id, point_b.camera_id, camera_edges
            )

            # Compute travel time
            time_diff = (point_b.timestamp - point_a.timestamp).total_seconds() / 60.0

            # Determine segment confidence
            if edge:
                # Check if travel time is within plausible range
                min_ok = time_diff >= edge.estimated_min_travel_time
                max_ok = time_diff <= edge.max_travel_time

                if min_ok and max_ok:
                    # Fully plausible
                    segment_confidence = 1.0
                    reason = "plausible_travel_time"
                    high_confidence_count += 1
                elif min_ok and not max_ok:
                    # Too slow (exceeds max) or too fast (below min but still positive)
                    segment_confidence = 0.5
                    reason = "travel_time_out_of_range"
                else:
                    # implausible - too much time or negative
                    segment_confidence = 0.1
                    reason = "implausible_travel"

                # Build segment
                segment = TrajectorySegment(
                    from_camera_id=point_a.camera_id,
                    to_camera_id=point_b.camera_id,
                    from_timestamp=point_a.timestamp,
                    to_timestamp=point_b.timestamp,
                    estimated_distance_km=self._estimate_segment_distance(
                        point_a, point_b, edge
                    ),
                    segment_confidence=segment_confidence,
                    match_reason=reason,
                )

                total_travel_time += time_diff
                validated_segments.append(segment)

            else:
                # No direct edge found
                # Check if cameras are in same zone or have some connection
                zone_conn = self._check_zone_connection(point_a, point_b)
                if zone_conn:
                    segment_confidence = zone_conn
                    reason = "same_zone_connection"
                else:
                    segment_confidence = 0.1
                    reason = "no_known_connection"

                segment = TrajectorySegment(
                    from_camera_id=point_a.camera_id,
                    to_camera_id=point_b.camera_id,
                    from_timestamp=point_a.timestamp,
                    to_timestamp=point_b.timestamp,
                    estimated_distance_km=None,
                    segment_confidence=segment_confidence,
                    match_reason=reason,
                )

                validated_segments.append(segment)
                errors.append(
                    f"No camera edge between cameras {point_a.camera_id} and {point_b.camera_id}"
                )

        # Compute overall trajectory confidence
        if validated_segments:
            avg_confidence = sum(
                s.segment_confidence for s in validated_segments
            ) / len(validated_segments)
            trajectory_confidence = round(avg_confidence, 3)
            num_transitions = len(validated_segments)
        else:
            trajectory_confidence = 0.0
            num_transitions = 0

        # Determine overall validity
        hard_errors = [e for e in errors if "implausible" in e.lower() or "impossible" in e.lower()]
        
        if hard_errors:
            valid = False
            reason = "; ".join(hard_errors[:2])  # Cap at 2 error summaries
        elif not validated_segments:
            valid = False
            reason = "no_valid_segments"
        elif trajectory_confidence >= 0.7:
            valid = True
            reason = "plausible_trajectory"
        elif trajectory_confidence >= 0.4:
            valid = True
            reason = "possible_trajectory"
        else:
            valid = False
            reason = "low_confidence_trajectory"

        return {
            "valid": valid,
            "reason": reason,
            "segments": validated_segments,
            "confidence": trajectory_confidence,
            "errors": errors,
            "num_transitions": num_transitions,
            "total_travel_time_minutes": round(total_travel_time, 2),
            "high_confidence_segments": high_confidence_count,
        }

    def _find_edge(
        self, source_id: int, dest_id: int, camera_edges: List[Any]
    ) -> Optional[Any]:
        """Find a camera edge from source to destination."""
        for edge in camera_edges:
            # Check both directions and attributes
            src = getattr(edge, 'source_camera_id', None) or getattr(edge, 'camera_a_id', None) or 0
            dst = getattr(edge, 'dest_camera_id', None) or getattr(edge, 'camera_b_id', None) or 0
            if src == source_id and dst == dest_id:
                return edge
            # Reverse if bidirectional
            if getattr(edge, 'is_bidirectional', False):
                if src == dest_id and dst == source_id:
                    return edge
        return None

    def _estimate_segment_distance(
        self, point_a: TrajectoryPoint, point_b: TrajectoryPoint,
        edge: Any,
    ) -> Optional[float]:
        """Estimate travel distance between two trajectory points.

        Uses camera edge road_name if available, otherwise returns None.
        """
        road = getattr(edge, 'road_name', None)
        if road:
            # Return a rough estimate based on typical distances
            # between cameras on same road
            return 5.0  # placeholder km
        return None

    def _check_zone_connection(
        self, point_a: TrajectoryPoint, point_b: TrajectoryPoint
    ) -> Optional[float]:
        """Check if cameras are in same or connected zones.

        Returns a confidence score (0-1) or None.
        """
        from backend.app.models import Camera

        # Query cameras from DB
        cam_a = self.db_session.query(Camera).get(point_a.camera_id) if self.db_session else None
        cam_b = self.db_session.query(Camera).get(point_b.camera_id) if self.db_session else None

        if not cam_a or not cam_b:
            return None

        if cam_a.zone == cam_b.zone:
            return 0.7  # same zone
        if cam_a.road_name and cam_b.road_name:
            if cam_a.road_name == cam_b.road_name:
                return 0.5  # same road different zone
        return None

    def reconstruct_trajectory(
        self,
        global_vehicle_id: int,
        observations: List[Dict[str, Any]],
        camera_edges: Optional[List[Any]] = None,
    ) -> GlobalVehicleTrajectory:
        """Reconstruct a complete trajectory for a global vehicle.

        Args:
            global_vehicle_id: The global vehicle identifier
            observations: List of observation dicts with camera_id, timestamp, etc.
            camera_edges: Known camera connections

        Returns:
            GlobalVehicleTrajectory with points, segments, and confidence
        """
        if camera_edges is None:
            camera_edges = self.get_camera_edges()

        # Convert observations to TrajectoryPoints
        points = []
        for obs in observations:
            point = TrajectoryPoint(
                camera_id=obs.get("camera_id", 0),
                camera_name=obs.get("camera_name", ""),
                timestamp=obs.get("timestamp", datetime.now()),
                point_2d=obs.get("point_2d"),
                detection_confidence=obs.get("detection_confidence"),
                plate_number=obs.get("plate_number"),
                vehicle_type=obs.get("vehicle_type"),
            )
            points.append(point)

        # Validate and sort
        validation = self.validate_trajectory(points, camera_edges)

        # Build segments from validated segments
        segments = validation.get("segments", [])

        # Count transitions
        num_transitions = validation.get("num_transitions", 0)

        # Compute total travel time
        total_travel = validation.get("total_travel_time_minutes", 0.0)

        # Build trajectory points list for return
        trajectory_points = validation  # reuse validation info

        # Determine match reason based on validation
        reason = validation.get("reason", "reconstructed")

        return GlobalVehicleTrajectory(
            global_vehicle_id=global_vehicle_id,
            observations=points,
            segments=segments,
            trajectory_confidence=validation.get("confidence", 0.0),
            match_reason=reason,
            num_transitions=num_transitions,
            total_travel_time_minutes=total_travel,
        )

    def get_trajectory_api_response(
        self, global_vehicle_id: int,
    ) -> Dict[str, Any]:
        """Generate API response for vehicle trajectory.

        This would be used by: GET /api/vehicles/{id}/trajectory
        """
        # Query the global vehicle from DB
        from backend.app.models import GlobalVehicle

        global_vehicle = (
            self.db_session.query(GlobalVehicle)
            .filter(GlobalVehicle.id == global_vehicle_id)
            .first()
        )

        if not global_vehicle:
            return {
                "error": "vehicle_not_found",
                "global_vehicle_id": global_vehicle_id,
            }

        # Build trajectory from stored observations
        # (In production, this would reconstruct from DB-stored data)
        trajectory = {
            "global_vehicle_id": global_vehicle_id,
            "vehicles_seen": global_vehicle.vehicle_count if hasattr(global_vehicle, 'vehicle_count') else 0,
            "first_observation": (
                global_vehicle.first_observation.isoformat()
                if global_vehicle and global_vehicle.first_observation
                else None
            ),
            "last_observation": (
                global_vehicle.last_observation.isoformat()
                if global_vehicle and global_vehicle.last_observation
                else None
            ),
            "total_observations": global_vehicle.total_observations if hasattr(global_vehicle, 'total_observations') else 0,
            "match_status": global_vehicle.match_status if hasattr(global_vehicle, 'match_status') else None,
        }

        return trajectory