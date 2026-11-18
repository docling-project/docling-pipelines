# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for PII and HAP Annotator operator.

These tests use mocked responses for consistent, reproducible results.
For integration tests with real Ollama, see test_pii_and_hap_integration.py

Tests verify the same output format as the enterprise version, including:
- PII detection with and without redaction
- HAP detection with and without redaction
- Combined PII and HAP detection
- Display PII information
- Metadata validation
- Column naming conventions
"""

import logging
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pytest

from docpipe.core.adapters.huggingface import huggingface_adapter
from docpipe.core.constants.constants import ExecutionStatus, Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.quality.pii_and_hap import pii_and_hap_annotator
from docpipe.core.operators.quality.pii_and_hap.adapters.outbound.huggingface import adapter as hf_hap_adapter_module
from docpipe.core.operators.quality.pii_and_hap.domain.models import (
    DetectionResult,
    PIIHAPDetectionResponse,
)
from docpipe.core.operators.quality.pii_and_hap.pii_and_hap_annotator import (
    PIIAndHAPAnnotator,
)
from docpipe.core.operators.quality.pii_and_hap.pii_and_hap_helper import (
    DEFAULT_PII_TYPES_OF_CONCERN,
    METADATA_HAP_FIELD_NAME,
    GuardRailsPIIAndHAPExtractor,
    get_detected_field,
    get_fields_to_redact,
    initialize_table_columns,
    update_table,
)
from docpipe.core.operators.quality.pii_and_hap.services import pii_hap_service
from docpipe.integrations.huggingface.classification_client import WindowScores


def mock_detect_pii_hap(payload: dict):
    """Mock detection function that returns deterministic results."""
    text = payload.get("input", "")
    detections = []

    # Check for email addresses
    if "support@ibm.com" in text:
        detections.append(
            {
                "detection": "EmailAddress",
                "detection_type": "pii",
                "start": text.find("support@ibm.com"),
                "end": text.find("support@ibm.com") + len("support@ibm.com"),
                "score": 0.8,
                "text": "support@ibm.com",
            }
        )
    if "test@ibm.com" in text:
        detections.append(
            {
                "detection": "EmailAddress",
                "detection_type": "pii",
                "start": text.find("test@ibm.com"),
                "end": text.find("test@ibm.com") + len("test@ibm.com"),
                "score": 0.8,
                "text": "test@ibm.com",
            }
        )
    if "adityars@ibm.com" in text:
        detections.append(
            {
                "detection": "EmailAddress",
                "detection_type": "pii",
                "start": text.find("adityars@ibm.com"),
                "end": text.find("adityars@ibm.com") + len("adityars@ibm.com"),
                "score": 0.8,
                "text": "adityars@ibm.com",
            }
        )

    # Check for SSN
    if "123-45-6789" in text:
        detections.append(
            {
                "detection": "NationalNumber.SocialSecurityNumber.US",
                "detection_type": "pii",
                "start": text.find("123-45-6789"),
                "end": text.find("123-45-6789") + len("123-45-6789"),
                "score": 0.8,
                "text": "123-45-6789",
            }
        )

    # Check for phone number
    if "123-456-7890" in text:
        detections.append(
            {
                "detection": "PhoneNumber",
                "detection_type": "pii",
                "start": text.find("123-456-7890"),
                "end": text.find("123-456-7890") + len("123-456-7890"),
                "score": 0.8,
                "text": "123-456-7890",
            }
        )

    # Check for credit card
    if "5340904586541378" in text:
        detections.append(
            {
                "detection": "CreditCardNumber",
                "detection_type": "pii",
                "start": text.find("5340904586541378"),
                "end": text.find("5340904586541378") + len("5340904586541378"),
                "score": 0.8,
                "text": "5340904586541378",
            }
        )

    # Check for IP address
    if "127.0.0.1" in text:
        detections.append(
            {
                "detection": "IPAddress",
                "detection_type": "pii",
                "start": text.find("127.0.0.1"),
                "end": text.find("127.0.0.1") + len("127.0.0.1"),
                "score": 0.8,
                "text": "127.0.0.1",
            }
        )

    # Check for PersonName
    if "John Smith" in text:
        detections.append(
            {
                "detection": OperatorConstants.PIIHAP.PII_TYPE_PERSON_NAME,
                "detection_type": "pii",
                "start": text.find("John Smith"),
                "end": text.find("John Smith") + len("John Smith"),
                "score": 0.8,
                "text": "John Smith",
            }
        )

    # Check for Address
    if "42 Maple Street, Springfield" in text:
        detections.append(
            {
                "detection": OperatorConstants.PIIHAP.PII_TYPE_ADDRESS,
                "detection_type": "pii",
                "start": text.find("42 Maple Street, Springfield"),
                "end": text.find("42 Maple Street, Springfield") + len("42 Maple Street, Springfield"),
                "score": 0.8,
                "text": "42 Maple Street, Springfield",
            }
        )

    # Check for DateOfBirth
    if "1990-01-15" in text:
        detections.append(
            {
                "detection": OperatorConstants.PIIHAP.PII_TYPE_DATE_OF_BIRTH,
                "detection_type": "pii",
                "start": text.find("1990-01-15"),
                "end": text.find("1990-01-15") + len("1990-01-15"),
                "score": 0.8,
                "text": "1990-01-15",
            }
        )

    # Check for PassportNumber
    if "A12345678" in text:  # pragma: allowlist secret
        detections.append(
            {
                "detection": OperatorConstants.PIIHAP.PII_TYPE_PASSPORT_NUMBER,
                "detection_type": "pii",
                "start": text.find("A12345678"),  # pragma: allowlist secret
                "end": text.find("A12345678") + len("A12345678"),  # pragma: allowlist secret
                "score": 0.8,
                "text": "A12345678",  # pragma: allowlist secret
            }
        )

    # Check for DriverLicenseNumber
    if "DL-987654321" in text:
        detections.append(
            {
                "detection": OperatorConstants.PIIHAP.PII_TYPE_DRIVER_LICENSE,
                "detection_type": "pii",
                "start": text.find("DL-987654321"),
                "end": text.find("DL-987654321") + len("DL-987654321"),
                "score": 0.8,
                "text": "DL-987654321",
            }
        )

    # Check for NationalID
    if "NAT-11223344" in text:
        detections.append(
            {
                "detection": OperatorConstants.PIIHAP.PII_TYPE_NATIONAL_ID,
                "detection_type": "pii",
                "start": text.find("NAT-11223344"),
                "end": text.find("NAT-11223344") + len("NAT-11223344"),
                "score": 0.8,
                "text": "NAT-11223344",
            }
        )

    # Check for MedicalRecordNumber
    if "MRN-55443322" in text:
        detections.append(
            {
                "detection": OperatorConstants.PIIHAP.PII_TYPE_MEDICAL_RECORD,
                "detection_type": "pii",
                "start": text.find("MRN-55443322"),
                "end": text.find("MRN-55443322") + len("MRN-55443322"),
                "score": 0.8,
                "text": "MRN-55443322",
            }
        )

    # Check for HAP content
    normalized_text = text.replace("\u2019", "'")
    if "shouldn't even be allowed to speak" in normalized_text or "fool" in text.lower():
        detections.append(
            {
                "detection": "HAP",  # Must match METADATA_HAP_FIELD_NAME
                "detection_type": "hap",
                "start": 0,
                "end": len(text),
                "score": 0.9,
                "text": text[:100],  # First 100 chars
            }
        )

    # Convert dict detections to DetectionResult objects
    detection_results = [
        DetectionResult(
            detection=d["detection"],
            detection_type=d["detection_type"],
            score=d["score"],
            start=d["start"],
            end=d["end"],
            text=d.get("text"),  # Include text field for display_pii
        )
        for d in detections
    ]

    # Return PIIHAPDetectionResponse as expected by the service
    return PIIHAPDetectionResponse(detections=detection_results, input_text=text)


@pytest.fixture
def mock_pii_hap_service():
    """Mock the factory and PIIHAPService for all annotator tests."""
    with (
        patch(
            "docpipe.core.operators.quality.pii_and_hap.pii_and_hap_annotator.PIIAndHAPDetectionFactory.create",
            return_value=MagicMock(),
        ),
        patch("docpipe.core.operators.quality.pii_and_hap.pii_and_hap_annotator.PIIHAPService") as mock_service_class,
    ):
        mock_service = MagicMock()
        mock_service.detect_pii_hap.side_effect = mock_detect_pii_hap
        mock_service_class.return_value = mock_service
        yield mock_service


def test_both_pii_and_hap_redactions(mock_pii_hap_service):
    """Test PII and HAP detection with redaction enabled for both."""
    # 1. Construct the operator with the required configuration
    operator = PIIAndHAPAnnotator(
        {
            "doc_column": "content",
            "provider": "litellm",
            "provider_config": {
                "model_id": "openai/granite4",
                "api_key": "<ollama>",  # pragma: allowlist secret
                "api_base": "http://localhost:11434/v1",
            },
            "redaction": True,
            "redaction_character": "*",
            "hap_redaction": True,
            "hap_redaction_character": "*",
            "hap_threshold": 0.8,
        }
    )

    # 2. Create an in-memory py-arrow table as input
    content = pa.array(
        [
            "Your email is support@ibm.com! 5340904586541378 Only the next instance of email will be processed. test@ibm.com. Your SSN is 123-45-6789. Contact me at 123-456-7890",
            "Subject: Assistance 127.0.0.1 adityars@ibm.com with credit card update [213254000]",
            "People like you shouldn't even be allowed to speak. Honestly, anyone who believes in [religion] or follows [ethnicity] is a fool.",
            "Contact John Smith, born 1990-01-15, living at 42 Maple Street, Springfield. Passport: A12345678, DL: DL-987654321, NatID: NAT-11223344, MRN: MRN-55443322.",
        ]
    )
    ids = [1, 2, 3, 4]
    names = ["file1", "file2", "file3", "file4"]
    col_names = ["id", "content", "name"]
    input_table = pa.Table.from_arrays([ids, content, names], names=col_names)

    # 3. Run the operator
    table_list, metadata = operator.transform(input_table)

    # 4. Verify metadata
    expected_metadata = {
        "BankAccountNumber": 0,
        "CreditCardNumber": 1,
        "EmailAddress": 3,
        "HAP": 1,
        "IPAddress": 1,
        "PhoneNumber": 1,
        "SocialSecurityNumber": 1,
        "PersonName": 1,
        "DateOfBirth": 1,
        "Address": 1,
        "PassportNumber": 1,
        "DriverLicenseNumber": 1,
        "NationalID": 1,
        "MedicalRecordNumber": 1,
        "documents_in_scope": 4,
        "processed_docs": 4,
        "failed_docs_count": 0,
        "failed_docs": [],
        "skipped_docs_count": 0,
        "skipped_docs": [],
        "node_status": "Completed",
        "processed_rows": 4,
    }
    assert metadata == expected_metadata, f"Expected {expected_metadata}, but got {metadata}"

    # 5. Verify output table structure
    assert len(table_list) > 0, "Output table list should not be empty"
    table = table_list[0]

    # 6. Verify PII and HAP counts per document
    errors = []
    expected_pii_bank_account = [0, 0, 0, 0]
    expected_pii_credit_card = [1, 0, 0, 0]
    expected_pii_email_address = [2, 1, 0, 0]
    expected_pii_ip_address = [0, 1, 0, 0]
    expected_pii_phone_number = [1, 0, 0, 0]
    expected_pii_ssn_details = [1, 0, 0, 0]
    expected_pii_person_name = [0, 0, 0, 1]
    expected_pii_date_of_birth = [0, 0, 0, 1]
    expected_pii_address = [0, 0, 0, 1]
    expected_pii_passport_number = [0, 0, 0, 1]
    expected_pii_driver_license = [0, 0, 0, 1]
    expected_pii_national_id = [0, 0, 0, 1]
    expected_pii_medical_record = [0, 0, 0, 1]
    expected_hap = [0, 0, 1, 0]

    if expected_pii_bank_account != table["pii_bank_account"].to_pandas().to_list():
        errors.append("Bank Account PII error:" + str(table["pii_bank_account"].to_pandas().to_list()))
    if expected_pii_credit_card != table["pii_credit_card"].to_pandas().to_list():
        errors.append("Credit Card PII error:" + str(table["pii_credit_card"].to_pandas().to_list()))
    if expected_pii_email_address != table["pii_email_address"].to_pandas().to_list():
        errors.append("Email Id PII error:" + str(table["pii_email_address"].to_pandas().to_list()))
    if expected_pii_ip_address != table["pii_ip_address"].to_pandas().to_list():
        errors.append("Ip Address PII error:" + str(table["pii_ip_address"].to_pandas().to_list()))
    if expected_pii_phone_number != table["pii_phone_number"].to_pandas().to_list():
        errors.append("Phone Number PII Error:" + str(table["pii_phone_number"].to_pandas().to_list()))
    if expected_pii_ssn_details != table["pii_ssn_details"].to_pandas().to_list():
        errors.append("SSN PII Error:" + str(table["pii_ssn_details"].to_pandas().to_list()))
    if expected_pii_person_name != table["pii_person_name"].to_pandas().to_list():
        errors.append("Person Name PII Error:" + str(table["pii_person_name"].to_pandas().to_list()))
    if expected_pii_date_of_birth != table["pii_date_of_birth"].to_pandas().to_list():
        errors.append("Date of Birth PII Error:" + str(table["pii_date_of_birth"].to_pandas().to_list()))
    if expected_pii_address != table["pii_address"].to_pandas().to_list():
        errors.append("Address PII Error:" + str(table["pii_address"].to_pandas().to_list()))
    if expected_pii_passport_number != table["pii_passport_number"].to_pandas().to_list():
        errors.append("Passport Number PII Error:" + str(table["pii_passport_number"].to_pandas().to_list()))
    if expected_pii_driver_license != table["pii_driver_license"].to_pandas().to_list():
        errors.append("Driver License PII Error:" + str(table["pii_driver_license"].to_pandas().to_list()))
    if expected_pii_national_id != table["pii_national_id"].to_pandas().to_list():
        errors.append("National ID PII Error:" + str(table["pii_national_id"].to_pandas().to_list()))
    if expected_pii_medical_record != table["pii_medical_record"].to_pandas().to_list():
        errors.append("Medical Record PII Error:" + str(table["pii_medical_record"].to_pandas().to_list()))
    if expected_hap != table["hap"].to_pandas().to_list():
        errors.append("HAP Error:" + str(table["hap"].to_pandas().to_list()))

    assert not errors, f"Errors: {', '.join(errors)}"


def test_pii_extraction_without_redaction_and_displaying_pii(mock_pii_hap_service):
    """Test PII extraction without redaction and with display_pii enabled."""
    # 1. Construct the operator
    operator = PIIAndHAPAnnotator(
        {
            "doc_column": "content",
            "provider": "litellm",
            "provider_config": {
                "model_id": "openai/granite4",
                "api_key": "<ollama>",  # pragma: allowlist secret
                "api_base": "http://localhost:11434/v1",
            },
            "redaction": False,
            "redaction_character": "",
            "hap_redaction": True,
            "hap_redaction_character": "*",
            "display_pii": True,
        }
    )

    # 2. Create input table
    content = pa.array(
        [
            "Your email is support@ibm.com! Only the next instance of email will be processed. test@ibm.com. Your SSN is 123-45-6789. Contact me at 123-456-7890",
            "Subject: Assistance  adityars@ibm.com with credit card update [213254000]",
            "Contact John Smith at 42 Maple Street, Springfield.",
        ]
    )
    names = ["file1", "file2", "file3"]
    ids = [1, 2, 3]
    col_names = ["id", "content", "name"]
    input_table = pa.Table.from_arrays([ids, content, names], names=col_names)

    # 3. Run the operator
    table_list, metadata = operator.transform(input_table)

    # 4. Verify metadata
    expected_metadata = {
        "BankAccountNumber": 0,
        "CreditCardNumber": 0,
        "EmailAddress": 3,
        "HAP": 0,
        "IPAddress": 0,
        "PhoneNumber": 1,
        "SocialSecurityNumber": 1,
        "PersonName": 1,
        "DateOfBirth": 0,
        "Address": 1,
        "PassportNumber": 0,
        "DriverLicenseNumber": 0,
        "NationalID": 0,
        "MedicalRecordNumber": 0,
        "documents_in_scope": 3,
        "processed_docs": 3,
        "failed_docs_count": 0,
        "failed_docs": [],
        "skipped_docs_count": 0,
        "skipped_docs": [],
        "node_status": "Completed",
        "processed_rows": 3,
    }
    assert metadata == expected_metadata, f"Expected {expected_metadata}, but got {metadata}"

    # 5. Verify output table
    table = table_list[0]

    # Expected counts per document
    expected_pii_bank_account = [0, 0, 0]
    expected_pii_credit_card = [0, 0, 0]
    expected_pii_email_address = [2, 1, 0]
    expected_pii_ip_address = [0, 0, 0]
    expected_pii_phone_number = [1, 0, 0]
    expected_pii_ssn_details = [1, 0, 0]
    expected_pii_person_name = [0, 0, 1]
    expected_pii_address = [0, 0, 1]
    expected_hap = [0, 0, 0]

    errors = []
    if expected_pii_bank_account != table["pii_bank_account"].to_pandas().to_list():
        errors.append("Bank Account PII error:" + str(table["pii_bank_account"].to_pandas().to_list()))
    if expected_pii_credit_card != table["pii_credit_card"].to_pandas().to_list():
        errors.append("Credit Card PII error:" + str(table["pii_credit_card"].to_pandas().to_list()))
    if expected_pii_email_address != table["pii_email_address"].to_pandas().to_list():
        errors.append("Email Id PII error:" + str(table["pii_email_address"].to_pandas().to_list()))
    if expected_pii_ip_address != table["pii_ip_address"].to_pandas().to_list():
        errors.append("Ip Address PII error:" + str(table["pii_ip_address"].to_pandas().to_list()))
    if expected_pii_phone_number != table["pii_phone_number"].to_pandas().to_list():
        errors.append("Phone Number PII Error:" + str(table["pii_phone_number"].to_pandas().to_list()))
    if expected_pii_ssn_details != table["pii_ssn_details"].to_pandas().to_list():
        errors.append("SSN PII Error:" + str(table["pii_ssn_details"].to_pandas().to_list()))
    if expected_pii_person_name != table["pii_person_name"].to_pandas().to_list():
        errors.append("Person Name PII Error:" + str(table["pii_person_name"].to_pandas().to_list()))
    if expected_pii_address != table["pii_address"].to_pandas().to_list():
        errors.append("Address PII Error:" + str(table["pii_address"].to_pandas().to_list()))
    if expected_hap != table["hap"].to_pandas().to_list():
        errors.append("HAP Error:" + str(table["hap"].to_pandas().to_list()))

    # 6. Verify detailed PII information (when display_pii is True)
    expected_email_id_doc1 = [
        {
            "start": 14,
            "end": 29,
            "detection": "EmailAddress",
            "score": 0.8,
            "text": "support@ibm.com",
        },
        {
            "start": 82,
            "end": 94,
            "detection": "EmailAddress",
            "score": 0.8,
            "text": "test@ibm.com",
        },
    ]
    expected_ssn_doc1 = [
        {
            "start": 108,
            "end": 119,
            "detection": "NationalNumber.SocialSecurityNumber.US",
            "score": 0.8,
            "text": "123-45-6789",
        }
    ]
    expected_phone_number_doc1 = [
        {
            "start": 135,
            "end": 147,
            "detection": "PhoneNumber",
            "score": 0.8,
            "text": "123-456-7890",
        }
    ]
    expected_email_id_doc2 = [
        {
            "start": 21,
            "end": 37,
            "detection": "EmailAddress",
            "score": 0.8,
            "text": "adityars@ibm.com",
        }
    ]
    expected_person_name_doc3 = [
        {
            "start": 8,
            "end": 18,
            "detection": OperatorConstants.PIIHAP.PII_TYPE_PERSON_NAME,
            "score": 0.8,
            "text": "John Smith",
        }
    ]
    expected_address_doc3 = [
        {
            "start": 22,
            "end": 50,
            "detection": OperatorConstants.PIIHAP.PII_TYPE_ADDRESS,
            "score": 0.8,
            "text": "42 Maple Street, Springfield",
        }
    ]

    if expected_email_id_doc1 != table["pii_email_address_info"][0].as_py():
        errors.append("Doc1: Email Id PII Error")
    if expected_phone_number_doc1 != table["pii_phone_number_info"][0].as_py():
        errors.append("Doc1:Phone Number PII Error")
    if expected_ssn_doc1 != table["pii_ssn_details_info"][0].as_py():
        errors.append("Doc1:SSN PII Error")
    if expected_email_id_doc2 != table["pii_email_address_info"][1].as_py():
        errors.append("Doc2: Email Id PII Error")
    if expected_person_name_doc3 != table["pii_person_name_info"][2].as_py():
        errors.append("Doc3: Person Name PII Error")
    if expected_address_doc3 != table["pii_address_info"][2].as_py():
        errors.append("Doc3: Address PII Error")

    assert not errors, f"Errors: {', '.join(errors)}"


def test_pii_extraction_with_redaction(mock_pii_hap_service):
    """Test PII extraction with redaction enabled."""
    # 1. Construct the operator
    operator = PIIAndHAPAnnotator(
        {
            "doc_column": "content",
            "provider": "litellm",
            "provider_config": {
                "model_id": "openai/granite4",
                "api_key": "<ollama>",  # pragma: allowlist secret
                "api_base": "http://localhost:11434/v1",
            },
            "redaction": True,
            "redaction_character": "*",
            "display_pii": False,
        }
    )

    # 2. Create input table
    content = pa.array(
        [
            "Your email is support@ibm.com! Only the next instance of email will be processed. test@ibm.com. Your SSN is 123-45-6789.",
            "Subject: Assistance adityars@ibm.com with credit card update",
            "Contact John Smith at 42 Maple Street, Springfield.",
        ]
    )
    names = ["file1", "file2", "file3"]
    ids = [1, 2, 3]
    col_names = ["id", "content", "name"]
    input_table = pa.Table.from_arrays([ids, content, names], names=col_names)

    # 3. Run the operator
    table_list, _ = operator.transform(input_table)

    # 4. Verify the content has been redacted
    table = table_list[0]
    redacted_content = table["content"][0].as_py()
    redacted_content_doc3 = table["content"][2].as_py()

    # Verify that PII has been replaced with redaction character
    assert "support@ibm.com" not in redacted_content, "Email should be redacted"
    assert "test@ibm.com" not in redacted_content, "Email should be redacted"
    assert "123-45-6789" not in redacted_content, "SSN should be redacted"
    assert "*" in redacted_content, "Redaction character should be present"

    assert "John Smith" not in redacted_content_doc3, "PersonName should be redacted"
    assert "42 Maple Street, Springfield" not in redacted_content_doc3, "Address should be redacted"
    assert "*" in redacted_content_doc3, "Redaction character should be present"


def test_hap_extraction_with_redaction(mock_pii_hap_service):
    """Test HAP extraction with redaction enabled."""
    # 1. Construct the operator
    operator = PIIAndHAPAnnotator(
        {
            "doc_column": "content",
            "provider": "litellm",
            "provider_config": {
                "model_id": "openai/granite4",
                "api_key": "api-key",  # pragma: allowlist secret
                "api_base": "http://localhost:11434/v1",
            },
            "hap_redaction": True,
            "hap_redaction_character": "*",
            "hap_threshold": 0.8,
        }
    )

    # 2. Create input table
    content = pa.array(
        [
            "Your email is support@ibm.com!",
            "People like you shouldn't even be allowed to speak. Honestly, anyone who believes in [religion] or follows [ethnicity] is a fool.",
        ]
    )
    names = ["file1", "file2"]
    ids = [1, 2]
    col_names = ["id", "content", "name"]
    input_table = pa.Table.from_arrays([ids, content, names], names=col_names)

    # 3. Run the operator
    table_list, _ = operator.transform(input_table)

    # 4. Verify HAP detection
    table = table_list[0]
    expected_hap = [0, 1]

    assert expected_hap == table["hap"].to_pandas().to_list(), (
        f"Expected HAP counts {expected_hap}, but got {table['hap'].to_pandas().to_list()}"
    )

    # 5. Verify HAP content has been redacted
    redacted_content = table["content"][1].as_py()
    assert "*" in redacted_content, "HAP content should be redacted"


def test_hap_extraction_without_redaction(mock_pii_hap_service):
    """Test HAP extraction without redaction."""
    # 1. Construct the operator
    operator = PIIAndHAPAnnotator(
        {
            "doc_column": "content",
            "provider": "litellm",
            "provider_config": {
                "model_id": "openai/granite4",
                "api_key": "api-key",  # pragma: allowlist secret
                "api_base": "http://localhost:11434/v1",
            },
            "hap_redaction": False,
            "hap_redaction_character": "",
        }
    )

    # 2. Create input table
    content = pa.array(
        [
            "Your email is support@ibm.com! Only the next instance of email will be processed. test@ibm.com. Your SSN is 123-45-6789. Contact me at 123-456-7890",
            "People like you shouldn't even be allowed to speak. Honestly, anyone who believes in [religion] or follows [ethnicity] is a fool.",
        ]
    )
    names = ["file1", "file2"]
    ids = [1, 2]
    col_names = ["id", "content", "name"]
    input_table = pa.Table.from_arrays([ids, content, names], names=col_names)

    # 3. Run the operator
    table_list, _ = operator.transform(input_table)

    # 4. Verify HAP detection
    table = table_list[0]
    expected_hap = [0, 1]

    assert expected_hap == table["hap"].to_pandas().to_list(), (
        f"Expected HAP counts {expected_hap}, but got {table['hap'].to_pandas().to_list()}"
    )

    # 5. Verify content is NOT redacted
    original_content = table["content"][1].as_py()
    assert "shouldn't even be allowed to speak" in original_content, (
        "HAP content should NOT be redacted when hap_redaction is False"
    )


def test_empty_input_table(mock_pii_hap_service):
    """Test operator with empty input table."""
    # 1. Construct the operator
    operator = PIIAndHAPAnnotator(
        {
            "doc_column": "content",
            "provider": "litellm",
            "provider_config": {
                "model_id": "openai/granite4",
                "api_key": "api-key",  # pragma: allowlist secret
                "api_base": "http://localhost:11434/v1",
            },
        }
    )

    # 2. Create empty input table
    content = pa.array([])
    ids: list[str] = []
    names: list[str] = []
    col_names = ["id", "content", "name"]
    input_table = pa.Table.from_arrays([ids, content, names], names=col_names)

    # 3. Run the operator
    _, metadata = operator.transform(input_table)

    # 4. Verify metadata for empty input
    assert metadata["documents_in_scope"] == 0
    assert metadata["processed_docs"] == 0
    assert metadata["node_status"] == "Completed"


def test_configuration_validation():
    """Test operator configuration validation."""
    # Test with missing doc_column (should use default)
    try:
        operator = PIIAndHAPAnnotator(
            {
                "provider": "litellm",
                "provider_config": {
                    "model_id": "openai/granite4",
                    "api_key": "api-key",  # pragma: allowlist secret
                    "api_base": "http://localhost:11434/v1",
                },
            }
        )
        assert operator.doc_column == OperatorConstants.Columns.DOC_COLUMN_DEFAULT
    except Exception as e:
        pytest.fail(f"Unexpected exception with default doc_column: {e!s}")

    # Test with custom configuration
    try:
        operator = PIIAndHAPAnnotator(
            {
                "doc_column": "text",
                "provider": "litellm",
                "provider_config": {
                    "model_id": "gpt-3.5-turbo",
                    "base_url": "http://localhost:8000/v1",
                    "api_key": "test-key",  # pragma: allowlist secret
                },
            }
        )
        assert operator.doc_column == "text"
        assert operator.provider == "litellm"
    except Exception as e:
        pytest.fail(f"Unexpected exception with custom configuration: {e!s}")


def test_validate_method_missing_provider_config(mock_pii_hap_service):
    """Test validate() appends error when provider_config is empty or missing."""
    operator = PIIAndHAPAnnotator({"doc_column": "content", "provider": "litellm"})
    errors: list[str] = []
    warnings: list[str] = []
    operator.validate(errors, warnings, [OperatorConstants.Columns.DOC_COLUMN_DEFAULT])
    assert any("provider_config is required" in e for e in errors)


def test_validate_method_missing_model_id(mock_pii_hap_service):
    """Test validate() appends error when provider_config is missing model_id."""
    operator = PIIAndHAPAnnotator(
        {
            "doc_column": "content",
            "provider": "litellm",
            "provider_config": {
                "api_base": "http://localhost:11434/v1",
                "api_key": "ollama",  # pragma: allowlist secret
            },
        }
    )
    errors: list[str] = []
    warnings: list[str] = []
    operator.validate(errors, warnings, [OperatorConstants.Columns.DOC_COLUMN_DEFAULT])
    assert any("provider_config.model_id is required" in e for e in errors)


def test_validate_method_valid_litellm_config(mock_pii_hap_service):
    """Test validate() succeeds with valid provider_config."""
    operator = PIIAndHAPAnnotator(
        {
            "doc_column": "content",
            "provider": "litellm",
            "provider_config": {
                "model_id": "openai/granite4",
                "api_base": "http://localhost:11434/v1",
                "api_key": "ollama",  # pragma: allowlist secret
            },
            "redaction": False,
            "hap_redaction": False,
        }
    )
    errors: list[str] = []
    warnings: list[str] = []
    operator.validate(errors, warnings, [OperatorConstants.Columns.DOC_COLUMN_DEFAULT])
    assert len(errors) == 0


def test_validate_method_watsonx_missing_keys(mock_pii_hap_service):
    """Test validate() appends error when watsonx is missing required fields."""
    operator = PIIAndHAPAnnotator(
        {
            "doc_column": "content",
            "provider": "watsonx",
            "provider_config": {
                "model_id": "ibm/granite-guardian-3-8b",
            },
        }
    )
    errors: list[str] = []
    warnings: list[str] = []
    operator.validate(errors, warnings, [OperatorConstants.Columns.DOC_COLUMN_DEFAULT])
    assert any("WatsonX provider requires" in e for e in errors)


def test_config_validation_invalid_pii_threshold():
    """Test that invalid pii_threshold raises ValueError."""
    # Test pii_threshold > 1
    with pytest.raises(ValueError, match="pii_threshold must be between 0 and 1"):
        PIIAndHAPAnnotator(
            {
                "doc_column": "content",
                "pii_threshold": 1.5,
            }
        )

    # Test pii_threshold < 0
    with pytest.raises(ValueError, match="pii_threshold must be between 0 and 1"):
        PIIAndHAPAnnotator(
            {
                "doc_column": "content",
                "pii_threshold": -0.1,
            }
        )


def test_config_validation_invalid_hap_threshold():
    """Test that invalid hap_threshold raises ValueError."""
    # Test hap_threshold > 1
    with pytest.raises(ValueError, match="hap_threshold must be between 0 and 1"):
        PIIAndHAPAnnotator(
            {
                "doc_column": "content",
                "hap_threshold": 2.0,
            }
        )

    # Test hap_threshold < 0
    with pytest.raises(ValueError, match="hap_threshold must be between 0 and 1"):
        PIIAndHAPAnnotator(
            {
                "doc_column": "content",
                "hap_threshold": -0.5,
            }
        )


def test_config_validation_invalid_batch_size():
    """Test that invalid batch_size raises ValueError."""
    # Test batch_size = 0
    with pytest.raises(ValueError, match="batch_size must be positive"):
        PIIAndHAPAnnotator(
            {
                "doc_column": "content",
                "batch_size": 0,
            }
        )

    # Test batch_size < 0
    with pytest.raises(ValueError, match="batch_size must be positive"):
        PIIAndHAPAnnotator(
            {
                "doc_column": "content",
                "batch_size": -5,
            }
        )


def test_config_validation_invalid_chunk_sizes():
    """Test that invalid chunk size configuration raises ValueError."""
    # Test min_chunk_size > max_chunk_size
    with pytest.raises(ValueError, match=r"min_chunk_size .* cannot exceed max_chunk_size"):
        PIIAndHAPAnnotator(
            {
                "doc_column": "content",
                "min_chunk_size_kb": 200 * 1024,
                "max_chunk_size_kb": 100 * 1024,
            }
        )


@pytest.mark.parametrize(
    ("config_override", "expected_attr", "expected_value"),
    [
        # PII threshold edge cases
        ({"pii_threshold": 0.0}, "pii_threshold", 0.0),
        ({"pii_threshold": 1.0}, "pii_threshold", 1.0),
        # HAP threshold edge cases
        ({"hap_threshold": 0.0}, "hap_threshold", 0.0),
        ({"hap_threshold": 1.0}, "hap_threshold", 1.0),
        # Chunk size edge case - special handling needed
        (
            {"min_chunk_size_kb": 100 * 1024, "max_chunk_size_kb": 100 * 1024},
            "min_chunk_size",
            None,  # None signals to compare min_chunk_size == max_chunk_size
        ),
    ],
    ids=[
        "pii_threshold_min",
        "pii_threshold_max",
        "hap_threshold_min",
        "hap_threshold_max",
        "chunk_sizes_equal",
    ],
)
def test_config_validation_valid_edge_cases(config_override, expected_attr, expected_value):
    """Test that valid edge case configurations are accepted."""
    base_config = {
        "doc_column": "content",
        "provider": "litellm",
        "provider_config": {
            "model_id": "openai/granite4",
            "api_key": "api-key",  # pragma: allowlist secret
            "api_base": "http://localhost:11434/v1",
        },
    }
    config = {**base_config, **config_override}

    operator = PIIAndHAPAnnotator(config)

    if expected_value is None:
        # Special case: chunk sizes should be equal
        assert operator.min_chunk_size == operator.max_chunk_size
    else:
        assert getattr(operator, expected_attr) == expected_value


def test_expected_redactions_as_set(mock_pii_hap_service):
    """Test that expected_redactions is stored as a set with lowercase values."""
    # Test with mixed case input
    operator = PIIAndHAPAnnotator(
        {
            "doc_column": "content",
            "expected_redactions": [
                "PII",
                "HAP",
                "pii",
            ],  # Duplicate "pii" in different case
        }
    )

    # Verify it's a set
    assert isinstance(operator.expected_redactions, set), "expected_redactions should be a set"

    # Verify all values are lowercase
    assert operator.expected_redactions == {
        "pii",
        "hap",
    }, f"expected_redactions should be lowercase set, got {operator.expected_redactions}"

    # Verify set deduplication worked (only 2 unique values)
    assert len(operator.expected_redactions) == 2, (
        f"expected_redactions should have 2 unique values, got {len(operator.expected_redactions)}"
    )


def test_expected_redactions_default_value(mock_pii_hap_service):
    """Test that expected_redactions uses default value when not provided."""
    operator = PIIAndHAPAnnotator(
        {
            "doc_column": "content",
        }
    )

    # Verify default value is used and converted to set
    assert isinstance(operator.expected_redactions, set), "expected_redactions should be a set"
    assert "pii" in operator.expected_redactions, "Default should include 'pii'"
    assert "hap" in operator.expected_redactions, "Default should include 'hap'"


def test_expected_redactions_membership_check(mock_pii_hap_service):
    """Test that set membership checks work correctly for expected_redactions."""
    operator = PIIAndHAPAnnotator(
        {
            "doc_column": "content",
            "expected_redactions": ["PII", "HAP"],
        }
    )

    # Test O(1) membership checks
    assert "pii" in operator.expected_redactions, "'pii' should be in expected_redactions"
    assert "hap" in operator.expected_redactions, "'hap' should be in expected_redactions"
    assert "other" not in operator.expected_redactions, "'other' should not be in expected_redactions"

    # Verify case-insensitive (all stored as lowercase)
    assert "PII" not in operator.expected_redactions, "Uppercase 'PII' should not match (stored as lowercase)"


def test_get_metadata_features_include_all_supported_types():
    """get_metadata() FEATURES dict must contain a counter entry for each supported type."""
    from docpipe.core.operators.quality.pii_and_hap.pii_and_hap_helper import DEFAULT_PII_TO_COLUMN_MAPPING

    features = PIIAndHAPAnnotator.get_metadata()[OperatorConstants.Config.FEATURES]
    for col in DEFAULT_PII_TO_COLUMN_MAPPING.values():
        assert f"pii_{col}" in features, f"Feature key 'pii_{col}' missing from get_metadata() FEATURES"


def test_helper_get_fields_to_redact():
    """Test get_fields_to_redact helper function."""
    fields = get_fields_to_redact(
        expected_redactions=[OperatorConstants.PIIHAP.PII_FIELD_NAME, OperatorConstants.PIIHAP.HAP_FIELD_NAME],
        pii_list=[OperatorConstants.PIIHAP.PII_TYPE_PERSON_NAME],
    )
    assert fields == [OperatorConstants.PIIHAP.PII_TYPE_PERSON_NAME, METADATA_HAP_FIELD_NAME]

    fields_default = get_fields_to_redact(
        expected_redactions=[OperatorConstants.PIIHAP.PII_FIELD_NAME],
        pii_list=[],
    )
    assert fields_default == DEFAULT_PII_TYPES_OF_CONCERN


def test_helper_get_detected_field_exact_and_partial_and_empty():
    """Test get_detected_field with exact match, partial match, and empty input."""
    fields = [
        OperatorConstants.PIIHAP.PII_TYPE_SOCIAL_SECURITY_NUMBER,
        OperatorConstants.PIIHAP.PII_TYPE_PERSON_NAME,
    ]

    # Exact match
    assert get_detected_field({"detection": OperatorConstants.PIIHAP.PII_TYPE_PERSON_NAME}, fields) == (
        OperatorConstants.PIIHAP.PII_TYPE_PERSON_NAME
    )

    # Partial match
    assert (
        get_detected_field(
            {"detection": "NationalNumber.SocialSecurityNumber.US"},
            fields,
        )
        == OperatorConstants.PIIHAP.PII_TYPE_SOCIAL_SECURITY_NUMBER
    )

    # Empty / no match / missing detection
    assert get_detected_field({"detection": "UnknownType"}, fields) == ""
    assert get_detected_field({}, fields) == ""


def test_helper_initialize_table_columns_and_update_table():
    """Test table column initialization and update_table helper."""
    metadata: dict = {}
    fields_to_redact = [
        METADATA_HAP_FIELD_NAME,
        OperatorConstants.PIIHAP.PII_TYPE_PERSON_NAME,
        "UnknownFieldWithoutColumnMapping",
    ]

    columns = initialize_table_columns(
        metadata=metadata,
        fields_to_redact=fields_to_redact,
        display_pii=True,
    )

    assert OperatorConstants.PIIHAP.HAP_FIELD_NAME in columns
    assert "pii_person_name_column" in columns
    assert "pii_person_name_info_column" in columns
    assert "UnknownFieldWithoutColumnMapping" not in columns

    # Test update_table
    columns[OperatorConstants.PIIHAP.HAP_FIELD_NAME].append(1)
    columns["pii_person_name_column"].append(1)
    columns["pii_person_name_info_column"].append(["John Doe"])

    base_table = pa.Table.from_arrays([pa.array(["Sample doc"])], names=["content"])
    updated = update_table(
        table=base_table,
        table_columns=columns,
        fields_to_redact=fields_to_redact,
        display_pii=True,
    )

    assert OperatorConstants.PIIHAP.HAP_FIELD_NAME in updated.column_names
    assert "pii_person_name" in updated.column_names
    assert "pii_person_name_info" in updated.column_names


def test_helper_guardrails_extractor_single_redaction_variants():
    """Test single redaction variants on GuardRailsPIIAndHAPExtractor."""
    extractor = GuardRailsPIIAndHAPExtractor(
        {
            OperatorConstants.PIIHAP.REDACTION_CHARACTER_KEY: "*",
            OperatorConstants.PIIHAP.HAP_REDACTION_CHARACTER_KEY: "#",
        }
    )

    # 1. Invalid redaction character fallback
    extractor_invalid = GuardRailsPIIAndHAPExtractor(
        {
            OperatorConstants.PIIHAP.REDACTION_CHARACTER_KEY: "invalid_multichar",
            OperatorConstants.PIIHAP.HAP_REDACTION_CHARACTER_KEY: "invalid_multichar",
        }
    )
    content = "Hello John Doe"
    item = {"start": 6, "end": 14, "text": "John Doe"}
    redacted = extractor_invalid.redact(content, item, "pii")
    assert redacted == "Hello ********"

    # 2. Text fallback redaction when start/end missing
    content2 = "Hello John Doe and goodbye John Doe"
    item2 = {"text": "John Doe"}
    redacted2 = extractor.redact(content2, item2, "pii")
    assert redacted2 == "Hello ******** and goodbye ********"

    # 3. Missing both start/end and text
    item3 = {"detection": "PersonName"}
    unchanged = extractor.redact(content2, item3, "pii")
    assert unchanged == content2

    # 4. PyArrow scalar content
    pa_scalar = pa.scalar("Hello Jane")
    item4 = {"start": 6, "end": 10, "text": "Jane"}
    assert extractor.redact(pa_scalar, item4, "pii") == "Hello ****"


def test_helper_guardrails_extractor_redact_batch():
    """Test batch redaction with overlapping and text-only detections."""
    extractor = GuardRailsPIIAndHAPExtractor(
        {
            OperatorConstants.PIIHAP.REDACTION_CHARACTER_KEY: "*",
            OperatorConstants.PIIHAP.HAP_REDACTION_CHARACTER_KEY: "#",
        }
    )

    # Empty detections
    assert extractor.redact_batch("Hello world", [], []) == "Hello world"

    # Overlapping and non-overlapping detections with start/end
    content = "User Alice and Bob are toxic hate remarks"
    detections = [
        {"start": 5, "end": 10, "text": "Alice"},  # PII
        {"start": 8, "end": 18, "text": "e and Bob "},  # Overlapping PII
        {"start": 23, "end": 28, "text": "toxic"},  # HAP
    ]
    detected_types = ["pii", "pii", METADATA_HAP_FIELD_NAME]

    redacted = extractor.redact_batch(content, detections, detected_types)
    # Alice (5..10) merged with (8..18) -> (5..18) 13 chars of '*'
    assert redacted == "User ************* are ##### hate remarks"

    # Detections without start/end positions (text search fallback in batch)
    content_text_only = "Contact Alice at Alice office"
    text_detections = [
        {"text": "Alice"},
    ]
    redacted_text = extractor.redact_batch(content_text_only, text_detections, ["pii"])
    assert redacted_text == "Contact ***** at ***** office"


# ---------------------------------------------------------------------------
# huggingface HAP provider, end to end through the annotator
# (real HuggingFaceHAPAdapter, core HuggingFaceAdapter and PIIHAPService;
# only the local classification model is replaced by a fake)
# ---------------------------------------------------------------------------

_HF_TOXIC_PHRASES = ("worthless idiot", "moron")
# A document containing this marker makes the fake classifier raise, simulating a model error.
_HF_SCORING_FAILURE_MARKER = "[simulate-scoring-failure]"


class _FakeHAPClassifier:
    """Stand-in for HuggingFaceClassificationClient: fixed scores per sentence, no model."""

    def get_labels(self) -> tuple[str, ...]:
        """Return the default model's labels."""
        return ("LABEL_0", "LABEL_1")

    def score_spans(self, *, text: str, spans: list[tuple[int, int]]) -> list[WindowScores]:
        """Score spans containing a toxic phrase 0.95 and everything else 0.01; fail on the failure marker."""
        if _HF_SCORING_FAILURE_MARKER in text:
            raise ValueError(f"tokenizer failed on: {text}")
        scores = []
        for start, end in spans:
            toxic = 0.95 if any(phrase in text[start:end] for phrase in _HF_TOXIC_PHRASES) else 0.01
            scores.append(WindowScores(start=start, end=end, probabilities={"LABEL_0": 1 - toxic, "LABEL_1": toxic}))
        return scores


