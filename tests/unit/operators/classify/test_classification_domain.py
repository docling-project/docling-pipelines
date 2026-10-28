#!/usr/bin/env python3
"""
Unit tests for classification domain models.
Tests ClassificationRequest, ClassificationResponse, and build_classification_prompt.
"""

import json

import pytest

from docpipe.core.operators.quality.classification.domain.models import (
    ClassificationRequest,
    ClassificationResponse,
    build_classification_prompt,
    parse_classification_response,
    resolve_document_type,
)


@pytest.mark.unit
class TestClassificationRequest:
    """Test ClassificationRequest domain model."""

    def test_create_request_with_dict_types(self):
        """Test creating request with dictionary of document types."""
        request = ClassificationRequest(
            content="Sample invoice content",
            document_types={
                "invoice": "Business invoice with line items",
                "receipt": "Payment receipt",
            },
            max_content_length=10000,
        )

        assert request.content == "Sample invoice content"
        assert isinstance(request.document_types, dict)
        assert len(request.document_types) == 2
        assert request.max_content_length == 10000

    def test_create_request_with_list_types(self):
        """Test creating request with list of document types."""
        request = ClassificationRequest(
            content="Sample content",
            document_types=["invoice", "receipt", "contract"],
            max_content_length=5000,
        )

        assert isinstance(request.document_types, list)
        assert len(request.document_types) == 3
        assert "invoice" in request.document_types

    def test_content_truncation(self):
        """Test that max_content_length is respected."""
        long_content = "A" * 20000
        request = ClassificationRequest(
            content=long_content,
            document_types=["invoice"],
            max_content_length=10000,
        )

        # The request stores the full content, truncation happens in prompt building
        assert len(request.content) == 20000
        assert request.max_content_length == 10000


@pytest.mark.unit
class TestClassificationResponse:
    """Test ClassificationResponse domain model."""

    def test_create_successful_response(self):
        """Test creating a successful classification response."""
        response = ClassificationResponse(
            document_type="invoice",
            confidence=9,
            reasoning="Contains line items and totals",
            success=True,
            error=None,
        )

        assert response.document_type == "invoice"
        assert response.confidence == 9
        assert response.reasoning == "Contains line items and totals"
        assert response.success is True
        assert response.error is None

    def test_create_error_response(self):
        """Test creating an error response."""
        response = ClassificationResponse(
            document_type="unknown",
            confidence=0,
            reasoning="",
            success=False,
            error="API call failed",
        )

        assert response.document_type == "unknown"
        assert response.confidence == 0
        assert response.success is False
        assert response.error == "API call failed"


