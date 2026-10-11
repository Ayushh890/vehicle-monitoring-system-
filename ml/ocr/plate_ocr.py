"""Plate OCR service for license plate detection and character recognition.

Modular pipeline:
- PlateDetector: detect plate region in vehicle crop
- PlatePreprocessor: enhance plate image for OCR
- PlateOCR: perform character recognition
- PlateNormalizer: normalize/format OCR results
"""

import re
import numpy as np
from typing import Optional, Tuple, List, Dict, Any


class PlateRead:
    """Result of plate OCR processing.

    Stores both raw OCR output and normalized result.
    """

    def __init__(
        self,
        camera_id: int,
        frame_id: int,
        track_id: Optional[int],
        timestamp: float,
        raw_text: str,
        normalized_text: Optional[str],
        ocr_confidence: float,
        plate_bbox: Tuple[float, float, float, float],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.camera_id = camera_id
        self.frame_id = frame_id
        self.track_id = track_id
        self.timestamp = timestamp
        self.raw_text = raw_text
        self.normalized_text = normalized_text
        self.ocr_confidence = ocr_confidence
        self.plate_bbox = plate_bbox  # (x1, y1, x2, y2) in pixel coords
        self.metadata = metadata or {}

    @property
    def display_text(self) -> str:
        """Return the text to display - normalized if available, else raw."""
        return self.normalized_text if self.normalized_text else self.raw_text

    @property
    def is_valid(self) -> bool:
        """Check if the OCR result has sufficient confidence."""
        return self.ocr_confidence >= 0.5

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database/storage."""
        return {
            "camera_id": self.camera_id,
            "frame_id": self.frame_id,
            "track_id": self.track_id,
            "timestamp": self.timestamp,
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "ocr_confidence": self.ocr_confidence,
            "plate_bbox": self.plate_bbox,
            "metadata": self.metadata,
        }


class PlateDetector:
    """Detects license plate region within a vehicle crop.

    Uses color-based segmentation and contour detection to find
    the plate region. Designed to work on vehicle crops from the
    tracker, not full frames.
    """

    def detect(self, vehicle_crop: np.ndarray) -> Optional[Tuple[np.ndarray, Tuple[int, int, int, int]]]:
        """Detect plate region in a vehicle crop.

        Args:
            vehicle_crop: BGR image crop containing a vehicle

        Returns:
            Tuple of (plate_image, bbox) or None if no plate found
            bbox is (x1, y1, x2, y2) in crop coordinates
        """
        if vehicle_crop.size == 0:
            return None

        try:
            # Convert to HSV for color segmentation
            hsv = cv2.cvtColor(vehicle_crop, cv2.COLOR_BGR2HSV)

            # License plates typically have dark background with light characters
            # Common: white on dark (black, navy, dark gray) or yellow on dark
            lower_white = np.array([0, 0, 200])
            upper_white = np.array([180, 30, 255])

            lower_yellow = np.array([20, 100, 100])
            upper_yellow = np.array([35, 255, 255])

            lower_dark = np.array([0, 0, 50])
            upper_dark = np.array([180, 255, 150])

            # Create color masks
            white_mask = cv2.inRange(hsv, lower_white, upper_white)
            yellow_mask = cv2.inRange(hsv, lower_yellow, upper_yellow)
            dark_mask = cv2.inRange(hsv, lower_dark, upper_dark)

            # Combine masks
            combined_mask = cv2.bitwise_or(cv2.bitwise_or(white_mask, yellow_mask), dark_mask)

            # Morphological operations to clean up
            kernel = np.ones((3, 3), np.uint8)
            combined_mask = cv2.morphologyEx(combined_mask, cv2.MORPH_OPEN, kernel)
            combined_mask = cv2.morphologyEx(combined_mask, cv2.MORPH_CLOSE, kernel)

            # Find contours
            contours, _ = cv2.findContours(
                combined_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )

            if not contours:
                return None

            # Filter contours by area and aspect ratio
            plate_candidates = []
            h, w = vehicle_crop.shape[:2]

            for cnt in contours:
                area = cv2.contourArea(cnt)
                if area < 500 or area > w * h * 0.8:
                    continue

                x, y, bw, bh = cv2.boundingRect(cnt)
                aspect_ratio = bw / bh if bh > 0 else 0

                # License plates typically have aspect ratio between 2:1 and 6:1
                if aspect_ratio < 2.0 or aspect_ratio > 6.0:
                    continue

                # Plate should not span entire image
                if bw > w * 0.7 or bh > h * 0.7:
                    continue

                plate_candidates.append((area, (x, y, x + bw, y + bh)))

            if not plate_candidates:
                return None

            # Sort by area, take largest
            plate_candidates.sort(key=lambda x: x[0], reverse=True)
            _, best_bbox = plate_candidates[0]

            # Extract plate region
            x1, y1, x2, y2 = best_bbox
            # Add some padding
            pad_x = int((x2 - x1) * 0.1)
            pad_y = int((y2 - y1) * 0.1)
            x1 = max(0, x1 - pad_x)
            y1 = max(0, y1 - pad_y)
            x2 = min(w, x2 + pad_x)
            y2 = min(h, y2 + pad_y)

            plate_image = vehicle_crop[y1:y2, x1:x2]

            if plate_image.size == 0:
                return None

            return plate_image, best_bbox

        except Exception as e:
            # Log error but return None - don't crash the pipeline
            import logging
            logging.getLogger(__name__).debug(f"Plate detection error: {e}")
            return None


class PlatePreprocessor:
    """Preprocesses plate image for OCR enhancement."""

    def preprocess(self, plate_image: np.ndarray) -> np.ndarray:
        """Enhance plate image for OCR.

        Args:
            plate_image: Raw plate region in BGR

        Returns:
            Preprocessed grayscale image optimized for OCR
        """
        if plate_image.size == 0:
            return np.array([])

        try:
            # Convert to grayscale
            gray = cv2.cvtColor(plate_image, cv2.COLOR_BGR2GRAY)

            # Apply bilateral filter to reduce noise while preserving edges
            gray = cv2.bilateralFilter(gray, 9, 75, 75)

            # Adaptive thresholding to handle varying lighting
            thresh = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
            )

            # Invert if background is dark characters on light (common)
            # Check: if most pixels are dark, we might need to invert
            dark_pixels = np.sum(thresh < 128)
            total_pixels = thresh.size
            dark_ratio = dark_pixels / total_pixels if total_pixels > 0 else 0

            # Invert if dark ratio is high (dark background, light chars)
            if dark_ratio > 0.6:
                thresh = cv2.bitwise_not(thresh)

            # Resize to standard OCR size while maintaining aspect ratio
            h, w = thresh.shape
            target_height = 32
            ratio = target_height / h
            new_w = int(w * ratio)
            new_w = max(new_w, 32)  # minimum width
            thresh = cv2.resize(thresh, (new_w, target_height), interpolation=cv2.INTER_CUBIC)

            # Add slight dilation to make characters bolder
            kernel = np.ones((2, 2), np.uint8)
            thresh = cv2.dilate(thresh, kernel, iterations=1)

            # Normalize brightness
            mean_val = np.mean(thresh)
            if mean_val < 128:
                thresh = cv2.add(thresh, 30)
            elif mean_val > 200:
                thresh = cv2.subtract(thresh, 30)

            # Clip values to valid range
            thresh = np.clip(thresh, 0, 255).astype(np.uint8)

            return thresh

        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"Plate preprocessing error: {e}")
            # Return original grayscale as fallback
            try:
                gray = cv2.cvtColor(plate_image, cv2.COLOR_BGR2GRAY)
                return gray
            except Exception:
                return plate_image


class PlateOCR:
    """Performs OCR on preprocessed plate images.

    Designed to be extremely robust - never raises exceptions.
    Always returns a valid dict with 'text' and 'confidence' keys,
    even on malformed input or missing dependencies.
    """

    def __init__(self, use_gpu: bool = False) -> None:
        """Initialize OCR engine.

        Args:
            use_gpu: Whether to attempt GPU acceleration (currently Python-only)
        """
        self.use_gpu = use_gpu
        self._initialized = False

        # Try to import pytesseract, fall back gracefully
        try:
            import pytesseract
            self.pytesseract = pytesseract
            self._tesseract_available = True
        except ImportError:
            self.pytesseract = None
            self._tesseract_available = False

        # Try to import PIL
        try:
            from PIL import Image
            self.Image = Image
            self._pil_available = True
        except ImportError:
            self.Image = None
            self._pil_available = False

        self._initialized = True

    def read(self, plate_image: np.ndarray, config: Optional[str] = None) -> Dict[str, Any]:
        """Perform OCR on a preprocessed plate image.

        Args:
            plate_image: Preprocessed grayscale plate image
            config: Optional tesseract config string

        Returns:
            Dict with 'text' and 'confidence' keys. Never raises exception.
            Returns {"text": "", "confidence": 0.0} on any error.
        """
        # Guard: check initialization and valid input
        if not self._initialized or plate_image is None or not isinstance(plate_image, np.ndarray) or plate_image.size == 0:
            return {"text": "", "confidence": 0.0}

        # Guard: tesseract availability
        if not self._tesseract_available:
            return {"text": "", "confidence": 0.0}

        # Guard: PIL availability
        if not self._pil_available:
            return {"text": "", "confidence": 0.0}

        try:
            # Convert to PIL Image if needed
            pil_image = self.Image.fromarray(plate_image)

            # Default tesseract config for license plates
            if config is None:
                config = "--psm 8 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

            # Perform OCR - wrapped in try/except to never crash
            try:
                text = self.pytesseract.image_to_string(
                    pil_image, config=config
                ).strip()
            except Exception:
                text = ""

            # Get confidence rating - wrapped in try/except
            try:
                data = self.pytesseract.image_to_data(
                    pil_image, config=config, output_type=self.pytesseract.Output.DICT
                )

                # Calculate average confidence from individual character detections
                confidences = []
                for i in range(len(data.get("text", []))):
                    try:
                        conf = int(data.get("confidence", [0])[i])
                        if conf > 0:
                            confidences.append(conf / 100.0)  # Normalize to 0-1
                    except (ValueError, IndexError, TypeError):
                        continue

                avg_confidence = float(np.mean(confidences)) if confidences else 0.0
            except Exception:
                avg_confidence = 0.0

            # Clean up the text - wrapped in try/except
            try:
                cleaned_text = self._clean_text(text)
            except Exception:
                cleaned_text = text

            return {
                "text": cleaned_text if cleaned_text else "",
                "confidence": min(max(avg_confidence, 0.0), 1.0),
            }

        except Exception as e:
            # Final fallback - never re-raise
            import logging
            logging.getLogger(__name__).debug(f"Plate OCR critical error: {e}")
            return {"text": "", "confidence": 0.0}

    def _numpy_to_pil(self, arr: np.ndarray) -> "Image.Image":
        """Convert numpy array to PIL Image.

        Gracefully handles invalid arrays.
        """
        try:
            if arr.ndim == 2:
                return self.Image.fromarray(arr, "L")
            elif arr.ndim == 3:
                if arr.shape[2] == 3:
                    return self.Image.fromarray(arr, "RGB")
                elif arr.shape[2] == 4:
                    return self.Image.fromarray(arr, "RGBA")
            return self.Image.fromarray(arr)
        except Exception:
            # Return a minimal valid image as last resort
            try:
                from PIL import Image
                return Image.new("L", (1, 1), 0)
            except Exception:
                return None

    @staticmethod
    def _clean_text(text: str) -> str:
        """Clean up OCR output by removing non-plate characters.

        Gracefully handles None/empty input.
        """
        try:
            if not text:
                return ""
            # Remove extra whitespace
            text = re.sub(r"\s+", "", text)
            # Remove common OCR artifacts - keep only alphanumeric and spaces
            text = re.sub(r"[^A-Za-z0-9\s]", "", text)
            # Collapse multiple spaces
            text = re.sub(r"\s+", " ", text).strip()
            return text
        except Exception:
            return ""

    def read_safe(self, plate_image: np.ndarray, config: Optional[str] = None) -> Dict[str, Any]:
        """Safe OCR read that never raises exceptions.

        Alias for read() - provided for explicit safe-call patterns.
        """
        return self.read(plate_image, config)


class PlateNormalizer:
    """Normalizes/format OCR results for consistent storage and display."""

    # Common Indian registration plate patterns (example)
    # Format: [XX]####[XX] or [X]####[X]
    # Where XX are state codes (2 letters) and #### are 4 digits

    # State code mappings (India)
    STATE_CODES = {
        "UP": "Uttar Pradesh",
        "MH": "Maharashtra",
        "DL": "Delhi",
        "KA": "Karnataka",
        "GJ": "Gujarat",
        "TN": "Tamil Nadu",
        "AP": "Andhra Pradesh",
        "TR": "Telangana",
        "HR": "Haryana",
        "RJ": "Rajasthan",
        "PB": "Punjab",
        "CT": "Chhattisgarh",
        "JH": "Jharkhand",
        "WB": "West Bengal",
        "AS": "Assam",
        "JK": "Jammu & Kashmir",
        "OR": "Odisha",
        "SK": "Sikkim",
        "GA": "Goa",
        "MP": "Madya Pradesh",
        "NIL": "Unknown/Invalid",
    }

    def normalize(self, raw_text: str) -> Optional[str]:
        """Normalize OCR output text.

        Args:
            raw_text: Raw OCR output

        Returns:
            Normalized text or None if not valid
        """
        if not raw_text or not raw_text.strip():
            return None

        text = raw_text.strip().upper()

        # Remove all spaces and special characters
        text = re.sub(r"\s+", "", text)

        # Keep only alphanumeric
        text = re.sub(r"[^A-Z0-9]", "", text)

        if len(text) < 3:
            # Too short to be a valid plate
            return None

        # Try to extract pattern: 2 letters + 4 digits + 2 letters (Indian format)
        normalized = self._try_indian_pattern(text)

        if normalized:
            return normalized

        # If no pattern matches, return cleaned text if it's reasonable length
        if 3 <= len(text) <= 12:
            return text

        return None

    def _try_indian_pattern(self, text: str) -> Optional[str]:
        """Try to match Indian registration plate pattern.

        Common pattern: UP32AB1234 or MH45CD5678
        Where: 2-state-code 2-district-code 2-letters 4-digits
        """
        import re

        # Pattern: 2 uppercase letters + 2 digits + 2 uppercase letters + 4 digits
        pattern = r"^[A-Z]{2}\d{2}[A-Z]{2}\d{4}$"
        match = re.match(pattern, text)
        if match:
            return match.group(0)

        # Pattern: 2 letters + 4 digits (simpler format)
        pattern2 = r"^[A-Z]{2}\d{4}$"
        match2 = re.match(pattern2, text)
        if match2:
            return match2.group(0)

        # Pattern: 4 digits + 2 letters
        pattern3 = r"^\d{4}[A-Z]{2}$"
        match3 = re.match(pattern3, text)
        if match3:
            return match3.group(0)

        return None

    def normalize_confidence(self, confidence: float, raw_text: str, normalized_text: str) -> float:
        """Adjust confidence based on normalization quality.

        Args:
            confidence: Original OCR confidence
            raw_text: Raw OCR output
            normalized_text: Normalized output

        Returns:
            Adjusted confidence score
        """
        try:
            if normalized_text and raw_text and normalized_text != raw_text:
                # Normalization changed some characters - adjust confidence down
                # but give credit if normalization improved readability
                mismatch = sum(1 for a, b in zip(raw_text, normalized_text) if a != b)
                adjustment = max(0.0, 1.0 - mismatch * 0.1)
                return min(confidence * adjustment, 1.0)

            return confidence
        except Exception:
            return confidence


# Export public API
__all__ = [
    "PlateRead",
    "PlateDetector",
    "PlatePreprocessor",
    "PlateOCR",
    "PlateNormalizer",
]