# Spec Delta

## ADDED Requirements

### Requirement: Session context exposes the flow name
The session context available to operators SHALL expose `flow_name` beside `flow_id`. The orchestrator SHALL set it when execution starts, from the `name` of the flow definition, and SHALL fall back to the flow ID when the definition has no name. Prefect batch workers SHALL restore it from the flow definition they receive. When no flow is running, `flow_name` SHALL be null.

#### Scenario: Name taken from the flow definition
- **WHEN** a flow whose definition is named `invoice-ingest` starts executing
- **THEN** the session context reports `flow_name` `invoice-ingest` to every operator of that run

#### Scenario: Fallback to the flow ID
- **WHEN** the flow definition has no name and the flow ID is `f-123`
- **THEN** the session context reports `flow_name` `f-123`

#### Scenario: Batch worker restores the name
- **WHEN** a micro-batch runs in a Prefect worker
- **THEN** operators in that worker see the same `flow_name` as the parent run

#### Scenario: No flow running
- **WHEN** an operator is used outside a flow run
- **THEN** `flow_name` is null and the operator does not fail

### Requirement: Flow definition available to operators
The compiled flow definition SHALL remain available to every operator in its configuration under `flow_definition`, so that an operator can inspect the nodes upstream of itself. This change SHALL NOT alter the shape of the flow definition or of any other configuration key.

#### Scenario: Operator reads upstream nodes
- **WHEN** an operator inspects `flow_definition` in its configuration
- **THEN** it finds the nodes with their `id`, `name`, `operator`, `config`, and `input_edges`
