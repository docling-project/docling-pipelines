# properties-panel/custom-panels/chunker-panel Specification

## Purpose

The chunker custom panel is the configuration form for the `chunker` operator. It lets users select a chunking strategy (simple, semantic, or hybrid), configure the fields relevant to that strategy, optionally enable Docling Serve for remote chunking, and configure a summarization step.

## ADDED Requirements

### Requirement: Chunk type drives field visibility
The panel SHALL show only the configuration fields relevant to the selected chunk type.

#### Scenario: Simple chunk type shows size and overlap
- **WHEN** chunk_type is set to "simple"
- **THEN** chunk_size, chunk_overlap, and chunk_overlap_percentage fields are visible

#### Scenario: Semantic chunk type shows embeddings model fields
- **WHEN** chunk_type is set to "semantic"
- **THEN** semantic_embeddings_model, breakpoint_threshold_type, and breakpoint_threshold_amount fields are visible

#### Scenario: Hybrid chunk type shows both sets
- **WHEN** chunk_type is set to "hybrid"
- **THEN** chunk_size, chunk_overlap, chunk_overlap_percentage, and docling_tokenizer fields are visible

### Requirement: Docling Serve toggle forces hybrid
The panel SHALL automatically set chunk_type to "hybrid" when the Docling Serve toggle is enabled.

#### Scenario: Enabling Docling Serve sets chunk type
- **WHEN** the user enables the "Use Docling Serve" toggle
- **THEN** chunk_type is set to "hybrid" and the hybrid configuration fields are shown

### Requirement: Summarization accordion
The panel SHALL provide an expandable summarization section with an enable toggle and, when enabled, a JSON configuration textarea.

#### Scenario: Summarization config hidden when disabled
- **WHEN** summarization is not enabled
- **THEN** the summarization JSON textarea is not rendered

#### Scenario: Summarization config shown when enabled
- **WHEN** the user enables summarization
- **THEN** the summarization JSON configuration textarea becomes visible
