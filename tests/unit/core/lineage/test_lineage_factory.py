"""Unit tests for lineage factory."""

from unittest.mock import patch

from docpipe.core.constants.constants import LineageConstants
from docpipe.core.lineage.adapters.noop.publisher import NoOpLineagePublisherAdapter
from docpipe.core.lineage.adapters.openlineage.observer import OpenLineageExecutionObserver
from docpipe.core.lineage.application.lineage_factory import create_lineage_observer


def test_factory_returns_none_when_disabled(monkeypatch) -> None:
    """Verify factory returns None when DOCPIPE_LINEAGE_ENABLED != true."""
    monkeypatch.setattr(LineageConstants, "DEFAULT_ENABLED", "false")
    observer = create_lineage_observer()
    assert observer is None


def test_factory_returns_observer_with_openlineage_when_enabled(monkeypatch) -> None:
    """Verify factory creates an OpenLineageExecutionObserver when enabled."""
    monkeypatch.setattr(LineageConstants, "DEFAULT_ENABLED", "true")
    observer = create_lineage_observer()
    assert observer is not None
    assert isinstance(observer, OpenLineageExecutionObserver)


def test_factory_falls_back_to_noop_when_import_error(monkeypatch) -> None:
    """Verify factory uses NoOpLineagePublisherAdapter when openlineage import fails."""
    monkeypatch.setattr(LineageConstants, "DEFAULT_ENABLED", "true")
    with patch(
        "docpipe.core.lineage.adapters.openlineage.publisher.OpenLineagePublisherAdapter.__init__",
        side_effect=ImportError("No module named openlineage"),
    ):
        observer = create_lineage_observer()
        assert observer is not None
        assert isinstance(observer, OpenLineageExecutionObserver)
        assert isinstance(observer._service._publisher, NoOpLineagePublisherAdapter)


def test_factory_falls_back_to_noop_on_generic_exception(monkeypatch) -> None:
    """Verify factory uses NoOpLineagePublisherAdapter when adapter init raises a non-ImportError."""
    monkeypatch.setattr(LineageConstants, "DEFAULT_ENABLED", "true")
    with patch(
        "docpipe.core.lineage.adapters.openlineage.publisher.OpenLineagePublisherAdapter.__init__",
        side_effect=RuntimeError("connection refused"),
    ):
        observer = create_lineage_observer()
        assert observer is not None
        assert isinstance(observer, OpenLineageExecutionObserver)
        assert isinstance(observer._service._publisher, NoOpLineagePublisherAdapter)


def test_factory_returns_none_on_unexpected_outer_error(monkeypatch) -> None:
    """Verify factory returns None and does not raise when observer construction itself fails."""
    monkeypatch.setattr(LineageConstants, "DEFAULT_ENABLED", "true")
    with patch(
        "docpipe.core.lineage.adapters.openlineage.observer.OpenLineageExecutionObserver.__init__",
        side_effect=RuntimeError("unexpected failure"),
    ):
        observer = create_lineage_observer()
        assert observer is None
