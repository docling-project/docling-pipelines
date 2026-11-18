/**
 * Attribute key names for the `ml_enrichment` operator.
 *
 * These must exactly match the backend attribute keys returned by
 * `MLEnrichmentOperator.get_metadata()["attributes"]`.
 * Used as the `name` argument to `controller.getPropertyValue()` /
 * `controller.updatePropertyValue()` throughout the panel.
 */
export const ML_ENRICHMENT_ATTRIBUTE = {
  /** Name of the column containing document text */
  DOC_COLUMN: 'doc_column',
  /** Name of the column containing the language identifier */
  LANG_COLUMN: 'lang_column',
  /** Prefix to prepend to all output feature column names */
  OUTPUT_COLUMN_PREFIX: 'output_column_prefix',
} as const;

/**
 * Union type of all valid `ml_enrichment` attribute key strings.
 */
export type MlEnrichmentAttributeKey =
  typeof ML_ENRICHMENT_ATTRIBUTE[keyof typeof ML_ENRICHMENT_ATTRIBUTE];
