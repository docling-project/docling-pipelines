"""Regression tests for FastText adapter failure handling."""

from unittest.mock import MagicMock, patch

import pytest

from docpipe.core.operators.quality.language_detection.adapters.outbound.fasttext_adapter import (
    FastTextAdapter,
)
from docpipe.exceptions.docpipe_exceptions import ExternalServiceError


def test_model_acquisition_failure():
    with patch(
        "docpipe.core.operators.quality.language_detection.adapters.outbound.fasttext_adapter.FastTextModelManager"
    ) as manager_class:
        manager = manager_class.return_value
        manager.acquire_model.side_effect = RuntimeError("model unavailable")

        with pytest.raises(ExternalServiceError, match="Failed to initialize FastText model"):
            FastTextAdapter()

        manager.acquire_model.assert_called_once()


def test_model_release_failure():
    with patch(
        "docpipe.core.operators.quality.language_detection.adapters.outbound.fasttext_adapter.FastTextModelManager"
    ) as manager_class:
        manager = manager_class.return_value
        manager.acquire_model.return_value = MagicMock()
        manager.get_ref_count.return_value = 1
        manager.release_model.side_effect = RuntimeError("release failed")

        adapter = FastTextAdapter()
        adapter.cleanup()

        manager.release_model.assert_called_once()


def test_prediction_exception_wrapped():
    with patch(
        "docpipe.core.operators.quality.language_detection.adapters.outbound.fasttext_adapter.FastTextModelManager"
    ) as manager_class:
        manager = manager_class.return_value
        model = MagicMock()
        model.predict.side_effect = RuntimeError("prediction failed")
        manager.acquire_model.return_value = model
        manager.get_ref_count.return_value = 1

        adapter = FastTextAdapter()
        with pytest.raises(ExternalServiceError, match="FastText language detection failed"):
            adapter.detect_language("Hello world")


def test_invalid_predictions_raise_value_error():
    with patch(
        "docpipe.core.operators.quality.language_detection.adapters.outbound.fasttext_adapter.FastTextModelManager"
    ) as manager_class:
        manager = manager_class.return_value
        model = MagicMock()
        model.predict.return_value = ([], [])
        manager.acquire_model.return_value = model
        manager.get_ref_count.return_value = 1

        adapter = FastTextAdapter()
        with pytest.raises(ValueError, match="FastText returned invalid predictions"):
            adapter.detect_language("Hello world")
