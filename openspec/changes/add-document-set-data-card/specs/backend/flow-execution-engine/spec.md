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

### Requirement: Flow definition available to operators unresolved
The compiled flow definition SHALL remain available to every operator in its configuration under `flow_definition`, so that an operator can inspect the nodes upstream of itself. Secret references inside it SHALL be left as written. The executor SHALL still resolve secret references in every other configuration key of the operator. The shape of the flow definition SHALL NOT change.

#### Scenario: Operator reads upstream nodes
- **WHEN** an operator inspects `flow_definition` in its configuration
- **THEN** it finds the nodes with their `id`, `name`, `operator`, `config`, and `input_edges`

#### Scenario: Upstream secret reference stays a reference
- **WHEN** an upstream node's configuration holds a `vault://` reference and a downstream operator is built
- **THEN** the operator's `flow_definition` still holds the reference text and the secret is not fetched for it

#### Scenario: Own parameters still resolved
- **WHEN** the operator's own configuration holds a `vault://` reference outside `flow_definition`
- **THEN** the operator receives the resolved value as before
