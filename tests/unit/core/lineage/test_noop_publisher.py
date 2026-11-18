"""Unit tests for NoOpLineagePublisherAdapter."""

from docpipe.core.lineage.adapters.noop.publisher import NoOpLineagePublisherAdapter
from docpipe.core.lineage.domain.models import (
    LineageDataset,
    LineageEventType,
    LineageJob,
    LineageRun,
)
from docpipe.core.lineage.domain.ports import LineagePublisherPort


def test_noop_publisher_implements_port() -> None:
    """Verify that NoOpLineagePublisherAdapter is an instance of LineagePublisherPort."""
    publisher = NoOpLineagePublisherAdapter()
    assert isinstance(publisher, LineagePublisherPort)


def test_noop_publisher_publish_is_noop() -> None:
    """Verify that publish executes silently without errors."""
    publisher = NoOpLineagePublisherAdapter()
    job = LineageJob(namespace="docpipe://local", name="test_job")
    run = LineageRun(run_id="run-123")
    inputs = [LineageDataset(namespace="s3://bucket", name="docs/input")]
    outputs = [LineageDataset(namespace="s3://bucket", name="docs/output")]

    # Should not raise any exception
    publisher.publish(
        event_type=LineageEventType.START,
        run=run,
        job=job,
        inputs=inputs,
        outputs=outputs,
    )
