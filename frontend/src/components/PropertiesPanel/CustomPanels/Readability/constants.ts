/**
 * Attribute key names for the `readability` operator.
 *
 * These must exactly match the backend attribute keys returned by
 * `ReadabilityOperator.get_metadata()["attributes"]`.
 * Used as the `name` argument to `controller.getPropertyValue()` /
 * `controller.updatePropertyValue()` throughout the panel.
 */
export const READABILITY_ATTRIBUTE = {
  /** List of readability score names to compute */
  SCORE_LIST: 'readability_score_list',
} as const;

/**
 * Union type of all valid `readability` attribute key strings.
 */
export type ReadabilityAttributeKey =
  typeof READABILITY_ATTRIBUTE[keyof typeof READABILITY_ATTRIBUTE];

/**
 * All valid readability score identifiers.
 * These match the live operator metadata `attributes.readability_score_list.default`
 * and are used as the static fallback when metadata is not yet loaded.
 */
export const READABILITY_SCORE_OPTIONS = [
  'flesch_ease_textstat',
  'flesch_kincaid_textstat',
  'gunning_fog_textstat',
  'smog_index_textstat',
  'coleman_liau_index_textstat',
  'automated_readability_index_textstat',
  'dale_chall_readability_score_textstat',
  'difficult_words_textstat',
  'linsear_write_formula_textstat',
  'text_standard_textstat',
  'spache_readability_textstat',
  'mcalpine_eflaw_textstat',
  'reading_time_textstat',
] as const;

/**
 * Maps score identifiers to their display names. These are named readability
 * tests and are intentionally not translated.
 */
export const READABILITY_SCORE_LABELS: Record<string, string> = {
  flesch_ease_textstat: 'Flesch Reading Ease',
  flesch_kincaid_textstat: 'Flesch Kincaid Grade',
  gunning_fog_textstat: 'Gunning Fog',
  smog_index_textstat: 'SMOG Index',
  coleman_liau_index_textstat: 'Coleman Liau Index',
  automated_readability_index_textstat: 'Automated Readability Index',
  dale_chall_readability_score_textstat: 'Dale Chall Readability Score',
  difficult_words_textstat: 'Difficult Words',
  linsear_write_formula_textstat: 'Linsear Write Formula',
  text_standard_textstat: 'Text Standard',
  spache_readability_textstat: 'Spache Readability',
  mcalpine_eflaw_textstat: 'McAlpine EFLAW',
  reading_time_textstat: 'Reading Time',
};
