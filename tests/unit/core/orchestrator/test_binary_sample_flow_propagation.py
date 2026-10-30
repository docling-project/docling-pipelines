"""End-to-end feature propagation for the Milvus binary sample flow."""

import json
from pathlib import Path

from docpipe.core.assets.flows.application.services.authoring_compiler import AuthoringCompiler
from docpipe.core.assets.flows.domain.models.authoring_flow import AuthoringFlow
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.orchestration.flow_validator import FlowValidator
from docpipe.core.orchestration.orchestrator_factory import OrchestratorFactory

SAMPLE_FLOW = Path(__file__).resolve().parents[4] / "sample_flows" / "vectordb" / "milvus_binary_integration.json"


def test_vectordb_node_receives_vector_binary_embeddings() -> None:
    """The vectordb node must see `vector_binary` so binary index config is applied to the field."""
    authoring_flow = AuthoringFlow.from_dict(data=json.loads(SAMPLE_FLOW.read_text()))
    runtime_flow = AuthoringCompiler().compile(authoring_flow=authoring_flow)
    validator = FlowValidator(orchestrator=OrchestratorFactory.create_orchestrator(orchestrator_name="python"))

    node_features = validator.propagate_features_per_node(
        flow_def=runtime_flow, global_config=runtime_flow["global_config"]
    )

    by_name = {snapshot["node_name"]: snapshot for snapshot in node_features.values()}
    embeddings_column = OperatorConstants.Columns.EMBEDDINGS_COLUMN_DEFAULT
    for node_name in ("generate_binary_embeddings", "store_in_milvus_binary"):
        feature = by_name[node_name]["available_features"][embeddings_column]
        assert feature["type"] == OperatorConstants.Types.TYPE_VECTOR_BINARY, node_name
