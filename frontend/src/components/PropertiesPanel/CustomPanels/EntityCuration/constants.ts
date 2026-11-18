/**
 * Attribute key names for the `entity_curation` operator.
 *
 * These must exactly match the backend attribute keys returned by
 * `EntityCurationOperator.get_metadata()["attributes"]`.
 * Used as the `name` argument to `controller.getPropertyValue()` /
 * `controller.updatePropertyValue()` throughout the panel.
 */
export const ENTITY_CURATION_ATTRIBUTE = {
  /** Name of the input column containing extracted entities (dict) */
  ENTITIES_COLUMN: 'entities_column',
  /** Name of the input column containing the document type identifier */
  DOCUMENT_TYPE_COLUMN: 'document_type_column',
} as const;

/**
 * Union type of all valid `entity_curation` attribute key strings.
 */
export type EntityCurationAttributeKey =
  typeof ENTITY_CURATION_ATTRIBUTE[keyof typeof ENTITY_CURATION_ATTRIBUTE];
