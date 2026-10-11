"""Cross-camera global vehicle identity engine.

Matches vehicles observed by multiple cameras using multiple signals:
- Plate similarity (OCR text)
- Visual appearance embedding similarity
- Temporal feasibility (physically plausible travel time)
- Route feasibility (camera topology)
- Vehicle type agreement
- Color agreement

Supports configurable weighted scoring and produces MATCHED/POSSIBLE_MATCH/NO_MATCH
statuses with evidence tracking.
"""

import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple

import numpy as np

from backend.ml.ocr.plate_ocr import PlateRead, PlateNormalizer
from backend.models import GlobalVehicle, VehicleEmbedding, Camera, TrafficMetric


class MatchStatus:
    """Match result status enumeration."""
    MATCHED = "MATCHED"
    POSSIBLE_MATCH = "POSSIBLE_MATCH"
    NO_MATCH = "NO_MATCH"


class GlobalVehicleIdentityEngine:
    """Engine for matching vehicles across multiple cameras.

    Uses a weighted scoring system combining multiple signals:
    1. Plate/OCR similarity
    2. Visual appearance embedding similarity
    3. Temporal feasibility (travel time)
    4. Route feasibility (camera topology)
    5. Vehicle attribute agreement (type, color)

    The final confidence is a weighted sum of these component scores.
    """

    # Default weights for each signal type
    DEFAULT_WEIGHTS = {
        "plate_similarity": 0.30,
        "embedding_similarity": 0.25,
        "temporal_feasibility": 0.20,
        "route_feasibility": 0.15,
        "attribute_agreement": 0.10,
    }

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        max_travel_time_minutes: float = 60.0,
        plate_similarity_threshold: float = 0.8,
        embedding_similarity_threshold: float = 0.6,
    ) -> None:
        """Initialize the identity engine.

        Args:
            weights: Custom weights for each signal (overrides defaults if provided)
            max_travel_time_minutes: Maximum plausible travel time between cameras
            plate_similarity_threshold: Minimum plate similarity for consideration
            embedding_similarity_threshold: Minimum embedding similarity for consideration
        """
        self.weights = weights or self.DEFAULT_WEIGHTS
        self.max_travel_time_minutes = max_travel_time_minutes
        self.plate_similarity_threshold = plate_similarity_threshold
        self.embedding_similarity_threshold = embedding_similarity_threshold

        # Normalize weights to sum to 1.0
        total = sum(self.weights.values())
        self.weights = {k: v / total for k, v in self.weights.items()}

    def compute_plate_similarity(
        self, read_a: PlateRead, read_b: PlateRead
    ) -> Tuple[float, str]:
        """Compute plate similarity between two OCR readings.

        Uses normalized text comparison with fuzzy matching.

        Returns:
            (similarity_score, match_reason) where score is 0-1
        """
        raw_a = read_a.raw_text or ""
        raw_b = read_b.raw_text or ""
        norm_a = read_a.normalized_text or PlateNormalizer().normalize(raw_a) or ""
        norm_b = read_b.normalized_text or PlateNormalizer().normalize(raw_b) or ""

        if not norm_a or not norm_b:
            return 0.0, "no_plate_text"

        # Exact match
        if norm_a == norm_b:
            return 1.0, "exact_plate_match"

        # Check if one is substring of other (OCR typo case)
        if norm_a in norm_b or norm_b in norm_a:
            longer = norm_a if len(norm_a) > len(norm_b) else norm_b
            shorter = norm_b if len(norm_a) > len(norm_b) else norm_a
            ratio = len(shorter) / len(longer)
            if ratio >= 0.75:
                return round(ratio, 3), "ocr_typo_similar"
            return round(ratio, 3), "partial_match"

        # Character-level similarity using longest common subsequence
        lcs_length = self._lcs_length(norm_a, norm_b)
        max_len = max(len(norm_a), len(norm_b))
        if max_len == 0:
            return 0.0, "empty_plate_text"

        similarity = lcs_length / max_len
        if similarity >= 0.6:
            return round(similarity, 3), "character_similar"
        return round(similarity, 3), "no_plate_match"

    @staticmethod
    def _lcs_length(a: str, b: str) -> int:
        """Compute length of longest common subsequence."""
        m, n = len(a), len(b)
        # Use space-optimized DP
        prev = [0] * (n + 1)
        for i in range(1, m + 1):
            curr = [0] * (n + 1)
            for j in range(1, n + 1):
                if a[i - 1] == b[j - 1]:
                    curr[j] = prev[j - 1] + 1
                else:
                    curr[j] = max(prev[j], curr[j - 1])
            prev = curr
        return prev[n]

    def compute_embedding_similarity(
        self, emb_a: Optional[np.ndarray], emb_b: Optional[np.ndarray]
    ) -> Tuple[float, str]:
        """Compute visual embedding similarity between two vehicles.

        Uses cosine similarity between feature vectors.

        Returns:
            (similarity_score, match_reason) where score is 0-1
        """
        if emb_a is None or emb_b is None:
            return 0.0, "missing_embedding"

        # Normalize vectors
        na = emb_a / (np.linalg.norm(emb_a) + 1e-8)
        nb = emb_b / (np.linalg.norm(emb_b) + 1e-8)

        # Cosine similarity
        cosine = float(np.dot(na, nb))

        # Clamp to [-1, 1] then map to [0, 1]
        cosine = max(-1.0, min(1.0, cosine))
        similarity = (cosine + 1.0) / 2.0  # Map from [-1,1] to [0,1]

        if similarity >= 0.8:
            return round(similarity, 3), "high_appearance_match"
        elif similarity >= 0.6:
            return round(similarity, 3), "moderate_appearance_match"
        elif similarity > 0:
            return round(similarity, 3), "low_appearance_match"
        return 0.0, "no_appearance_match"

    def compute_temporal_feasibility(
        self,
        timestamp_a: datetime,
        timestamp_b: datetime,
        camera_a: "Camera",
        camera_b: "Camera",
    ) -> Tuple[float, str]:
        """Compute temporal feasibility (travel time plausibility).

        Checks if the time difference between two observations is
        physically plausible given the distance between cameras.

        Returns:
            (feasibility_score, match_reason) where score is 0-1
        """
        time_diff = abs((timestamp_b - timestamp_a).total_seconds()) / 60.0  # minutes

        if time_diff <= 0:
            return 0.0, "same_timestamp"

        # Get distance between cameras
        try:
            dist_km = self._compute_camera_distance_km(camera_a, camera_b)
        except Exception:
            dist_km = None

        # Maximum plausible speeds (km/h)
        max_speeds = {
            "highway": 120,
            "urban": 50,
            "local": 30,
        }

        # If no distance info, use moderate score based on time alone
        if dist_km is None:
            # Assume moderate distance, check if time is reasonable
            if time_diff <= 30:  # Within 30 minutes is reasonably plausible
                return round(1.0 - min(time_diff / 30.0, 1.0), 3), "reasonable_time_unknown_dist"
            return round(max(0, 1.0 - time_diff / 60.0), 3), "implausible_time_unknown_dist"

        # Compute maximum plausible travel time at different speeds
        max_time_highway = dist_km / max_speeds["highway"] * 60  # in minutes
        max_time_urban = dist_km / max_speeds["urban"] * 60
        max_time_local = dist_km / max_speeds["local"] * 60

        # The observed time should be at least minimally plausible
        if time_diff <= max_time_highway:
            # Very fast travel (highway)
            if time_diff <= max_time_urban:
                # Highway or urban
                if time_diff <= max_time_local:
                    # Very plausible
                    score = 1.0
                    reason = "plausible_travel"
                else:
                    # Too slow for local, maybe highway
                    ratio = max_time_local / time_diff
                    score = min(1.0, 0.8 + 0.2 * ratio)
                    reason = "plausible_highway"
            else:
                # Likely too slow for highway, maybe urban
                ratio = max_time_urban / time_diff
                score = min(1.0, 0.6 + 0.4 * ratio)
                reason = "plausible_urban"

        elif time_diff <= max_time_urban:
            # Too slow for highway, plausible for urban
            ratio = max_time_urban / time_diff
            score = min(1.0, 0.5 + 0.5 * ratio)
            reason = "plausible_urban_too_slow_for_highway"

        elif time_diff <= max_time_local:
            # Too slow for urban, plausible for local
            ratio = max_time_local / time_diff
            score = min(1.0, 0.3 + 0.7 * ratio)
            reason = "plausible_local"

        else:
            # Implausibly slow
            score = max(0, 0.1 * max_time_local / time_diff)
            reason = "implausible_travel_time"

        # Cap at 0 minimum
        score = max(0.0, min(1.0, score))
        return round(score, 3), reason

    def _compute_camera_distance_km(self, cam_a: "Camera", cam_b: "Camera") -> Optional[float]:
        """Compute approximate distance between two cameras in km.

        Uses Haversine formula on latitude/longitude if available.
        """
        try:
            from sqlalchemy import func

            # This would query the database, but for now use a simplified approach
            # In production, use PostGIS ST_Distance
            lat_a, lon_a = float(cam_a.latitude), float(cam_a.longitude) if cam_a.latitude and cam_a.longitude else (0, 0)
            lat_b, lon_b = float(cam_b.latitude), float(cam_b.longitude) if cam_b.latitude and cam_b.longitude else (0, 0)

            if lat_a == 0 or lon_a == 0 or lat_b == 0 or lon_b == 0:
                return None

            # Haversine formula
            R = 6371.0  # Earth radius in km
            phi_a = math.radians(lat_a)
            phi_b = math.radians(lat_b)
            delta_phi = math.radians(lat_b - lat_a)
            delta_lambda = math.radians(lon_b - lon_a)

            a = (math.sin(delta_phi / 2) ** 2 +
                 math.cos(phi_a) * math.cos(phi_b) * math.sin(delta_lambda / 2) ** 2)
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

            return round(R * c, 2)
        except (ValueError, TypeError, AttributeError):
            return None

    def compute_route_feasibility(
        self,
        camera_a: "Camera",
        camera_b: "Camera",
        camera_edges: Optional[List[Any]] = None,
    ) -> Tuple[float, str]:
        """Compute route feasibility based on camera topology.

        Checks if there's a direct or indirect connection between
        cameras in the known topology.

        Returns:
            (feasibility_score, match_reason) where score is 0-1
        """
        # If cameras are the same, fully feasible
        if camera_a.id == camera_b.id:
            return 1.0, "same_camera"

        # Check if direct edge exists
        if camera_edges:
            for edge in camera_edges:
                # edge could be (a_id, b_id) or have source/dest attributes
                src = getattr(edge, 'source_id', None) or getattr(edge, 'camera_a_id', None) or 0
                dst = getattr(edge, 'dest_id', None) or getattr(edge, 'camera_b_id', None) or 0
                if src == camera_a.id and dst == camera_b.id:
                    return 1.0, "direct_route_exists"
                # Reverse direction
                if src == camera_b.id and dst == camera_a.id:
                    return 1.0, "direct_route_exists_reverse"

        # No direct edge - check plausibility based on locations
        # If both cameras are on same road or nearby zones, moderate feasibility
        if camera_a.zone == camera_b.zone:
            return 0.7, "same_zone"

        # Different zones but same road name
        if camera_a.road_name and camera_b.road_name:
            if camera_a.road_name == camera_b.road_name:
                return 0.5, "same_road_different_zone"

        # No known connection
        return 0.1, "no_known_route"

    def compute_attribute_agreement(
        self,
        vehicle_type_a: Optional[str],
        vehicle_type_b: Optional[str],
        vehicle_color_a: Optional[str],
        vehicle_color_b: Optional[str],
    ) -> Tuple[float, str]:
        """Compute vehicle attribute agreement score.

        Returns:
            (agreement_score, match_reason) where score is 0-1
        """
        scores = []
        reasons = []

        # Vehicle type agreement
        if vehicle_type_a and vehicle_type_b:
            if vehicle_type_a.lower() == vehicle_type_b.lower():
                scores.append(1.0)
                reasons.append("type_match")
            else:
                # Check if they're in the same broader category
                broader_a = self._broader_category(vehicle_type_a)
                broader_b = self._broader_category(vehicle_type_b)
                if broader_a and broader_a == broader_b:
                    scores.append(0.6)
                    reasons.append("same_broader_type")
                else:
                    scores.append(0.0)
                    reasons.append("type_mismatch")
        else:
            # Missing type info - neutral score
            scores.append(0.5)
            reasons.append("missing_type_info")

        # Color agreement
        if vehicle_color_a and vehicle_color_b:
            if vehicle_color_a.lower() == vehicle_color_b.lower():
                scores.append(1.0)
                reasons.append("color_match")
            else:
                # Check for similar colors (e.g., both "silver" vs "gray")
                if self._colors_similar(vehicle_color_a, vehicle_color_b):
                    scores.append(0.7)
                    reasons.append("similar_color")
                else:
                    scores.append(0.3)
                    reasons.append("color_difference")
        else:
            scores.append(0.5)
            reasons.append("missing_color_info")

        if not scores:
            return 0.5, "no_attribute_info"

        agreement = sum(scores) / len(scores)
        primary_reason = reasons[0] if reasons else "unknown"
        return round(agreement, 3), primary_reason

    @staticmethod
    def _broader_category(vehicle_type: str) -> Optional[str]:
        """Get broader vehicle category for comparison."""
        mappings = {
            "car": "passenger",
            "motorcycle": "two_wheeler",
            "bus": "commercial",
            "truck": "commercial",
            "van": "commercial",
        }
        return mappings.get(vehicle_type.lower())

    @staticmethod
    def _colors_similar(color_a: str, color_b: str) -> bool:
        """Check if two color descriptions are similar."""
        # Simple direct comparison with some aliases
        color_a = color_a.lower().strip()
        color_b = color_b.lower().strip()

        similar_pairs = {
            ("silver", "gray"),
            ("gray", "silver"),
            ("black", "dark"),
            ("white", "cream"),
        }

        return (color_a, color_b) in similar_pairs or (color_b, color_a) in similar_pairs

    def compute_match_score(
        self,
        vehicle_a_data: Dict[str, Any],
        vehicle_b_data: Dict[str, Any],
        camera_a: "Camera",
        camera_b: "Camera",
        camera_edges: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:  
        """Compute the total match score between two vehicle observations.

        Combines all weighted signals into a final confidence score.

        Args:
            vehicle_a_data: Dict with plate_read, embedding, timestamp, vehicle_type, color
            vehicle_b_data: Dict with plate_read, embedding, timestamp, vehicle_type, color
            camera_a: Camera object A
            camera_b: Camera object B
            camera_edges: Known camera connectivity edges

        Returns:
            Dict with all component scores and final confidence
        """
        # 1. Plate similarity
        plate_a = vehicle_a_data.get("plate_read")
        plate_b = vehicle_b_data.get("plate_read")
        plate_score, plate_reason = self.compute_plate_similarity(plate_a, plate_b) if plate_a and plate_b else (0.0, "no_plate_data")

        # 2. Embedding similarity
        emb_a = vehicle_a_data.get("embedding")
        emb_b = vehicle_b_data.get("embedding")
        emb_score, emb_reason = self.compute_embedding_similarity(emb_a, emb_b)

        # 3. Temporal feasibility
        ts_a = vehicle_a_data.get("timestamp")
        ts_b = vehicle_b_data.get("timestamp")
        temp_score, temp_reason = self.compute_temporal_feasibility(ts_a, ts_b, camera_a, camera_b)

        # 4. Route feasibility
        route_score, route_reason = self.compute_route_feasibility(camera_a, camera_b, camera_edges)

        # 5. Attribute agreement
        vtype_a = vehicle_a_data.get("vehicle_type")
        vtype_b = vehicle_b_data.get("vehicle_type")
        color_a = vehicle_a_data.get("vehicle_color")
        color_b = vehicle_b_data.get("vehicle_color")
        attr_score, attr_reason = self.compute_attribute_agreement(vtype_a, vtype_b, color_a, color_b)

        # Weighted sum
        final_confidence = (
            self.weights["plate_similarity"] * plate_score +
            self.weights["embedding_similarity"] * emb_score +
            self.weights["temporal_feasibility"] * temp_score +
            self.weights["route_feasibility"] * route_score +
            self.weights["attribute_agreement"] * attr_score
        )

        # Determine match status
        if final_confidence >= 0.8:
            status = MatchStatus.MATCHED
        elif final_confidence >= 0.5:
            status = MatchStatus.POSSIBLE_MATCH
        else:
            status = MatchStatus.NO_MATCH

        # Build reason text
        reason_parts = []
        if plate_reason != "no_plate_data":
            reason_parts.append(f"plate:{plate_reason}")
        reason_parts.append(f"temp:{temp_reason}")
        reason_parts.append(f"route:{route_reason}")

        return {
            "plate_similarity": plate_score,
            "embedding_similarity": emb_score,
            "temporal_feasibility": temp_score,
            "route_feasibility": route_score,
            "attribute_agreement": attr_score,
            "final_confidence": round(final_confidence, 3),
            "match_status": status,
            "match_reason": " | ".join(reason_parts),
            "component_details": {
                "plate_similarity_reason": plate_reason,
                "embedding_similarity_reason": emb_reason,
                "temporal_feasibility_reason": temp_reason,
                "route_feasibility_reason": route_reason,
                "attribute_agreement_reason": attr_reason,
            },
        }

    def classify_match(
        self,
        vehicle_a_data: Dict[str, Any],
        vehicle_b_data: Dict[str, Any],
        camera_a: "Camera",
        camera_b: "Camera",
        camera_edges: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        """Classify a cross-camera vehicle match.

        Primary entry point for match classification.

        Returns:
            Dict with match status, confidence, and evidence
        """
        scores = self.compute_match_score(
            vehicle_a_data, vehicle_b_data, camera_a, camera_b, camera_edges)

        # Build evidence summary
        evidence = {
            "plate_raw_a": vehicle_a_data.get("plate_read", {}).raw_text if vehicle_a_data.get("plate_read") else None,
            "plate_raw_b": vehicle_b_data.get("plate_read", {}).raw_text if vehicle_b_data.get("plate_read") else None,
            "plate_norm_a": vehicle_a_data.get("plate_read", {}).normalized_text if vehicle_a_data.get("plate_read") else None,
            "plate_norm_b": vehicle_b_data.get("plate_read", {}).normalized_text if vehicle_b_data.get("plate_read") else None,
            "embedding_a_available": vehicle_a_data.get("embedding") is not None,
            "embedding_b_available": vehicle_b_data.get("embedding") is not None,
            "time_diff_minutes": abs(
                (vehicle_b_data.get("timestamp", datetime.now()) -
                 vehicle_a_data.get("timestamp", datetime.now())).total_seconds()
            ) / 60.0 if vehicle_a_data.get("timestamp") and vehicle_b_data.get("timestamp") else None,
        }

        result = {
            "match_status": scores["match_status"],
            "confidence": scores["final_confidence"],
            "evidence": evidence,
            "match_reason": scores["match_reason"],
            "component_details": scores["component_details"],
        }

        # Add matching metadata
        if "match_reason" in scores and scores["match_reason"]:
            result["reason_key"] = scores["match_reason"].split(" | ")[0]

        return result


# Export
__all__ = [
    "GlobalVehicleIdentityEngine",
    "MatchStatus",
]