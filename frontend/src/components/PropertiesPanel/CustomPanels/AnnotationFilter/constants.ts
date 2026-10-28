/**
 * @file constants.ts
 *
 * All constants for the `sql_filter` (Annotation Filter) operator panel.
 *
 * - `ANNOTATION_FILTER_ATTRIBUTE` — Elyra parameter / attribute key names
 * - `ADVANCED_EXPRESSION_ROW_ID` — sentinel ID for the advanced-mode table row
 *
 * User-facing strings live in the sibling `*.messages.ts` files.
 *
 * Import from here instead of defining strings inline in component files.
 */

// ---------------------------------------------------------------------------
// Attribute keys — Elyra parameter names
// ---------------------------------------------------------------------------

/**
 * Elyra property names for the `sql_filter` operator's parameters.
 *
 * Values must exactly match the `id` fields in `sql_filter_paramDef.json`
 * and the attribute keys returned by `SQLFilterOperator.get_metadata()`.
 * Used as the `name` argument to `controller.getPropertyValue()` /
 * `controller.updatePropertyValue()` throughout the panel.
 */
export const ANNOTATION_FILTER_ATTRIBUTE = {
  /**
   * Structured condition object written in Simple mode.
   * Shape: `{ logical_operator: "AND"|"OR", criteria_list: Condition[] }`
   */
  CRITERIA_JSON: 'criteria_json',
  /**
   * Single-element string array written in Advanced mode.
   * Shape: `["raw SQL expression"]`
   */
  CRITERIA_LIST: 'criteria_list',
} as const;

/**
 * Union type of all valid `sql_filter` attribute key strings.
 * Derived from {@link ANNOTATION_FILTER_ATTRIBUTE} so it stays in sync automatically.
 */
export type AnnotationFilterAttributeKey =
  typeof ANNOTATION_FILTER_ATTRIBUTE[keyof typeof ANNOTATION_FILTER_ATTRIBUTE];

// ---------------------------------------------------------------------------
// Sentinel values
// ---------------------------------------------------------------------------

/**
 * Stable row ID used for the single Advanced-mode row in the criteria table.
 *
 * When `criteria_list` holds a raw SQL string, one synthetic row is created
 * with this ID. `handleDeleteCondition` checks for it to decide whether to
 * clear `criteria_list` (advanced) or filter `criteria_json.criteria_list`
 * (simple).
 */
export const ADVANCED_EXPRESSION_ROW_ID = 'advanced-expression' as const;
