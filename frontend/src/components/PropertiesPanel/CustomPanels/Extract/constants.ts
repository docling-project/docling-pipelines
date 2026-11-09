/**
 * Attribute key names for the `extract_operator` operator.
 *
 * These must exactly match the backend config keys consumed by
 * `ExtractOperator.get_metadata()["attributes"]`.
 * Used as the `name` argument to controller.getPropertyValue()` /
 * `controller.updatePropertyValue()` throughout the panel.
 */

/**
 * Top-level property keys written into `node.parameters` by the panel.
 *
 * Keys must match the top-level keys in Extract operator metadata attributes:
 *   - `text_extraction`  → nested object  { provider, provider_config, doc_column }
 *   - `entity_extraction` → nested object { provider, provider_config, output_column, … }
 *   - `max_workers`      → number
 *   - `use_processes`    → boolean
 */
export const EXTRACT_ATTRIBUTE = {
  TEXT_EXTRACTION: 'text_extraction',
  ENTITY_EXTRACTION: 'entity_extraction',
  MAX_WORKERS: 'max_workers',
  USE_PROCESSES: 'use_processes',
} as const;

/**
 * Union type of all valid `extract_operator` attribute key strings.
 */
export type ExtractAttributeKey = typeof EXTRACT_ATTRIBUTE[keyof typeof EXTRACT_ATTRIBUTE];

/**
 * Sub-field keys shared by both text_extraction and entity_extraction objects.
 * These are nested inside the top-level extraction objects, not top-level property names.
 */
export const EXTRACTION_KEY = {
  PROVIDER: 'provider',
  PROVIDER_CONFIG: 'provider_config',
  DOC_COLUMN: 'doc_column',
  OUTPUT_COLUMN: 'output_column',
  ENTITY_MAX_DOC_CHARS: 'entity_max_doc_chars',
  EXPAND_EXTRACTED_DATA: 'expand_extracted_data',
  CUSTOM_SCHEMA: 'custom_schema',
} as const;

// ── Valid values ─────────────────────────────────────────────────────────────

export const TEXT_PROVIDERS = ['docling_library', 'docling_serve'] as const;
export type TextProvider = typeof TEXT_PROVIDERS[number];

// ── docling_library provider_config field keys ────────────────────────────────
export const DOCLING_LIBRARY_CONFIG_KEY = {
  VLM_PIPELINE: 'vlm_pipeline',
  ASR_PIPELINE: 'asr_pipeline',
  ADDITIONAL_FORMATS: 'additional_formats',
  STANDARD_PIPELINE: 'standard_pipeline',
} as const;

/** Sub-keys for vlm_pipeline nested object. */
export const VLM_PIPELINE_KEY = {
  PRESET: 'preset',
  ENGINE: 'engine',
  ENGINE_OPTIONS: 'engine_options',
} as const;

/** Sub-keys for asr_pipeline nested object. */
export const ASR_PIPELINE_KEY = {
  MODEL_ID: 'model_id',
} as const;

/** Sub-keys for standard_pipeline.accelerator nested object. */
export const ACCELERATOR_KEY = {
  DEVICE: 'device',
  NUM_THREADS: 'num_threads',
} as const;

/** Valid VLM engine values from the operator metadata. */
export const VLM_ENGINES = [
  'transformers',
  'mlx',
  'api',
  'api_ollama',
  'api_openai',
  'api_watsonx',
  'api_lmstudio',
] as const;
export type VlmEngine = typeof VLM_ENGINES[number];

/** Valid additional_formats values from the operator metadata. */
export const ADDITIONAL_FORMATS = ['html', 'json', 'text', 'doctags', 'doclang'] as const;
export type AdditionalFormat = typeof ADDITIONAL_FORMATS[number];

// ── docling_serve provider_config field keys ──────────────────────────────────
export const DOCLING_SERVE_CONFIG_KEY = {
  BASE_URL: 'base_url',
  API_KEY: 'api_key', // pragma: allowlist secret
  TIMEOUT: 'timeout',
  POLL_INTERVAL: 'poll_interval',
  MAX_RETRIES: 'max_retries',
  VERIFY_SSL: 'verify_ssl',
  DO_OCR: 'do_ocr',
  PDF_BACKEND: 'pdf_backend',
  OCR_ENGINE: 'ocr_engine',
  OCR_LANGUAGES: 'ocr_languages',
  TABLE_MODE: 'table_mode',
  IMAGE_EXPORT_MODE: 'image_export_mode',
} as const;

/** Valid pdf_backend values from the operator metadata. */
export const PDF_BACKENDS = ['dlparse_v2', 'pypdfium2'] as const;
export type PdfBackend = typeof PDF_BACKENDS[number];

/** Valid image_export_mode values from the operator metadata. */
export const IMAGE_EXPORT_MODES = ['placeholder', 'embedded'] as const;
export type ImageExportMode = typeof IMAGE_EXPORT_MODES[number];

export const ENTITY_PROVIDERS = ['none', 'litellm', 'watsonx', 'docling'] as const;
export type EntityProvider = typeof ENTITY_PROVIDERS[number];

// ── Entity provider_config field keys ─────────────────────────────────────────

/** Shared keys used by litellm and watsonx provider_config. */
export const LLM_ENTITY_CONFIG_KEY = {
  MODEL_ID: 'model_id',
  API_BASE: 'api_base',
  API_KEY: 'api_key', // pragma: allowlist secret
  TEMPERATURE: 'temperature',
  MAX_TOKENS: 'max_tokens',
} as const;

/** Additional keys for the watsonx provider_config. */
export const WATSONX_ENTITY_CONFIG_KEY = {
  URL: 'url',
  CONTAINER_KIND: 'container_kind',
  CONTAINER_ID: 'container_id',
  PROJECT_ID: 'project_id',
} as const;

/** Valid container_kind values for watsonx. */
export const WATSONX_CONTAINER_KINDS = ['project', 'space'] as const;
export type WatsonxContainerKind = typeof WATSONX_CONTAINER_KINDS[number];

/** Key for the docling entity provider_config. */
export const DOCLING_ENTITY_CONFIG_KEY = {
  VLM_PIPELINE: 'vlm_pipeline',
} as const;
