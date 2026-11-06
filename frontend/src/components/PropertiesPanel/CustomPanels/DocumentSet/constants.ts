/**
 * Attribute key names for the `document_set` operator.
 *
 * These must exactly match the backend attribute keys returned by
 * `DocumentSetOperator.get_metadata()["attributes"]`.
 * Used as the `name` argument to `controller.getPropertyValue()` /
 * `controller.updatePropertyValue()` throughout the panel.
 */
export const DOCUMENT_SET_ATTRIBUTE = {
  /** Name of the document set to create or update (required) */
  DOCUMENT_SET_NAME: 'document_set_name',
  /** Human-readable description of the document set */
  DESCRIPTION: 'description',
  /** Arbitrary JSON object stored as document set metadata */
  METADATA: 'metadata',
  /** UUID of an existing document set to update instead of creating a new one */
  DOCUMENT_SET_ID: 'document_set_id',
  /** File path for the DuckDB database */
  DATABASE_PATH: 'database_path',
  /** Data store backend for PyArrow table data */
  DATA_BACKEND: 'data_backend',
} as const;

/**
 * Union type of all valid `document_set` attribute key strings.
 */
export type DocumentSetAttributeKey =
  typeof DOCUMENT_SET_ATTRIBUTE[keyof typeof DOCUMENT_SET_ATTRIBUTE];
