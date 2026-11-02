/**
 * Attribute key names for the `document_classifier` operator.
 *
 * These must exactly match the backend attribute keys returned by
 * `DocumentClassifierOperator.get_metadata()["attributes"]`.
 * Used as the `name` argument to `controller.getPropertyValue()` /
 * `controller.updatePropertyValue()` throughout the panel.
 */
export const DOCUMENT_CLASSIFIER_ATTRIBUTE = {
  /** LLM provider identifier — `"litellm"` or `"watsonx"` */
  PROVIDER: 'provider',
  /** Provider-specific configuration JSON (model, api_base, api_key, …) */
  PROVIDER_CONFIG: 'provider_config',
  /** Comma-separated list of document type names to classify into */
  DOCUMENT_TYPES: 'document_types',
  /** Minimum confidence score (1–10) required to accept a classification */
  CONFIDENCE_THRESHOLD: 'confidence_threshold',
  /** Name of the output PyArrow column that receives the classified type */
  OUTPUT_COLUMN: 'output_column',
  /** Whether to write the confidence score to a companion column */
  INCLUDE_CONFIDENCE: 'include_confidence',
  /** Whether to write the LLM reasoning to a companion column */
  INCLUDE_REASONING: 'include_reasoning',
  /** Name of the input column containing the document text to classify */
  DOC_COLUMN: 'doc_column',
} as const;

/**
 * Union type of all valid `document_classifier` attribute key strings.
 * Derived from {@link DOCUMENT_CLASSIFIER_ATTRIBUTE} so it stays in sync automatically.
 */
export type DocumentClassifierAttributeKey =
  typeof DOCUMENT_CLASSIFIER_ATTRIBUTE[keyof typeof DOCUMENT_CLASSIFIER_ATTRIBUTE];
