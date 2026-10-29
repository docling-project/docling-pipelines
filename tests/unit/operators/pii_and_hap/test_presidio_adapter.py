# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for PresidioPIIAdapter (Presidio analyzer mocked; presidio-analyzer not required)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from docpipe.core.operators.quality.pii_and_hap.adapters.outbound.presidio.adapter import (
    PRESIDIO_INSTALL_HINT,
    PresidioPIIAdapter,
)
from docpipe.core.operators.quality.pii_and_hap.adapters.outbound.presidio.config import (
    ADAPTER_NAME,
    DEFAULT_PRESIDIO_ENTITY_MAPPING,
    PresidioPIIConfig,
)
from docpipe.core.operators.quality.pii_and_hap.domain.models import PIIHAPDetectionResponse
from docpipe.core.operators.quality.pii_and_hap.pii_and_hap_helper import DEFAULT_PII_TYPES_OF_CONCERN
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.hap_detection_port import HAPDetectionPort
from docpipe.core.operators.quality.pii_and_hap.ports.outbound.pii_detection_port import PIIDetectionPort
from docpipe.exceptions.docpipe_exceptions import DocpipeException

_BUILD_ANALYZER = (
    "docpipe.core.operators.quality.pii_and_hap.adapters.outbound.presidio.adapter.PresidioPIIAdapter._build_analyzer"
)
_IMPORT_MODULE = "docpipe.core.operators.quality.pii_and_hap.adapters.outbound.presidio.adapter.importlib.import_module"

_TEXT = "Contact John Smith at john@example.com on 2024-01-01."


def _result(entity_type: str, start: int, end: int, score: float = 0.85) -> SimpleNamespace:
    """Mimic presidio_analyzer.RecognizerResult."""
    return SimpleNamespace(entity_type=entity_type, start=start, end=end, score=score)


@pytest.fixture
def mock_analyzer():
    analyzer = MagicMock()
    analyzer.analyze.return_value = [
        _result("PERSON", 8, 18),
        _result("EMAIL_ADDRESS", 22, 38, 1.0),
        _result("DATE_TIME", 42, 52),  # unmapped by default
    ]
    return analyzer


@pytest.fixture
def adapter(mock_analyzer):
    with patch(_BUILD_ANALYZER, return_value=mock_analyzer):
        inst = PresidioPIIAdapter(model_id="", provider_config={})
        assert inst.validate()["valid"] is True
    return inst


# ---------------------------------------------------------------------------
# Class metadata / capabilities
# ---------------------------------------------------------------------------


def test_adapter_is_pii_only():
    assert ADAPTER_NAME == "presidio"
    assert PresidioPIIAdapter.ADAPTER_NAME == "presidio"
    assert PresidioPIIAdapter.SUPPORTS_PII is True
    assert PresidioPIIAdapter.SUPPORTS_HAP is False
    assert issubclass(PresidioPIIAdapter, PIIDetectionPort)
    assert not issubclass(PresidioPIIAdapter, HAPDetectionPort)
    assert PresidioPIIAdapter.get_capabilities() == ["pii"]


def test_model_id_not_required():
    assert PresidioPIIAdapter.REQUIRES_MODEL_ID is False
    assert PresidioPIIAdapter.validate_provider_config(provider_config={}, config_key="pii_provider_config") == []


def test_config_schema():
    assert PresidioPIIAdapter.get_config_schema() is PresidioPIIConfig
    config = PresidioPIIConfig()
    assert config.language == "en"
    assert config.spacy_model == "en_core_web_lg"
    assert config.entity_mapping is None


def test_default_mapping_targets_operator_vocabulary():
    assert set(DEFAULT_PRESIDIO_ENTITY_MAPPING.values()) <= set(DEFAULT_PII_TYPES_OF_CONCERN)
    assert DEFAULT_PRESIDIO_ENTITY_MAPPING["EMAIL_ADDRESS"] == "EmailAddress"
    assert DEFAULT_PRESIDIO_ENTITY_MAPPING["US_SSN"] == "SocialSecurityNumber"
    assert DEFAULT_PRESIDIO_ENTITY_MAPPING["CREDIT_CARD"] == "CreditCardNumber"
    assert DEFAULT_PRESIDIO_ENTITY_MAPPING["PERSON"] == "PersonName"
    assert "DATE_TIME" not in DEFAULT_PRESIDIO_ENTITY_MAPPING
    assert "LOCATION" not in DEFAULT_PRESIDIO_ENTITY_MAPPING


# ---------------------------------------------------------------------------
# validate()
# ---------------------------------------------------------------------------


def test_validate_reports_install_hint_when_presidio_missing():
    with patch(_IMPORT_MODULE, side_effect=ImportError("No module named 'presidio_analyzer'")):
        inst = PresidioPIIAdapter(model_id="", provider_config={})
        result = inst.validate()
    assert result["valid"] is False
    assert result["errors"] == [PRESIDIO_INSTALL_HINT]
    assert "pip install presidio-analyzer" in PRESIDIO_INSTALL_HINT


