"""Temporal OCR fusion service.

Combines OCR readings from multiple frames for the same tracked vehicle
to produce a final, more reliable plate candidate.

Architecture:
- Maintains a sliding window of recent PlateRead observations per track_id
- Uses voting to determine the most consistent plate text
- Weights readings by OCR confidence
- Handles temporal decay (older readings have less influence)
"""

import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

import numpy as np

from backend.ml.ocr.plate_ocr import PlateRead


@dataclass
class OCRReading:
    """A single OCR reading with timing information."""
    track_id: int
    plate_read: PlateRead
    timestamp: float
    confidence: float


class TemporalOCRFusion:
    """Fuses multiple OCR readings over time for the same vehicle.

    Uses a confidence-weighted voting system to determine the most likely
    plate number from multiple frames.
    """

    def __init__(
        self,
        window_size: int = 10,
        confidence_weight: float = 0.7,
        temporal_decay: float = 0.95,
        min_readings: int = 2,
    ) -> None:
        """Initialize temporal OCR fusion.

        Args:
            window_size: Maximum number of recent readings to keep per track
            confidence_weight: How much weight to give confidence (0-1)
            temporal_decay: Decay factor per frame (0-1), 1 = no decay
            min_readings: Minimum readings before fusion produces result
        """
        self.window_size = window_size
        self.confidence_weight = confidence_weight
        self.temporal_decay = temporal_decay
        self.min_readings = min_readings

        # Store readings per track_id: {track_id: [OCRReading, ...]}
        self._readings: Dict[int, List[OCRReading]] = defaultdict(list)

        # Store fused results: {track_id: str}
        self._fused: Dict[int, str] = {}

    def add_reading(self, track_id: int, plate_read: PlateRead, timestamp: float) -> None:
        """Add a new OCR reading for a tracked vehicle.

        Args:
            track_id: Tracker ID for the vehicle
            plate_read: The PlateRead result from current frame
            timestamp: Current frame timestamp
        """
        # Create reading with confidence
        confidence = plate_read.ocr_confidence if plate_read else 0.0
        reading = OCRReading(
            track_id=track_id,
            plate_read=plate_read,
            timestamp=timestamp,
            confidence=confidence,
        )

        # Add to window, maintain size
        readings = self._readings[track_id]
        readings.append(reading)

        # Remove oldest if over window size
        if len(readings) > self.window_size:
            readings = readings[-self.window_size:]
            self._readings[track_id] = readings

        # Re-fuse after adding new reading
        self._fuse_track(track_id)

    def _fuse_track(self, track_id: int) -> Optional[str]:
        """Fuse all readings for a track into a final plate candidate.

        Args:
            track_id: Tracker ID to fuse

        Returns:
            Normalized plate text if enough readings, None otherwise
        """
        readings = self._readings.get(track_id, [])

        # Check minimum readings
        if len(readings) < self.min_readings:
            # Clear fused result if not enough readings
            if track_id in self._fused:
                del self._fused[track_id]
            return None

        # Apply temporal decay to weights
        decayed_readings = self._apply_temporal_decay(track_id, readings)

        # Vote on plate text using confidence-weighted voting
        fused = self._confidence_weighted_vote(decayed_readings)

        # Store the fused result
        self._fused[track_id] = fused

        return fused

    def _apply_temporal_decay(
        self, track_id: int, readings: List[OCRReading]
    ) -> List[OCRReading]:
        """Apply temporal decay to reading weights.

        Newer readings have higher weight, older readings decay.
        """
        if not readings:
            return readings

        # Sort by timestamp (newest first)
        sorted_readings = sorted(readings, key=lambda r: r.timestamp, reverse=True)

        decayed = []
        for i, reading in enumerate(sorted_readings):
            # Decay based on position in sequence
            decay_factor = self.temporal_decay ** i
            effective_confidence = reading.confidence * decay_factor

            decayed_reading = type(reading)(
                track_id=reading.track_id,
                plate_read=reading.plate_read,
                timestamp=reading.timestamp,
                confidence=effective_confidence,
            )
            decayed.append(decayed_reading)

        return decayed

    def _confidence_weighted_vote(
        self, readings: List[OCRReading]
    ) -> Optional[str]:
        """Perform confidence-weighted voting to determine plate text.

        Each reading votes for its plate text, weighted by its confidence.
        The text with the highest total weight wins.
        """
        if not readings:
            return None

        # Vote accumulator: {plate_text: total_weight}
        votes: Dict[str, float] = {}
        total_weight = 0.0

        for reading in readings:
            plate_text = reading.plate_read.normalized_text or reading.plate_read.raw_text

            if not plate_text or len(plate_text) < 3:
                continue

            # Weight = confidence * (1 + normalization_bonus)
            # Readings with normalized text get slight boost
            normalization_bonus = 0.1 if plate_text == (
                reading.plate_read.normalized_text or ""
            ) else 0.0

            weight = reading.confidence + normalization_bonus

            if plate_text in votes:
                votes[plate_text] += weight
            else:
                votes[plate_text] = weight

            total_weight += weight

        if not votes or total_weight == 0:
            return None

        # Find plate with highest total weight
        best_plate = max(votes, key=votes.get)
        best_weight = votes[best_plate]

        # Normalize confidence to 0-1 range
        normalized_confidence = min(best_weight / total_weight, 1.0) if total_weight > 0 else 0.0

        # Only return if confidence is above threshold
        if normalized_confidence >= 0.3:  # 30% minimum confidence
            return best_plate

        return None

    def get_fused_result(self, track_id: int) -> Optional[Dict[str, Any]]:
        """Get the fused OCR result for a track.

        Args:
            track_id: Tracker ID

        Returns:
            Dict with plate_text and confidence, or None
        """
        fused_text = self._fused.get(track_id)
        if fused_text is None:
            return None

        # Find the confidence from readings
        readings = self._readings.get(track_id, [])
        if not readings:
            return {"plate_text": fused_text, "ocr_confidence": 0.0}

        # Use the most recent reading's confidence as reference
        latest_confidence = readings[-1].ocr_confidence if readings else 0.0

        return {
            "plate_text": fused_text,
            "ocr_confidence": latest_confidence,
            "reading_count": len(readings),
        }

    def get_reading_count(self, track_id: int) -> int:
        """Get the number of readings accumulated for a track.

        Args:
            track_id: Tracker ID

        Returns:
            Number of accumulated readings
        """
        return len(self._readings.get(track_id, []))

    def reset_track(self, track_id: int) -> None:
        """Reset all readings and fused result for a track.

        Called when a track is destroyed or reidentified.
        """
        if track_id in self._readings:
            del self._readings[track_id]
        if track_id in self._fused:
            del self._fused[track_id]


# Export
__all__ = [
    "TemporalOCRFusion",
    "OCRReading",
    "PlateRead",
]