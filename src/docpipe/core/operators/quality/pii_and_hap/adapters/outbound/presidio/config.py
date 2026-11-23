# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Pydantic config model and entity mapping for the Presidio PII detection adapter."""

from pydantic import BaseModel, ConfigDict, Field

from docpipe.core.constants.operator_constants import OperatorConstants

ADAPTER_NAME = "presidio"

DEFAULT_LANGUAGE = "en"
DEFAULT_SPACY_MODEL = "en_core_web_lg"

_PIIHAP = OperatorConstants.PIIHAP

# Presidio entity type -> PII label used by the pii_and_hap operator (``pii_list`` values).
# Entities without a sensible equivalent are intentionally left out:
#   - DATE_TIME matches any date, not specifically a date of birth.
#   - LOCATION matches city / country names, not postal addresses.
# Use ``provider_config.entity_mapping`` to add or override mappings.
DEFAULT_PRESIDIO_ENTITY_MAPPING: dict[str, str] = {
    "EMAIL_ADDRESS": _PIIHAP.PII_TYPE_EMAIL_ADDRESS,
    "PHONE_NUMBER": _PIIHAP.PII_TYPE_PHONE_NUMBER,
    "US_SSN": _PIIHAP.PII_TYPE_SOCIAL_SECURITY_NUMBER,
    "CREDIT_CARD": _PIIHAP.PII_TYPE_CREDIT_CARD_NUMBER,
    "US_BANK_NUMBER": _PIIHAP.PII_TYPE_BANK_ACCOUNT_NUMBER,
    "IBAN_CODE": _PIIHAP.PII_TYPE_BANK_ACCOUNT_NUMBER,
    "IP_ADDRESS": _PIIHAP.PII_TYPE_IP_ADDRESS,
    "PERSON": _PIIHAP.PII_TYPE_PERSON_NAME,
    "US_PASSPORT": _PIIHAP.PII_TYPE_PASSPORT_NUMBER,
    "UK_PASSPORT": _PIIHAP.PII_TYPE_PASSPORT_NUMBER,
    "IT_PASSPORT": _PIIHAP.PII_TYPE_PASSPORT_NUMBER,
    "US_DRIVER_LICENSE": _PIIHAP.PII_TYPE_DRIVER_LICENSE,
    "IT_DRIVER_LICENSE": _PIIHAP.PII_TYPE_DRIVER_LICENSE,
    "US_ITIN": _PIIHAP.PII_TYPE_NATIONAL_ID,
    "UK_NINO": _PIIHAP.PII_TYPE_NATIONAL_ID,
    "ES_NIF": _PIIHAP.PII_TYPE_NATIONAL_ID,
    "ES_NIE": _PIIHAP.PII_TYPE_NATIONAL_ID,
    "IT_FISCAL_CODE": _PIIHAP.PII_TYPE_NATIONAL_ID,
    "IT_IDENTITY_CARD": _PIIHAP.PII_TYPE_NATIONAL_ID,
    "SG_NRIC_FIN": _PIIHAP.PII_TYPE_NATIONAL_ID,
    "AU_TFN": _PIIHAP.PII_TYPE_NATIONAL_ID,
    "IN_AADHAAR": _PIIHAP.PII_TYPE_NATIONAL_ID,
    "IN_PAN": _PIIHAP.PII_TYPE_NATIONAL_ID,
    "IN_VOTER": _PIIHAP.PII_TYPE_NATIONAL_ID,
    "PL_PESEL": _PIIHAP.PII_TYPE_NATIONAL_ID,
    "FI_PERSONAL_IDENTITY_CODE": _PIIHAP.PII_TYPE_NATIONAL_ID,
    "KR_RRN": _PIIHAP.PII_TYPE_NATIONAL_ID,
    "UK_NHS": _PIIHAP.PII_TYPE_MEDICAL_RECORD,
    "AU_MEDICARE": _PIIHAP.PII_TYPE_MEDICAL_RECORD,
}


class PresidioPIIConfig(BaseModel):
    """User-facing provider_config for the Presidio PII detection adapter.

    Presidio runs locally (no API key, no model_id).  It requires the optional
    ``presidio-analyzer`` package and a spaCy language model.
    """

    model_config = ConfigDict(extra="ignore")

    language: str = Field(
        default=DEFAULT_LANGUAGE,
        description="Language code of the documents (e.g. 'en'). Passed to the Presidio analyzer.",
    )
    spacy_model: str = Field(
        default=DEFAULT_SPACY_MODEL,
        description=(
            "spaCy model used for named-entity recognition (e.g. 'en_core_web_lg', 'en_core_web_sm'). "
            "Install it beforehand with 'python -m spacy download <model>'."
        ),
    )
    entity_mapping: dict[str, str] | None = Field(
        default=None,
        description=(
            "Optional Presidio entity type -> PII type overrides merged over the built-in mapping "
            "(e.g. {'DATE_TIME': 'DateOfBirth'}). Values must be valid pii_list entries."
        ),
    )