def test_validate_reports_spacy_model_problems():
    with patch(_BUILD_ANALYZER, side_effect=OSError("[E050] Can't find model 'en_core_web_lg'")):
        inst = PresidioPIIAdapter(model_id="", provider_config={})
        result = inst.validate()
    assert result["valid"] is False
    assert "Failed to initialise Presidio AnalyzerEngine" in result["errors"][0]
    assert "python -m spacy download en_core_web_lg" in result["errors"][0]


def test_validate_builds_analyzer_once(mock_analyzer):
    with patch(_BUILD_ANALYZER, return_value=mock_analyzer) as build:
        inst = PresidioPIIAdapter(model_id="", provider_config={"language": "de", "spacy_model": "de_core_news_sm"})
        inst.validate()
        inst.detect_pii(text=_TEXT, threshold=0.5)
    build.assert_called_once_with(language="de", spacy_model="de_core_news_sm")


def test_validate_rejects_invalid_entity_mapping():
    inst = PresidioPIIAdapter(model_id="", provider_config={"entity_mapping": {"DATE_TIME": "Birthday"}})
    result = inst.validate()
    assert result["valid"] is False
    assert "not valid PII types" in result["errors"][0]


def test_validate_rejects_malformed_config():
    inst = PresidioPIIAdapter(model_id="", provider_config={"entity_mapping": "not-a-dict"})
    result = inst.validate()
    assert result["valid"] is False
    assert "Invalid Presidio provider_config" in result["errors"][0]


def test_validate_provider_config_static_checks():
    errors = PresidioPIIAdapter.validate_provider_config(
        provider_config={"entity_mapping": {"X": "Nope"}}, config_key="pii_provider_config"
    )
    assert len(errors) == 1
    assert errors[0].startswith("pii_provider_config: ")


# ---------------------------------------------------------------------------
# detect_pii()
# ---------------------------------------------------------------------------


def test_detect_pii_maps_entities_and_drops_unmapped(adapter, mock_analyzer):
    response = adapter.detect_pii(text=_TEXT, threshold=0.6)

    mock_analyzer.analyze.assert_called_once_with(text=_TEXT, language="en", score_threshold=0.6)
    assert isinstance(response, PIIHAPDetectionResponse)
    assert [d.detection for d in response.detections] == ["PersonName", "EmailAddress"]
    email = response.detections[1]
    assert email.detection_type == "pii"
    assert (email.start, email.end, email.score) == (22, 38, 1.0)
    assert email.text == "john@example.com"
    assert email.evidences == [{"source": "presidio", "entity_type": "EMAIL_ADDRESS"}]


def test_detect_pii_entity_mapping_override(mock_analyzer):
    with patch(_BUILD_ANALYZER, return_value=mock_analyzer):
        inst = PresidioPIIAdapter(
            model_id="",
            provider_config={"entity_mapping": {"DATE_TIME": "DateOfBirth", "PERSON": "NationalID"}},
        )
        response = inst.detect_pii(text=_TEXT, threshold=0.5)
    assert [d.detection for d in response.detections] == ["NationalID", "EmailAddress", "DateOfBirth"]


def test_detect_pii_no_results(adapter, mock_analyzer):
    mock_analyzer.analyze.return_value = []
    response = adapter.detect_pii(text="nothing here", threshold=0.5)
    assert response.detections == []
    assert response.input_text == "nothing here"


def test_detect_pii_wraps_analyzer_errors(adapter, mock_analyzer):
    mock_analyzer.analyze.side_effect = RuntimeError("boom")
    with pytest.raises(DocpipeException, match="Presidio PII detection failed: boom"):
        adapter.detect_pii(text=_TEXT, threshold=0.5)


def test_detect_pii_raises_install_hint_when_presidio_missing():
    with patch(_IMPORT_MODULE, side_effect=ImportError("missing")):
        inst = PresidioPIIAdapter(model_id="", provider_config={})
        with pytest.raises(DocpipeException, match="presidio-analyzer"):
            inst.detect_pii(text=_TEXT, threshold=0.5)


def test_build_analyzer_uses_spacy_nlp_engine():
    analyzer_module = MagicMock()
    nlp_module = MagicMock()

    def _import(name):
        return {"presidio_analyzer": analyzer_module, "presidio_analyzer.nlp_engine": nlp_module}[name]

    with patch(_IMPORT_MODULE, side_effect=_import):
        PresidioPIIAdapter._build_analyzer(language="en", spacy_model="en_core_web_sm")

    nlp_module.NlpEngineProvider.assert_called_once_with(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
        }
    )
    analyzer_module.AnalyzerEngine.assert_called_once_with(
        nlp_engine=nlp_module.NlpEngineProvider.return_value.create_engine.return_value,
        supported_languages=["en"],
    )
