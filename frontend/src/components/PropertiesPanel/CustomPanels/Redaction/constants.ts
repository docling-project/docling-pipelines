/**
 * Attribute key names for the `redaction` operator.
 *
 * These must exactly match the backend attribute keys returned by
 * `RedactionOperator.get_metadata()["attributes"]`.
 * Used as the `name` argument to `controller.getPropertyValue()` /
 * `controller.updatePropertyValue()` throughout the panel.
 */
export const REDACTION_ATTRIBUTE = {
  /** Regex pattern or plain word to match and redact */
  REDACTION_REGEX: 'redaction_regex',
  /** Single character used to replace each matched character */
  REDACTION_MASKING_CHARACTER: 'redaction_masking_character',
} as const;

/**
 * Union type of all valid `redaction` attribute key strings.
 */
export type RedactionAttributeKey =
  typeof REDACTION_ATTRIBUTE[keyof typeof REDACTION_ATTRIBUTE];
