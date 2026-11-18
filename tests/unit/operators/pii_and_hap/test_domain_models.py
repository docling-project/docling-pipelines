# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for PII/HAP domain models."""

from docpipe.core.operators.quality.pii_and_hap.domain.models import (
    DetectionResult,
    PIIHAPDetectionResponse,
)


class TestDetectionResult:
    """Test suite for DetectionResult domain model."""

    def test_detection_result_creation(self):
        """Test creating a DetectionResult with required fields."""
        result = DetectionResult(detection="email", detection_type="pii", score=0.95, start=10, end=30)

        assert result.detection == "email"
        assert result.detection_type == "pii"
        assert result.score == 0.95
        assert result.start == 10
        assert result.end == 30
        assert result.text is None
        assert result.evidences is None

    def test_detection_result_with_optional_fields(self):
        """Test creating a DetectionResult with optional fields."""
        evidences = [{"context": "found in email field"}]
        result = DetectionResult(
            detection="ssn",
            detection_type="pii",
            score=0.88,
            start=50,
            end=61,
            text="123-45-6789",
            evidences=evidences,
        )

        assert result.text == "123-45-6789"
        assert result.evidences == evidences
        assert len(result.evidences) == 1

    def test_detection_result_hap_type(self):
        """Test creating a HAP detection result."""
        result = DetectionResult(detection="hate_speech", detection_type="hap", score=0.92, start=0, end=50)

        assert result.detection == "hate_speech"
        assert result.detection_type == "hap"


class TestPIIHAPDetectionResponse:
    """Test suite for PIIHAPDetectionResponse domain model."""

    def test_empty_response(self):
        """Test creating an empty detection response."""
        response = PIIHAPDetectionResponse(detections=[])

        assert response.detections == []
        assert response.input_text is None

    def test_response_with_detections(self):
        """Test creating a response with multiple detections."""
        detections = [
            DetectionResult(detection="email", detection_type="pii", score=0.95, start=10, end=30),
            DetectionResult(detection="phone", detection_type="pii", score=0.88, start=40, end=52),
        ]

        response = PIIHAPDetectionResponse(
            detections=detections,
            input_text="Sample text with email@example.com and 555-1234",
        )

        assert len(response.detections) == 2
        assert response.input_text is not None
        assert "email@example.com" in response.input_text

    def test_response_preserves_detection_order(self):
        """Test that detection order is preserved."""
        detections = [
            DetectionResult("email", "pii", 0.9, 0, 10),
            DetectionResult("phone", "pii", 0.8, 20, 30),
            DetectionResult("ssn", "pii", 0.95, 40, 50),
        ]

        response = PIIHAPDetectionResponse(detections=detections)

        assert response.detections[0].detection == "email"
        assert response.detections[1].detection == "phone"
        assert response.detections[2].detection == "ssn"
