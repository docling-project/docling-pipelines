# Spec Delta

## Purpose

Allows more than one component to observe flow lifecycle events. Today the orchestrator holds a single observer slot (used by lineage). Derivative recording needs the same completion event.

## ADDED Requirements

### Requirement: Composite lifecycle observation
The orchestrator factory SHALL pass a single `ExecutionLifecycleObserverPort` to the orchestrator that forwards every lifecycle event to all enabled observers in a fixed order (lineage first, derivative recorder second). An observer raising an exception MUST NOT prevent later observers from receiving the event. With no enabled observer, the factory SHALL pass none, as today. Disabled lineage (`DOCPIPE_LINEAGE_ENABLED` not true) MUST NOT disable derivative recording.

#### Scenario: Both observers receive completion
- **WHEN** lineage is enabled and a flow completes
- **THEN** both the lineage observer and the derivative recorder receive `on_flow_complete`

#### Scenario: Lineage disabled
- **WHEN** lineage is disabled and a flow completes
- **THEN** the derivative recorder still receives `on_flow_complete`

#### Scenario: One observer fails
- **WHEN** the first observer raises in `on_flow_complete`
- **THEN** the second observer still receives the event and the flow result is unchanged

#### Scenario: Lineage strict mode
- **WHEN** `DOCPIPE_LINEAGE_STRICT=true` and the lineage observer raises
- **THEN** the error is re-raised as today, after the remaining observers were called

### Requirement: Node completion metadata available to observers
Observers SHALL be able to learn, for each completed `document_set` node, the document set id written by that node, using the existing `on_node_complete` event (`NodeCompleteContext.metadata`) together with `FlowCompleteContext.flow_def` on `on_flow_complete`. No new event type is introduced.

#### Scenario: Document set id available
- **WHEN** a flow with a `document_set` node completes
- **THEN** an observer that recorded `on_node_complete` metadata for that node can read the document set id when `on_flow_complete` arrives

#### Scenario: Batched execution
- **WHEN** micro-batching runs the `document_set` node once per batch
- **THEN** the observer records the derivative once per distinct document set id, not once per batch
