/**
 * @file Constants for the VectorDB operator properties panel and feature mapping tearsheet.
 *
 * Provider-specific differences in key names, labels, default values and
 * capabilities are expressed as data in `PROVIDER_CONFIG_MAP`. Adding a provider
 * takes a map entry plus its connection and authentication controls in the
 * panel (see `WeaviateConnectionFields` for a provider with its own controls).
 */

import type { MessageDescriptor } from 'react-intl';
import { messages as tearsheetMessages } from './VectorDBFeatureMappingTearsheet.messages';

export const VECTORDB_ATTRIBUTES = {
  PROVIDER: 'provider',
  PROVIDER_CONFIG: 'provider_config',
  FEATURE_MAPPINGS: 'feature_mappings',
  ADD_SPARSE_VECTOR: 'add_sparse_vector',
} as const;

export const VECTORDB_LABELS = {
  /** Sentinel value for the resource ComboBox "create a new resource" option. */
  CREATE_NEW: 'Create new',
} as const;

export const VECTORDB_PROVIDERS = {
  OPENSEARCH: 'opensearch',
  MILVUS: 'milvus',
  WEAVIATE: 'weaviate',
} as const;

// ── OpenSearch constants ──────────────────────────────────────────────────────

/** Fallback space_type options when metadata valid_values are unavailable. */
export const DEFAULT_SPACE_TYPE_VALUES = ['l2', 'cosine', 'inner_product'];

/** Fallback engine options when metadata valid_values are unavailable. */
export const DEFAULT_ENGINE_VALUES = ['faiss', 'lucene', 'nmslib', 'jvector'];

// ── Milvus constants ──────────────────────────────────────────────────────────

/** Fallback metric_type options when metadata valid_values are unavailable. */
export const DEFAULT_METRIC_TYPE_VALUES = ['L2', 'IP', 'COSINE', 'BM25', 'HAMMING', 'JACCARD'];

/** Milvus binary similarity metrics */
export const MILVUS_BINARY_METRIC_VALUES = ['HAMMING', 'JACCARD'] as const;

/** Milvus dense similarity metrics */
export const MILVUS_DENSE_METRIC_VALUES = ['L2', 'IP', 'COSINE'] as const;

/** Milvus GPU index (GPU_*) metrics — GPU mode accepts only L2 and IP. */
export const MILVUS_GPU_METRIC_VALUES = ['L2', 'IP'] as const;

// ── Weaviate constants ────────────────────────────────────────────────────────

/** Fallback distance_metric options when metadata valid_values are unavailable. */
const DEFAULT_DISTANCE_METRIC_VALUES = ['cosine', 'dot', 'l2-squared', 'manhattan', 'hamming'];

/** Weaviate collection names start with an upper-case ASCII letter (mirrors the backend rule). */
const WEAVIATE_COLLECTION_NAME_PATTERN = /^[A-Z][_0-9A-Za-z]*$/;

/** Example collection name used as the input placeholder. */
const WEAVIATE_COLLECTION_NAME_EXAMPLE = 'DocumentChunks';

// ── Provider configuration map ───────────────────────────────────────────────

/**
 * All provider-specific configuration for the VectorDB panel and tearsheet.
 * Components read `cfg = getProviderConfig(provider)` and use `cfg.*` throughout.
 */

/** Wording family for the sparse-retrieval checkbox in the tearsheet. */
export type SparseLabelKind = 'sparse-vectors' | 'bm25';

/** Fields shared by every provider configuration. */
interface ProviderConfigBase {
  /** Key in provider_config that holds the resource name (e.g. index_name / collection_name). */
  resourceNameKey: string;
  /** User-facing singular label for the resource type (e.g. "index" / "collection"). */
  resourceLabel: string;
  /** Key in provider_config that holds the similarity metric (e.g. space_type / metric_type). */
  similarityKey: string;
  /** Localizable label for the similarity field (e.g. "Space type" / "Metric type"). */
  similarityLabel: MessageDescriptor;
  /** Fallback similarity options when operator metadata returns none. */
  defaultSimilarityValues: string[];
  /**
   * Keys stripped from provider_config before enrichment API calls.
   *
   * Includes resource identity keys (e.g. `index_name`, `collection_name`) and
   * index-creation-time parameters (e.g. `space_type`, `engine`, `algorithm`,
   * `index_type`). These are fixed at creation and must not bleed into connection-
   * level calls for a different or new resource.
   */
  resourceSpecificKeys: string[];
  /**
   * Keys owned by the structured connection and authentication controls. They are
   * hidden from the Advanced JSON textarea and always win over its content.
   */
  connectionKeys: string[];
  /**
   * Resource-specific keys that have no structured control. They stay visible and
   * editable in the Advanced JSON textarea but are still stripped from enrichment.
   */
  advancedOnlyKeys: string[];
  /** Whether the provider can retrieve with a sparse/keyword signal (shows the tearsheet checkbox). */
  supportsSparse: boolean;
  /** Wording of the sparse checkbox; meaningful only when `supportsSparse` is true. */
  sparseLabel?: SparseLabelKind;
  /** Tooltip explaining the sparse checkbox; the tooltip is shown only when this is set. */
  sparseTooltip?: MessageDescriptor;
  /** Show the provider-reported reason in the unsupported-resource state instead of the generic text. */
  showsUnsupportedReason?: boolean;
  /** Naming rule for a new resource. Absent = the generic rule applies. */
  resourceNamePattern?: RegExp;
  /** Valid example name used as the new-name placeholder when `resourceNamePattern` is set. */
  resourceNameExample?: string;
  /** Default provider_config JSON shown in the textarea when no config is saved yet. null = show empty textarea. */
  defaultConfig: Record<string, unknown> | null;
}

