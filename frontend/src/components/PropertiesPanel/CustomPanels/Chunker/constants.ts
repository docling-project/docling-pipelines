/**
 * Attribute key names for the `chunker` operator.
 *
 * These must exactly match the backend config keys consumed by
 * `ChunkerOperator.get_metadata()["attributes"]`.
 * Used as the `name` argument to `controller.getPropertyValue()` /
 * `controller.updatePropertyValue()` throughout the panel.
 */
export const CHUNKER_ATTRIBUTE = {
  /** Chunking strategy */
  CHUNK_TYPE: 'chunk_type',
  /** Chunk size in characters (simple) or tokens (hybrid) */
  CHUNK_SIZE: 'chunk_size',
  /** Overlap between consecutive chunks */
  CHUNK_OVERLAP: 'chunk_overlap',
  /** Overlap expressed as a percentage of chunk_size */
  CHUNK_OVERLAP_PERCENTAGE: 'chunk_overlap_percentage',
  /** Ollama model name for semantic chunking embeddings */
  SEMANTIC_EMBEDDINGS_MODEL: 'semantic_embeddings_model',
  /** Boundary detection method for semantic chunking */
  BREAKPOINT_THRESHOLD_TYPE: 'breakpoint_threshold_type',
  /** Threshold value for the selected breakpoint detection method */
  BREAKPOINT_THRESHOLD_AMOUNT: 'breakpoint_threshold_amount',
  /** HuggingFace tokenizer for hybrid chunking */
  DOCLING_TOKENIZER: 'docling_tokenizer',
  /** Whether to keep the original content column after chunking */
  RETAIN_ORIGINAL_CONTENT: 'retain_original_content',
  /** Summarization configuration */
  SUMMARIZATION: 'summarization',
  /** Set to 'docling_serve' to route chunking to a remote Docling Serve API */
  PROVIDER: 'provider',
  /** Provider-specific configuration */
  PROVIDER_CONFIG: 'provider_config',
} as const;

// ── Chunk types ───────────────────────────────────────────────────────────────

export const CHUNK_TYPES = ['simple', 'semantic', 'hybrid'] as const;
export type ChunkType = typeof CHUNK_TYPES[number];

// ── Breakpoint threshold types ────────────────────────────────────────────────

export const BREAKPOINT_THRESHOLD_TYPES = [
  'percentile',
  'standard_deviation',
  'interquartile',
  'gradient',
] as const;
export type BreakpointThresholdType = typeof BREAKPOINT_THRESHOLD_TYPES[number];

// ── Defaults ──────────────────────────────────────────────────────────────────

export const CHUNKER_DEFAULTS = {
  CHUNK_TYPE: 'simple' as ChunkType,
  CHUNK_SIZE: 1000,
  CHUNK_OVERLAP: 200,
  CHUNK_OVERLAP_PERCENTAGE: 20,
  BREAKPOINT_THRESHOLD_TYPE: 'percentile' as BreakpointThresholdType,
  DOCLING_TOKENIZER: 'sentence-transformers/all-MiniLM-L6-v2',
  RETAIN_ORIGINAL_CONTENT: false,
} as const;
