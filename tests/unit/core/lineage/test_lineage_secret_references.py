# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Lineage must carry neither a vault reference nor the value it resolves to (spec: lineage and statistics)."""

import json
from unittest.mock import MagicMock

from docpipe.core.lineage.application.lineage_service import LineageService
from docpipe.core.lineage.dataset_naming import REFERENCE_PLACEHOLDER
from docpipe.core.lineage.domain.ports.lineage_publisher import LineagePublisherPort
from docpipe.core.lineage.utils import LineageUtils
from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator
from docpipe.core.operators.secret_fields import declared_key_names
from docpipe.core.operators.vectordb.vectordb_operator import VectorDBOperator
from docpipe.core.orchestration.models.execution_event_context import NodeCompleteContext

BUCKET_REF = "vault://hashicorp/s3#bucket"
CANARY_BUCKET = "CANARY-bucket-5e1f"


def _ingest(**provider_config: object) -> dict:
    return {"config": {"provider": "s3", "provider_config": provider_config}}


class TestDatasetIdentityFromReferences:
    def test_s3_bucket_reference_uses_placeholder_component(self) -> None:
        namespace, name = LineageUtils.derive_dataset_info_from_ingest(
            ingest_operator=_ingest(bucket=BUCKET_REF, prefix="docs/")
        )
        assert namespace == f"s3://{REFERENCE_PLACEHOLDER}"
        assert name == "docs"

    def test_identity_contains_neither_the_reference_nor_a_resolved_name(self) -> None:
        info = LineageUtils.derive_dataset_info_from_ingest(ingest_operator=_ingest(bucket=BUCKET_REF))
        text = json.dumps(info)
        assert "vault://" not in text
        assert "hashicorp" not in text
        assert CANARY_BUCKET not in text

    def test_dataset_name_derived_from_a_reference_prefix_is_masked(self) -> None:
        _, name = LineageUtils.derive_dataset_info_from_ingest(
            ingest_operator=_ingest(bucket="b", prefix="vault://hashicorp/s3#prefix")
        )
        assert name == REFERENCE_PLACEHOLDER

    def test_reference_embedded_in_a_longer_string_is_masked_whole(self) -> None:
        namespace, _ = LineageUtils.derive_dataset_info_from_ingest(
            ingest_operator=_ingest(bucket="pre-vault://hashicorp/s3#bucket-post")
        )
        assert namespace == f"s3://{REFERENCE_PLACEHOLDER}"

    def test_other_components_stay_literal(self) -> None:
        namespace, name = LineageUtils.derive_dataset_info_from_ingest(
            ingest_operator=_ingest(bucket="plain-bucket", prefix="a/b/")
        )
        assert (namespace, name) == ("s3://plain-bucket", "a/b")

    def test_reference_in_the_legacy_connection_params_is_masked(self) -> None:
        operator = {"config": {"provider": "s3", "connection_params": {"bucket": BUCKET_REF}}}
        namespace, _ = LineageUtils.derive_dataset_info_from_ingest(ingest_operator=operator)
        assert namespace == f"s3://{REFERENCE_PLACEHOLDER}"

    def test_milvus_sink_host_reference_is_masked(self) -> None:
        info = LineageUtils.derive_dataset_info_from_sink(
            operator_def={
                "operator": "vectordb",
                "config": {
                    "provider": "milvus",
                    "provider_config": {"auth_type": "standalone", "host": "vault://hashicorp/m#host"},
                },
            }
        )
        assert info is not None
        assert "vault://" not in json.dumps(info)

    def test_a_reference_as_the_provider_name_is_masked(self) -> None:
        namespace, _ = LineageUtils.derive_dataset_info_from_ingest(
            ingest_operator={"config": {"provider": BUCKET_REF, "provider_config": {}}}
        )
        assert "vault://" not in namespace


class TestStatisticsKeysByDeclaration:
    def test_declared_key_names_cover_every_provider(self) -> None:
        names = declared_key_names(metadata=IngestSourceOperator.get_metadata())
        assert {"secret_key", "access_key", "endpoint_url", "bucket"} <= names

    def test_declared_key_names_cover_vectordb_provider_fields(self) -> None:
        names = declared_key_names(metadata=VectorDBOperator.get_metadata())
        assert {"token", "password"} <= names

    def test_a_declared_key_is_excluded_even_when_not_on_the_fixed_list(self) -> None:
        assert LineageUtils.is_secret_statistic_key(key="endpoint_url", secret_field_names=frozenset({"endpoint_url"}))

    def test_the_fixed_list_remains_a_floor(self) -> None:
        assert LineageUtils.is_secret_statistic_key(key="Password", secret_field_names=frozenset())

    def test_an_ordinary_metric_is_kept(self) -> None:
        assert not LineageUtils.is_secret_statistic_key(
            key="processed_docs", secret_field_names=frozenset({"endpoint_url"})
        )

    def test_node_complete_event_drops_declared_keys_from_the_stats_facet(self) -> None:
        publisher = MagicMock(spec=LineagePublisherPort)
        service = LineageService(publisher=publisher, namespace="docpipe://test", producer="https://test.producer")
        context = NodeCompleteContext(
            flow_id="f",
            flow_name="flow",
            job_run_id="run-1",
            node_id="n1",
            node_name="ingest",
            operator_type="ingest_source",
            metadata={"processed_docs": 3, "endpoint_url": "https://leak.example", "bucket": CANARY_BUCKET},
            secret_field_names=declared_key_names(metadata=IngestSourceOperator.get_metadata()),
        )
        service.emit_node_complete(context=context)
        run = publisher.publish.call_args.kwargs["run"]
        stats = run.facets["docpipeStats"]
        assert stats["processedDocs"] == 3
        assert "endpointUrl" not in stats
        assert "bucket" not in stats
        assert CANARY_BUCKET not in json.dumps(run.facets, default=str)
