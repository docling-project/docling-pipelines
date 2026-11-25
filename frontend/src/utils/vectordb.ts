/**
 * @file VectorDB provider-config helpers for properties panels.
 *
 * Pure functions only. Index type and metric option filtering is driven by the `applicability`
 * block of the operator metadata, with static fallbacks so the form still works against a
 * backend that does not send it.
 */

/** One Milvus index family (CPU dense, GPU or binary) as described by the operator metadata. */
export interface IndexFamily {
  id: string;
  index_types: string[];
  metric_types: string[];
  feature_types: string[];
}

/** The `applicability` block under `providers.<provider>` in the VectorDB operator metadata. */
export interface VectorDBApplicability {
  /** Milvus: index families with the metrics and feature types they apply to. */
  index_families?: IndexFamily[];
  /** Milvus Lite: the supported index types and the default. */
  lite?: { index_types: string[]; default: string };
  /** OpenSearch: the algorithms each KNN engine supports. */
  engine_algorithms?: Record<string, string[]>;
}

/** Feature types that decide which vector fields a collection will hold. */
export const VECTOR_FEATURE_TYPES = {
  DENSE: 'vector',
  BINARY: 'vector_binary',
} as const;

/** Static fallback used when the operator metadata carries no `applicability` block. */
export const FALLBACK_MILVUS_FAMILIES: IndexFamily[] = [
  {
    id: 'cpu_dense',
    index_types: ['FLAT', 'IVF_FLAT', 'IVF_SQ8', 'IVF_PQ', 'HNSW', 'DISKANN', 'AUTOINDEX'],
    metric_types: ['L2', 'IP', 'COSINE'],
    feature_types: [VECTOR_FEATURE_TYPES.DENSE],
  },
  {
    id: 'gpu',
    index_types: ['GPU_CAGRA', 'GPU_IVF_FLAT', 'GPU_IVF_PQ', 'GPU_BRUTE_FORCE'],
    metric_types: ['L2', 'IP'],
    feature_types: [VECTOR_FEATURE_TYPES.DENSE],
  },
  {
    id: 'binary',
    index_types: ['BIN_FLAT', 'BIN_IVF_FLAT'],
    metric_types: ['HAMMING', 'JACCARD'],
    feature_types: [VECTOR_FEATURE_TYPES.BINARY],
  },
];

/** Static fallback for Milvus Lite. */
export const FALLBACK_MILVUS_LITE = { index_types: ['FLAT'], default: 'FLAT' };

/** Sparse (BM25) metric, offered only where no dense field uses the configured metric. */
const SPARSE_METRIC = 'BM25';

/** Vector modes whose index family is fixed by the mode itself. */
const MODE_TO_FAMILY: Record<string, string> = {
  dense: 'cpu_dense',
  gpu: 'gpu',
  binary: 'binary',
};

/**
 * True when provider_config selects Milvus GPU mode: `vector_mode` is "gpu", or
 * `vector_mode` is unset and `index_type` starts with "GPU_" (the backend infers the
 * mode from the index type the same way).
 */
export function isMilvusGpuMode(providerConfig: Record<string, unknown>): boolean {
  const { vector_mode: vectorMode, index_type: indexType } = providerConfig;
  if (vectorMode) { return vectorMode === 'gpu'; }
  return typeof indexType === 'string' && indexType.startsWith('GPU_');
}

/** Returns the Milvus index family that contains `indexType`, or undefined when none does. */
export function getMilvusFamily(
  indexType: string,
  applicability?: VectorDBApplicability
): IndexFamily | undefined {
  const families = applicability?.index_families ?? FALLBACK_MILVUS_FAMILIES;
  return families.find((family) => family.index_types.includes(indexType));
}

/** Input for {@link getMilvusIndexTypeOptions}. */
export interface MilvusIndexTypeContext {
  applicability?: VectorDBApplicability;
  /** `provider_config.auth_type`; `lite` restricts the options to the Lite subset. */
  authType?: string;
  /** Types of the vector features that will be mapped (`vector`, `vector_binary`). */
  featureTypes: string[];
  /** Saved `provider_config.vector_mode`, when set. */
  vectorMode?: string;
  /** Full list of index types from `valid_values`; options outside it are dropped. */
  validValues?: string[];
}

/**
 * Index types the user may select for a Milvus collection.
 *
 * - Lite: only the Lite subset.
 * - Otherwise: every family whose feature type is present among the mapped features. With no vector
 *   feature known, all families are offered.
 * - An explicit `vector_mode` narrows the result to that mode's family, unless that would leave nothing.
 */
