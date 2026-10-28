/**
 * @fileoverview Operator-related type definitions.
 * Covers both API wire types (HTTP responses/requests) and Redux state shapes.
 */

// ── Provider models types ─────────────────────────────────────────────────

/**
 * A single model entry as returned by GET /api/v1/providers/{provider}/models.
 */
export interface ModelInfo {
  model_id: string;
  description: string | null;
  functions: string[];
  embedding_dimension: number | null;
}

/**
 * Response shape of GET /api/v1/providers/{provider}/models.
 */
export interface ModelsResponse {
  provider: string;
  models: ModelInfo[];
}

// ── API wire types ───────────────────────────────────────────────────────

/**
 * Individual operator attribute / feature definition.
 *
 * Used both at the top level (`attributes` map) and recursively for nested fields
 * such as `provider_config` which can carry its own `providers` and `properties`.
 *
 * - `providers` — maps provider id → schema with its own `properties` map.
 * - `properties` — flat map of sub-field definitions, each typed as `OperatorFeature`
 *   so they can themselves carry `providers` (e.g. summarization.properties.provider_config).
 */
export interface OperatorFeature {
  type: string;
  name?: string;
  /**
   * Human-readable description served by the backend operator metadata. It is
   * English-only and not part of the react-intl catalog.
   */
  description?: string | null;
  required?: boolean | null;
  default?: unknown;
  available_for_filter?: boolean | null;
  available_for_vector_db?: boolean | null;
  sensitive?: boolean;
  valid_values?: string[];
  /** Minimum allowed value for numeric fields. */
  min_value?: number;
  /** Maximum allowed value for numeric fields. */
  max_value?: number;
  /** Maps provider id → per-provider schema. Each entry is itself an OperatorFeature. */
  providers?: Record<string, OperatorFeature>;
  /** Sub-field map. Each value is itself an OperatorFeature so nesting is supported. */
  properties?: Record<string, OperatorFeature>;
}

/**
 * Complete metadata for a single operator.
 */
export interface OperatorMetadata {
  label: string;
  category: string;
  description: string | null;
  features: Record<string, OperatorFeature>;
  required_features: string[];
  attributes: Record<string, OperatorFeature>;
  [key: string]: unknown;
}

/**
 * Response from GET /api/v1/operators/metadata.
 * Dictionary mapping operator short names to their metadata.
 */
export interface OperatorsResponse {
  [operatorName: string]: OperatorMetadata;
}

// ── Redux state types ────────────────────────────────────────────────────

/**
 * Per-node enriched feature metadata returned by enrich_flow_features.
 * Both input_features and output_features are maps of feature name → feature attributes.
 */
export interface NodeFeatureEntry {
  /** Features flowing into this node from upstream operators */
  input_features: Record<string, FeatureAttributes>;
  /** Features produced/output by this node */
  output_features: Record<string, FeatureAttributes>;
}

/**
 * Attribute shape for a single feature returned by the backend enrichment API.
 */
export interface FeatureAttributes {
  name: string;
  type: string;
  description: string;
  available_for_filter: boolean;
  available_for_vector_db: boolean;
  mandatory_for_vector_db: boolean;
  /** ID of the node that introduced this feature */
  node_id: string;
  tags: string[];
}

/**
 * A single row in the feature_mappings list returned by enrich_flow_features
 * for vectordb nodes.
 */
export interface FeatureMappingRow {
  feature_name: string;
  mapped_column_name: string;
  /** Persisted from the tearsheet so the summary table can disable mandatory rows without a live enrichment call. */
  is_mandatory?: boolean;
}

/**
 * VectorDB-specific keys injected into node.parameters by FlowEnrichmentService
 * when provider_config is non-empty.
 */
export interface VectorDBEnrichmentResult {
  available_resources: string[];
  selected_resource_schema: Record<string, unknown>;
  feature_mappings: FeatureMappingRow[];
  is_docpipe_supported_resource: { supported?: boolean; resource_name?: string };
  stored_resource_metadata: {
    vector_similarity: string | null;
    dimension_size: number | null;
  };
  available_features: Record<string, FeatureAttributes>;
}

/**
 * Redux state slice for managing operator metadata and feature options.
 * Stores all available operators and their configuration options.
 */
export interface OperatorsState {
  /** Map of operator IDs to their metadata */
  metadata: Record<string, OperatorMetadata>;
  /** Available feature options for operator configuration */
  featureOptions: Record<string, unknown>;
  /** Per-node feature metadata keyed by node ID, populated by enrich_flow_features */
  nodeFeatures: Record<string, NodeFeatureEntry>;
  /** Loading state for async operations */
  loading: boolean;
  /** Loading state for feature enrichment API call */
  featuresLoading: boolean;
  /** Error message if an operation failed, null otherwise */
  error: string | null;
}

/**
 * A single document class entry from `GET /api/v1/document_classes`.
 * Used to populate the Document Types multi-select in the Document Classifier panel.
 */
export interface DocumentClassItem {
  /** Canonical document type identifier, e.g. `"invoice"`, `"contract"` */
  document_type: string;
  /** Human-readable description of the document type */
  document_description: string;
}