@pytest.fixture
def huggingface_hap_operator_factory():
    """Build pii_and_hap operators that use the huggingface HAP provider with a fake model."""
    with patch.object(huggingface_adapter, "HuggingFaceClassificationClient", return_value=_FakeHAPClassifier()):

        def build(**overrides):
            config = {
                "doc_column": "content",
                "hap_provider": "huggingface",
                "expected_redactions": ["HAP"],
                "hap_threshold": 0.8,
                "hap_redaction": False,
                **overrides,
            }
            return PIIAndHAPAnnotator(config)

        yield build


def _hf_table(contents: list[str]) -> pa.Table:
    return pa.Table.from_pydict(
        {
            "id": [f"doc-{index}" for index in range(len(contents))],
            "content": contents,
            "name": [f"file{index}.md" for index in range(len(contents))],
        }
    )


_HF_DOCS = [
    "Thanks for the report.\nYou are a worthless idiot. Go away, moron.",
    "All good here. See you tomorrow.",
    "Meeting notes:\n- You are a worthless idiot.\n- Next steps.",
]


def test_huggingface_hap_counts_per_document_and_in_metadata(huggingface_hap_operator_factory):
    operator = huggingface_hap_operator_factory()
    input_table = _hf_table(_HF_DOCS)

    (table,), metadata = operator.transform(input_table)

    assert table.column_names == [*input_table.column_names, "hap"]
    assert table.schema.field("hap").type == pa.int64()
    assert table["hap"].to_pylist() == [2, 0, 1]
    assert metadata[METADATA_HAP_FIELD_NAME] == 3
    assert table["content"].to_pylist() == _HF_DOCS