/** Provider that exposes an engine field (e.g. OpenSearch). */
interface ProviderConfigWithEngine extends ProviderConfigBase {
  hasEngine: true;
  /** Key in provider_config for the engine. */
  engineKey: string;
}

/** Provider without an engine field (e.g. Milvus). */
interface ProviderConfigNoEngine extends ProviderConfigBase {
  hasEngine: false;
  engineKey?: never;
}

/** Discriminated union — narrow with `cfg.hasEngine` to access engine fields without `!`. */
export type ProviderConfig = ProviderConfigWithEngine | ProviderConfigNoEngine;

const PROVIDER_CONFIG_MAP: Record<string, ProviderConfig> = {
  [VECTORDB_PROVIDERS.OPENSEARCH]: {
    resourceNameKey:         'index_name',
    resourceLabel:           'index',
    similarityKey:           'space_type',
    similarityLabel:         tearsheetMessages.spaceTypeLabel,
    defaultSimilarityValues: DEFAULT_SPACE_TYPE_VALUES,
    hasEngine:               true,
    engineKey:               'engine',
    resourceSpecificKeys:    ['index_name', 'space_type', 'engine', 'algorithm'],
    connectionKeys: [
      'host', 'port', 'use_ssl', 'verify_certs',
      'username', 'password', 'jwt_token', 'aws_auth', 'aws_region',
    ],
    advancedOnlyKeys:        ['algorithm'],
    supportsSparse:          false,
    defaultConfig:           null,
  },
  [VECTORDB_PROVIDERS.MILVUS]: {
    resourceNameKey:         'collection_name',
    resourceLabel:           'collection',
    similarityKey:           'metric_type',
    similarityLabel:         tearsheetMessages.metricTypeLabel,
    defaultSimilarityValues: DEFAULT_METRIC_TYPE_VALUES,
    hasEngine:               false,
    resourceSpecificKeys:    ['collection_name', 'metric_type', 'index_type'],
    connectionKeys: [
      'host', 'port', 'database', 'secure',
      'auth_type', 'username', 'password', 'token', 'uri',
    ],
    advancedOnlyKeys:        ['index_type'],
    supportsSparse:          true,
    sparseLabel:             'sparse-vectors',
    defaultConfig:           null,
  },
  [VECTORDB_PROVIDERS.WEAVIATE]: {
    resourceNameKey:         'collection_name',
    resourceLabel:           'collection',
    similarityKey:           'distance_metric',
    similarityLabel:         tearsheetMessages.distanceMetricLabel,
    defaultSimilarityValues: DEFAULT_DISTANCE_METRIC_VALUES,
    hasEngine:               false,
    resourceSpecificKeys:    ['collection_name', 'distance_metric', 'index_type', 'index_parameters'],
    connectionKeys: [
      'connection_type', 'host', 'port', 'secure',
      'grpc_host', 'grpc_port', 'grpc_secure', 'cluster_url',
      'auth_type', 'api_key', 'bearer_token', 'username', 'password',
    ],
    advancedOnlyKeys:        ['index_type', 'index_parameters'],
    supportsSparse:          true,
    sparseLabel:             'bm25',
    sparseTooltip:           tearsheetMessages.bm25Tooltip,
    showsUnsupportedReason:  true,
    resourceNamePattern:     WEAVIATE_COLLECTION_NAME_PATTERN,
    resourceNameExample:     WEAVIATE_COLLECTION_NAME_EXAMPLE,
    defaultConfig:           null,
  },
};

/**
 * Returns the provider-specific config for the given provider string.
 * Falls back to OpenSearch config for unknown providers so the UI never breaks.
 */
export function getProviderConfig(provider: string): ProviderConfig {
  return PROVIDER_CONFIG_MAP[provider] ?? (PROVIDER_CONFIG_MAP[VECTORDB_PROVIDERS.OPENSEARCH] as ProviderConfig);
}

/** Canonical default target column/field names for standard feature names. */
export const DEFAULT_COLUMN_MAPPINGS: Record<string, string> = {
  doc_id_hash: 'pk',
  id: 'document_id',
  name: 'document_name',
  embeddings: 'vector_embeddings',
  sparse_embeddings: 'sparse_embeddings',
  content: 'text',
};

/**
 * Omit a set of keys from a provider_config object before sending to the API.
 * Used to strip resource-specific saved values so the backend computes fresh ones.
 */
export function omitProviderConfigKeys(
  config: Record<string, unknown>,
  keys: string[]
): Record<string, unknown> {
  const keySet = new Set(keys);
  return Object.fromEntries(Object.entries(config).filter(([k]) => !keySet.has(k)));
}
