/**
 * Attribute key names for the `embeddings` operator.
 *
 * These must exactly match the backend config keys consumed by
 * `EmbeddingsOperator.get_metadata()["attributes"]`.
 */
export const EMBEDDINGS_ATTRIBUTE = {
  /** Embedding provider identifier — "litellm" or "watsonx" */
  PROVIDER: 'provider',
  /** Provider-specific configuration object */
  PROVIDER_CONFIG: 'provider_config',
  /** Provider config key for the selected model id */
  PROVIDER_CONFIG_MODEL_ID: 'model_id',
  /** Provider config key for the API base URL */
  PROVIDER_CONFIG_API_BASE: 'api_base',
  /** Provider config key for the API credential */
  PROVIDER_CONFIG_API_KEY: 'api_key', // pragma: allowlist secret
  /** Watsonx provider config key for the endpoint URL */
  PROVIDER_CONFIG_URL: 'url',
  /** Watsonx provider config key for the container type */
  PROVIDER_CONFIG_CONTAINER_KIND: 'container_kind',
  /** Watsonx provider config key for the container ID */
  PROVIDER_CONFIG_CONTAINER_ID: 'container_id',
  /** Overlap ratio for long-text chunking */
  OVERLAP_RATIO: 'overlap_ratio',
  /** Maximum token limit for chunking */
  TOKEN_LIMIT: 'token_limit',
} as const;

/**
 * Union type of all valid `embeddings` attribute key strings.
 */
export type EmbeddingsAttributeKey = typeof EMBEDDINGS_ATTRIBUTE[keyof typeof EMBEDDINGS_ATTRIBUTE];

/**
 * Canonical provider identifiers supported by the Embeddings operator UI.
 */
export const EMBEDDINGS_PROVIDER = {
  LITELLM: 'litellm',
  WATSONX: 'watsonx',
} as const;

/**
 * Ordered provider list used by the provider dropdown.
 */
export const EMBEDDINGS_PROVIDERS = [
  EMBEDDINGS_PROVIDER.LITELLM,
  EMBEDDINGS_PROVIDER.WATSONX,
] as const;
/**
 * Union type of all supported Embeddings provider identifiers.
 */
export type EmbeddingsProvider = typeof EMBEDDINGS_PROVIDERS[number];

/**
 * Maps provider identifiers to their display names. These are brand names and
 * are intentionally not translated.
 */
export const EMBEDDINGS_PROVIDER_LABELS: Record<EmbeddingsProvider, string> = {
  [EMBEDDINGS_PROVIDER.LITELLM]: 'LiteLLM',
  [EMBEDDINGS_PROVIDER.WATSONX]: 'watsonx',
};

/**
 * Default values used by the Embeddings properties panel when a node has not
 * yet persisted explicit configuration values.
 */
export const EMBEDDINGS_DEFAULTS = {
  PROVIDER: 'litellm' as EmbeddingsProvider,
  PROVIDER_CONFIG: '',
  OVERLAP_RATIO: 0.2,
  TOKEN_LIMIT: 8192,
} as const;

/**
 * Valid `container_kind` values for the watsonx provider.
 */
export const WATSONX_CONTAINER_KINDS = ['project', 'space'] as const;
export type WatsonxContainerKind = typeof WATSONX_CONTAINER_KINDS[number];