def test_huggingface_hap_redaction_masks_only_the_flagged_sentence(huggingface_hap_operator_factory):
    operator = huggingface_hap_operator_factory(hap_redaction=True, hap_redaction_character="#")
    content = _HF_DOCS[2]
    # A Markdown list item is one span, so its "- " marker is masked with the sentence
    toxic = "- You are a worthless idiot."

    (table,), _ = operator.transform(_hf_table([content]))

    assert table["content"].to_pylist() == [content.replace(toxic, "#" * len(toxic))]
    assert table["content"][0].as_py().count("\n") == content.count("\n")


def test_huggingface_hap_scoring_failure_removes_only_that_document(huggingface_hap_operator_factory):
    operator = huggingface_hap_operator_factory(partial_ingest=True)
    failing = f"{_HF_SCORING_FAILURE_MARKER} secret customer sentence."

    (table,), metadata = operator.transform(_hf_table([_HF_DOCS[0], failing, _HF_DOCS[2]]))

    assert table["id"].to_pylist() == ["doc-0", "doc-2"]
    assert table["hap"].to_pylist() == [2, 1]
    assert metadata[Metrics.External.NODE_STATUS] == ExecutionStatus.COMPLETED_WITH_ERRORS.value
    assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 1
    (failed,) = metadata[Metrics.External.FAILED_DOCS]
    assert "Hugging Face HAP detection failed: ValueError while scoring with model" in str(failed)
    assert "secret customer sentence" not in str(failed)


def test_huggingface_hap_debug_logs_contain_no_document_text(huggingface_hap_operator_factory, caplog):
    operator = huggingface_hap_operator_factory(partial_ingest=True)
    contents = [_HF_DOCS[0], f"{_HF_SCORING_FAILURE_MARKER} secret customer sentence."]
    loggers = [
        logging.getLogger(name)
        for name in (
            pii_and_hap_annotator.__name__,
            huggingface_adapter.__name__,
            hf_hap_adapter_module.__name__,
            pii_hap_service.__name__,
        )
    ]
    previous_levels = [module_logger.level for module_logger in loggers]
    for module_logger in loggers:
        module_logger.addHandler(caplog.handler)
        module_logger.setLevel(logging.DEBUG)
    try:
        operator.transform(_hf_table(contents))
    finally:
        for module_logger, level in zip(loggers, previous_levels, strict=True):
            module_logger.removeHandler(caplog.handler)
            module_logger.setLevel(level)

    messages = [record.getMessage() for record in caplog.records]
    assert any(record.levelno == logging.DEBUG for record in caplog.records)
    for fragment in ("worthless idiot", "Go away", "Thanks for the report", "secret customer sentence"):
        assert all(fragment not in message for message in messages), fragment


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
