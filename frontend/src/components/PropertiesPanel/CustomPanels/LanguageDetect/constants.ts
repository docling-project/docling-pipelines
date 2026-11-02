/** Attribute key names — must match operator metadata keys exactly. */
export const LANGUAGE_DETECT_ATTR = {
  LANGUAGE_PROVIDER: 'language_provider',
  FILTER_UNKNOWN_LANGUAGE: 'filter_unknown_language',
} as const;

export const LANGUAGE_DETECT_PROVIDER_ITEMS = ['fasttext', 'langdetect'];
