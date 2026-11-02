/**
 * Copyright IBM Corp. 2024, 2026
 * Constants for the BottomNotificationPanel and TopNotificationBar components.
 */

// Table column keys
export const COLUMN_KEYS = {
  EXPAND: 'expand',
  NUMBER: 'number',
  TIMESTAMP: 'timestamp',
  STATUS: 'status',
  NAME: 'name',
  DESCRIPTION: 'description',
} as const;

// Notification types
export const NOTIFICATION_TYPES = {
  ERROR: 'error',
  WARNING: 'warning',
} as const;

// Default values
export const DEFAULT_VALUES = {
  NODE_NAME_PLACEHOLDER: '-',
} as const;

// Keys used for client-side search in the notification table
export const SEARCH_KEYS = ['description', 'name', 'timestamp'] as const;

// Validation response status strings returned by the backend (lowercase for comparison)
export const VALIDATION_STATUS = {
  SUCCEEDED: 'succeeded',
  FAILED: 'failed',
  SUCCEEDED_WITH_WARNINGS: 'succeeded_with_warnings',
} as const;

// message_code values that should highlight a node rather than open its properties panel.
// Matches VALIDATION_MESSAGE_CODES_FOR_HIGHLIGHT from the original spec.
export const HIGHLIGHT_MESSAGE_CODES = new Set([
  'DISJOINT_OPERATORS_DETECTED',
  'CHUNKER_OPERATOR_MISPLACED',
  'EXTRACT_OPERATOR_MISSING',
  'CHUNKER_OPERATOR_MISSING',
  'GENERATE_OUTPUT_MISSING',
  'INGEST_OPERATOR_MISPLACED',
  'DAG_PIPELINE_MISSING',
  'OPERATOR_NAME_REPEATED',
  'PIPELINE_NOT_FOUND_ERROR',
  'MISSING_NODE_ID',
  'MISSING_NODE_NAME',
  'GET_OPERATOR_FAILED',
  'MULTIPLE_EXTRACTED_DETECTED',
]);