export function getMilvusIndexTypeOptions(context: MilvusIndexTypeContext): string[] {
  const { applicability, authType, featureTypes, vectorMode, validValues } = context;
  const families = applicability?.index_families ?? FALLBACK_MILVUS_FAMILIES;
  const allowed = (values: string[]): string[] =>
    validValues ? values.filter((value) => validValues.includes(value)) : values;

  if (authType === 'lite') {
    return allowed((applicability?.lite ?? FALLBACK_MILVUS_LITE).index_types);
  }

  const present = new Set(featureTypes);
  const hasVectorFeature = featureTypes.some(
    (type) => type === VECTOR_FEATURE_TYPES.DENSE || type === VECTOR_FEATURE_TYPES.BINARY
  );
  let candidates = hasVectorFeature
    ? families.filter((family) => family.feature_types.some((type) => present.has(type)))
    : families;

  const modeFamily = vectorMode ? MODE_TO_FAMILY[vectorMode] : undefined;
  if (modeFamily) {
    const narrowed = candidates.filter((family) => family.id === modeFamily);
    if (narrowed.length > 0) { candidates = narrowed; }
  }

  return allowed(candidates.flatMap((family) => family.index_types));
}

/** Default index type to preselect: the Lite default on Lite, otherwise the metadata default when offered. */
export function getMilvusDefaultIndexType(
  options: string[],
  metadataDefault: string | undefined,
  authType: string | undefined,
  applicability?: VectorDBApplicability
): string {
  if (authType === 'lite') {
    return (applicability?.lite ?? FALLBACK_MILVUS_LITE).default;
  }
  if (metadataDefault && options.includes(metadataDefault)) { return metadataDefault; }
  return options[0] ?? '';
}

/** Input for {@link getMilvusMetricOptions}. */
export interface MilvusMetricContext {
  applicability?: VectorDBApplicability;
  /** Index type selected in the form; undefined before a selection exists (existing resources). */
  indexType?: string;
  /** Saved provider config, used for GPU mode when no index type is selected. */
  providerConfig: Record<string, unknown>;
  featureTypes: string[];
  sparseEnabled: boolean;
  /** Full metric list from `valid_values`; options outside it are dropped. */
  validValues: string[];
}

/**
 * Similarity metrics the user may select for a Milvus collection.
 *
 * Derived from the index family selected in the form, not from saved config. Before a form
 * selection exists, GPU mode is read from `providerConfig`. `BM25` is offered only when sparse
 * is on and no dense field is indexed with the configured metric.
 */
export function getMilvusMetricOptions(context: MilvusMetricContext): string[] {
  const { applicability, indexType, providerConfig, featureTypes, sparseEnabled, validValues } = context;
  const families = applicability?.index_families ?? FALLBACK_MILVUS_FAMILIES;
  const familyOf = (id: string): IndexFamily | undefined => families.find((family) => family.id === id);
  const keep = (values: string[]): string[] => values.filter((value) => validValues.includes(value));

  const hasBinary = featureTypes.includes(VECTOR_FEATURE_TYPES.BINARY);
  const hasDense = featureTypes.includes(VECTOR_FEATURE_TYPES.DENSE);
  const selectedFamily = indexType ? getMilvusFamily(indexType, applicability) : undefined;

  // Binary-only collections: binary metrics, plus BM25 when sparse is on (no dense field uses the metric).
  if (hasBinary && !hasDense) {
    const binary = familyOf('binary')?.metric_types ?? [];
    return keep(sparseEnabled ? [...binary, SPARSE_METRIC] : binary);
  }

  // Dense metrics follow the selected family; GPU mode from saved config applies before any selection.
  const family = selectedFamily ?? (isMilvusGpuMode(providerConfig) ? familyOf('gpu') : undefined);
  if (family) {
    // A binary family selected without a binary feature still resolves to its own metrics.
    return keep(family.metric_types);
  }

  // Mixed dense and binary features keep the full list (the configured metric applies to whichever
  // field it fits); only BM25 is dropped because a dense field is present.
  if (hasDense && hasBinary) {
    return validValues.filter((value) => value !== SPARSE_METRIC);
  }
  if (hasDense) {
    return keep(familyOf('cpu_dense')?.metric_types ?? []);
  }
  return validValues;
}

/** Algorithms the user may select for an OpenSearch engine; falls back to `validValues` when unmapped. */
export function getOpenSearchAlgorithmOptions(
  engine: string,
  applicability: VectorDBApplicability | undefined,
  validValues: string[]
): string[] {
  const supported = applicability?.engine_algorithms?.[engine];
  if (!supported) { return validValues; }
  return supported.filter((algorithm) => validValues.includes(algorithm));
}