@pytest.mark.unit
class TestBuildClassificationPrompt:
    """Test build_classification_prompt function."""

    def test_prompt_with_dict_types(self):
        """Test prompt generation with dictionary of document types."""
        request = ClassificationRequest(
            content="Invoice #12345\nTotal: $1000",
            document_types={
                "invoice": "Business invoice with line items",
                "receipt": "Payment receipt",
                "contract": "Legal contract",
            },
            max_content_length=10000,
        )

        prompt = build_classification_prompt(request=request)

        # Check prompt contains document types
        assert "invoice: Business invoice with line items" in prompt
        assert "receipt: Payment receipt" in prompt
        assert "contract: Legal contract" in prompt

        # Check prompt contains content
        assert "Invoice #12345" in prompt
        assert "Total: $1000" in prompt

        # Check prompt contains instructions
        assert "Classify the following document" in prompt
        assert "document_type" in prompt
        assert "confidence" in prompt
        assert "reasoning" in prompt

    def test_prompt_with_list_types(self):
        """Test prompt generation with list of document types."""
        request = ClassificationRequest(
            content="Sample content",
            document_types=["invoice", "receipt", "contract"],
            max_content_length=10000,
        )

        prompt = build_classification_prompt(request=request)

        # Check prompt contains document types as list items
        assert "- invoice" in prompt
        assert "- receipt" in prompt
        assert "- contract" in prompt

    def test_prompt_content_truncation(self):
        """Test that content is truncated in prompt."""
        long_content = "A" * 20000
        request = ClassificationRequest(
            content=long_content,
            document_types=["invoice"],
            max_content_length=5000,
        )

        prompt = build_classification_prompt(request=request)

        # The prompt should contain truncated content
        # Count 'A's in the prompt to verify truncation
        a_count = prompt.count("A")
        assert a_count <= 5000
        assert a_count > 0  # Some content should be present

    def test_prompt_with_empty_content(self):
        """Test prompt generation with empty content."""
        request = ClassificationRequest(
            content="",
            document_types=["invoice", "receipt"],
            max_content_length=10000,
        )

        prompt = build_classification_prompt(request=request)

        # Prompt should still be generated with instructions
        assert "Classify the following document" in prompt
        assert "invoice" in prompt

    def test_prompt_json_format_instructions(self):
        """Test that prompt includes JSON format instructions."""
        request = ClassificationRequest(
            content="Sample content",
            document_types=["invoice"],
            max_content_length=10000,
        )

        prompt = build_classification_prompt(request=request)

        # Check for JSON format instructions
        assert "JSON object" in prompt or "json" in prompt.lower()
        assert "document_type" in prompt
        assert "confidence" in prompt
        assert "reasoning" in prompt

    def test_prompt_example_response(self):
        """Test that prompt includes an example response."""
        request = ClassificationRequest(
            content="Sample content",
            document_types=["invoice"],
            max_content_length=10000,
        )

        prompt = build_classification_prompt(request=request)

        # Check for example response
        assert "Example" in prompt or "example" in prompt
        assert "{" in prompt  # JSON example should be present
        assert "}" in prompt


@pytest.mark.unit
class TestResolveDocumentType:
    """resolve_document_type maps an LLM label onto the configured spelling."""

    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            ("Purchase Order", "Purchase Order"),
            ("purchase order", "Purchase Order"),
            ("purchase_order", "Purchase Order"),
            ("PURCHASE  ORDER", "Purchase Order"),
            ("invoice", "invoice"),
        ],
    )
    def test_matches_ignoring_case_space_and_underscore(self, label, expected):
        assert resolve_document_type(label=label, document_types=["Purchase Order", "invoice"]) == expected

    def test_dict_types_use_keys(self):
        types = {"Pay Stub": "A pay stub", "invoice": "An invoice"}
        assert resolve_document_type(label="pay_stub", document_types=types) == "Pay Stub"

    def test_returns_none_when_no_match(self):
        assert resolve_document_type(label="memo", document_types=["invoice"]) is None

    def test_exact_match_wins_over_folded_match(self):
        assert resolve_document_type(label="a_b", document_types=["a b", "a_b"]) == "a_b"


@pytest.mark.unit
class TestParseClassificationResponse:
    """parse_classification_response turns raw LLM text into a ClassificationResponse."""

    def test_parses_valid_json(self):
        response = parse_classification_response(
            response_text='{"document_type": " Invoice ", "confidence": 9, "reasoning": "r"}'
        )
        assert response.success is True
        assert response.document_type == "Invoice"
        assert response.confidence == 9
        assert response.reasoning == "r"

    @pytest.mark.parametrize(("raw", "expected"), [(15, 10), (0, 1), ("8.7", 8)])
    def test_clamps_confidence(self, raw, expected):
        text = json.dumps({"document_type": "x", "confidence": raw})
        assert parse_classification_response(response_text=text).confidence == expected

    @pytest.mark.parametrize(
        "text",
        [None, "", "   ", "not json", '{"confidence": 5}', '{"document_type": null, "confidence": 5}'],
    )
    def test_raises_value_error_for_unusable_text(self, text):
        with pytest.raises(ValueError):
            parse_classification_response(response_text=text)

    def test_raises_value_error_for_non_numeric_confidence(self):
        with pytest.raises(ValueError, match="Invalid confidence value"):
            parse_classification_response(response_text='{"document_type": "x", "confidence": "high"}')
