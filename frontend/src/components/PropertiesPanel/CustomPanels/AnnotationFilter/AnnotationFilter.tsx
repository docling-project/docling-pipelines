/**
 * @file AnnotationFilter.tsx
 *
 * Configuration panel body for the `sql_filter` operator node.
 *
 * The operator accepts SQL-style filter criteria applied to document annotation
 * features (PII scores, language scores, quality scores, etc.).
 *
 * **Parameter storage duality**
 *
 * | Mode     | Written to            | Cleared               |
 * |----------|-----------------------|-----------------------|
 * | Simple   | `criteria_json`       | `criteria_list = null`|
 * | Advanced | `criteria_list`       | `criteria_json = null`|
 *
 * `criteria_json` shape: `{ logical_operator: "AND"|"OR", criteria_list: Condition[] }`
 * `criteria_list` shape: `["raw SQL expression string"]` (single-element array)
 *
 * **Data flow**
 * 1. Input features come from `appData.nodeFeatureMap[nodeId].input_features` —
 *    fetched by `Canvas.tsx` and injected via the Elyra controller's `appData`.
 * 2. Saved values are read via `controller.getPropertyValue({ name })`.
 * 3. Changes are written via `controller.updatePropertyValue({ name }, value)`;
 *    Elyra persists the full property set when the user clicks Save.
 *
 * **Sub-components** (each in their own file for reuse by other operators):
 * - {@link ConditionBuilderTearsheet} — tabbed Simple/Advanced builder
 * - {@link CriteriaFullViewTearsheet} — full-screen expand view
 *
 * **Shared utilities** (see `conditionTypes.ts`):
 * - {@link Condition}, {@link CriteriaJson} — domain types
 * - {@link LOGICAL}, {@link SQL_OPERATORS} — constants
 * - {@link generateConditionId}, {@link conditionToText} — pure helpers
 *
 * @module AnnotationFilter
 */

import React, { useCallback, useMemo, useState } from 'react';
import { useIntl } from 'react-intl';
import { Button, DefinitionTooltip, FormLabel } from '@carbon/react';
import { Add, Maximize, TrashCan } from '@carbon/icons-react';
import { NodeOperator } from '@/constants/operators';
import { SharedDataTable } from '@/components/common/SharedDataTable';
import type { SharedDataTableHeader, SharedDataTableRow } from '@/components/common/SharedDataTable';
import type { ElyraController, FeatureAttributes, OperatorFeature } from '@/types';
import {
  type Condition,
  type CriteriaJson,
  LOGICAL,
  conditionToText,
  FEATURE_TYPES,
  generateConditionId,
} from './conditionTypes';
import {
  convertFromEpoch,
  convertToEpoch,
  isEpochValue,
} from '@/utils/dateTimeUtils';
import { ConditionBuilderTearsheet } from './ConditionBuilderTearsheet';
import {
  CriteriaFullViewTearsheet,
  type CriteriaDisplayRow,
} from './CriteriaFullViewTearsheet';
import {
  ADVANCED_EXPRESSION_ROW_ID,
  ANNOTATION_FILTER_ATTRIBUTE,
} from './constants';
import { messages } from './AnnotationFilter.messages';
import styles from './AnnotationFilter.module.scss';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

/**
 * Props for {@link AnnotationFilterPanelBody}.
 *
 * `controller` is the Elyra `CommonProperties` controller instance injected
 * by `CommonPropertiesPanelWrapper`. Typed via {@link ElyraController}.
 *
 * Relevant methods used in this panel:
 * - `controller.getAppData()` — returns `{ operatorMetadata, nodeId, nodeFeatureMap, … }`
 * - `controller.getPropertyValue({ name })` — reads a saved node parameter
 * - `controller.updatePropertyValue({ name }, value)` — writes a node parameter
 */
interface AnnotationFilterPanelBodyProps {
  controller: ElyraController;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Configuration panel body for the `sql_filter` operator node.
 *
 * Rendered by `CommonPropertiesPanel` when the selected canvas node has
 * `op === "sql_filter"`. Registered in `OPERATOR_PANEL_MAP` inside
 * `CommonPropertiesPanel.tsx`.
 *
 * **Tearsheets mounted conditionally**
 * - {@link ConditionBuilderTearsheet} — opened by Add/Update Criteria button
 * - {@link CriteriaFullViewTearsheet} — opened by the Maximize icon in the toolbar
 *
 * @param props - {@link AnnotationFilterPanelBodyProps}
 */
export function AnnotationFilterPanelBody({
  controller,
}: AnnotationFilterPanelBodyProps): React.JSX.Element {
  const intl = useIntl();
  const [isConditionBuilderOpen, setIsConditionBuilderOpen] = useState(false);
  const [isFullViewOpen, setIsFullViewOpen] = useState(false);

  // ── Read node context from Elyra controller ──────────────────────────

  // Cast once to a typed internal shape — ElyraController.getAppData() returns
  // Record<string, unknown>; this single cast avoids repeated unsafe-member-access
  // suppressions throughout the component.

  const appData = (controller.getAppData() as {
    nodeId?: string;
    featuresLoading?: boolean;
    nodeFeatureMap?: Record<string, { input_features?: Record<string, FeatureAttributes> }>;
    operatorMetadata?: Record<string, { attributes?: Record<string, OperatorFeature> }>;
  });

  const currentNodeId: string = appData.nodeId ?? '';
  const nodeFeatureMap = appData.nodeFeatureMap ?? {};

  /** Input features flowing into this node from upstream operators. */
  const inputFeatures: Record<string, FeatureAttributes> =
    nodeFeatureMap[currentNodeId]?.input_features ?? {};

  // ── Read operator attribute metadata ─────────────────────────────────
  const nodeAttributes: Record<string, OperatorFeature> =
    appData.operatorMetadata?.[NodeOperator.SQL_FILTER]?.attributes ?? {};

  // ── Read saved parameters ─────────────────────────────────────────────

  const elyraCriteriaJson =
    (controller.getPropertyValue({ name: ANNOTATION_FILTER_ATTRIBUTE.CRITERIA_JSON }) as CriteriaJson | null | undefined) ?? null;

  const elyraCriteriaList =
    (controller.getPropertyValue({ name: ANNOTATION_FILTER_ATTRIBUTE.CRITERIA_LIST }) as string[] | null | undefined) ?? [];

  /** Feature name strings — used for the available features table. */
  const featureNames = Object.keys(inputFeatures);

  // ── Derived display rows ──────────────────────────────────────────────
  /**
   * Unified row list for the criteria table.
   *
   * Precedence:
   * 1. `criteria_list` is a non-empty string array → Advanced mode (one row).
   * 2. `criteria_json.criteria_list` is non-empty → Simple mode (one row per condition).
   * 3. Otherwise → empty array (no criteria saved yet).
   */
  const criteriaRows = useMemo((): CriteriaDisplayRow[] => {
    if (elyraCriteriaList.length > 0 && typeof elyraCriteriaList[0] === 'string') {
      return [{
        id: ADVANCED_EXPRESSION_ROW_ID,
        condition: elyraCriteriaList[0],
        isAdvanced: true,
      }];
    }

    if (!elyraCriteriaJson?.criteria_list?.length) {
      return [];
    }

    return elyraCriteriaJson.criteria_list.map((c) => {
      // For datetime fields stored as epoch, convert back to human-readable for display
      const featureType = inputFeatures[c.variable]?.type ?? '';
      const isDatetime = featureType === FEATURE_TYPES.DATETIME;
      const displayValue =
        isDatetime && isEpochValue(c.value) ? convertFromEpoch(c.value) : c.value;
      return {
        id: c.id,
        condition: conditionToText({ ...c, value: displayValue }),
        isAdvanced: false,
      };
    });
  }, [elyraCriteriaJson, elyraCriteriaList]);

  // ── Initial state for the builder tearsheet ──────────────────────────
  /**
   * Simple-mode conditions to pre-populate when the builder opens.
   * Returns an empty array when Advanced mode is active.
   */
  const initialConditions = useMemo((): Condition[] => {
    if (elyraCriteriaList.length > 0 && typeof elyraCriteriaList[0] === 'string') {
      return [];
    }
    // Convert epoch → human-readable for datetime fields before pre-populating builder
    return (elyraCriteriaJson?.criteria_list ?? []).map((c) => {
      const featureType = inputFeatures[c.variable]?.type ?? '';
      if (featureType === FEATURE_TYPES.DATETIME && isEpochValue(c.value)) {
        return { ...c, value: convertFromEpoch(c.value) };
      }
      return c;
    });
  }, [elyraCriteriaJson, elyraCriteriaList]);

  /**
   * Advanced-mode expression to pre-populate when the builder opens.
   * Returns an empty string when Simple mode is active.
   */
  const initialAdvancedExpression = useMemo((): string => {
    if (elyraCriteriaList.length > 0 && typeof elyraCriteriaList[0] === 'string') {
      return elyraCriteriaList[0];
    }
    return '';
  }, [elyraCriteriaList]);

  // ── Handlers ─────────────────────────────────────────────────────────

  /**
   * Persists the criteria from the builder tearsheet back into Elyra's
   * property store, enforcing the Simple/Advanced mutual-exclusion rule:
   *
   * - Advanced: writes `criteria_list`, clears `criteria_json`.
   * - Simple: writes `criteria_json`, clears `criteria_list`.
   *
   * @param conditions - Condition rows from the Simple tab.
   * @param logicalOperator - `"AND"` or `"OR"` from the Simple tab.
   * @param advancedExpression - Raw SQL string from the Advanced tab.
   */
  const handleSaveConditions = (
    conditions: Condition[],
    logicalOperator: string,
    advancedExpression: string
  ): void => {
    if (advancedExpression.trim()) {

      controller.updatePropertyValue({ name: ANNOTATION_FILTER_ATTRIBUTE.CRITERIA_LIST }, [advancedExpression.trim()]);

      controller.updatePropertyValue({ name: ANNOTATION_FILTER_ATTRIBUTE.CRITERIA_JSON }, null);
    } else {
      const conditionsWithIds = conditions.map((c) => {
        // Ensure every condition has a stable ID
        const withId = c.id ? c : { ...c, id: generateConditionId() };
        // For datetime fields, convert human-readable → epoch before persisting
        const featureType = inputFeatures[withId.variable]?.type ?? '';
        if (featureType === FEATURE_TYPES.DATETIME && !isEpochValue(withId.value) && withId.value) {
          return { ...withId, value: String(convertToEpoch(withId.value)) };
        }
        return withId;
      });

      controller.updatePropertyValue({ name: ANNOTATION_FILTER_ATTRIBUTE.CRITERIA_JSON }, {
        logical_operator: logicalOperator || LOGICAL.AND,
        criteria_list: conditionsWithIds,
      });

      controller.updatePropertyValue({ name: ANNOTATION_FILTER_ATTRIBUTE.CRITERIA_LIST }, null);
    }
    setIsConditionBuilderOpen(false);
  };

  /**
   * Removes a single condition from the saved criteria.
   *
   * - `"advanced-expression"` → clears the `criteria_list` parameter.
   * - Any other ID → filters the matching entry out of `criteria_json.criteria_list`.
   *
   * @param conditionId - The {@link Condition.id} to remove, or `"advanced-expression"`.
   */
  const handleDeleteCondition = useCallback((conditionId: string): void => {
    if (conditionId === ADVANCED_EXPRESSION_ROW_ID) {

      controller.updatePropertyValue({ name: ANNOTATION_FILTER_ATTRIBUTE.CRITERIA_LIST }, []);
      return;
    }
    if (elyraCriteriaJson) {
      const updated = elyraCriteriaJson.criteria_list.filter((c) => c.id !== conditionId);

      controller.updatePropertyValue({ name: ANNOTATION_FILTER_ATTRIBUTE.CRITERIA_JSON }, {
        ...elyraCriteriaJson,
        criteria_list: updated,
      });
    }
  }, [controller, elyraCriteriaJson]);

  // ── Criteria table configuration ──────────────────────────────────────

  /** Resolved logical operator string (normalised to uppercase). */
  const logicalOp = (elyraCriteriaJson?.logical_operator ?? LOGICAL.AND).toUpperCase();

  /** Column definitions for the compact inline criteria table — sourced from constants. */
  const criteriaTableHeaders: SharedDataTableHeader[] = useMemo(
    () => [{ key: 'conditionDisplay', header: intl.formatMessage(messages.condition) }],
    [intl]
  );

  /**
   * Rows for the compact inline criteria table.
   * Each `conditionDisplay` cell renders condition text + optional AND/OR badge
   * + an inline delete button.
   */
  const criteriaTableRows: SharedDataTableRow[] = useMemo(
    () =>
      criteriaRows.map((row, idx) => ({
        id: row.id,
        conditionDisplay: (
          <div className={styles.conditionCell}>
            <span className={styles.conditionText}>{row.condition}</span>
            {!row.isAdvanced && idx < criteriaRows.length - 1 && (
              <span className={styles.logicalOperatorBadge}>{logicalOp}</span>
            )}
            <div className={styles.actionButtons}>
              <Button
                kind="ghost"
                size="sm"
                hasIconOnly
                renderIcon={TrashCan}
                iconDescription={intl.formatMessage(messages.delete)}
                onClick={() => { handleDeleteCondition(row.id); }}
              />
            </div>
          </div>
        ),
      })),
    [criteriaRows, logicalOp, handleDeleteCondition, intl]
  );

  // ── Available features table ──────────────────────────────────────────

  /** Column definition for the read-only available features table — sourced from constants. */
  const availableFeaturesHeaders: SharedDataTableHeader[] = useMemo(
    () => [
      { key: 'feature', header: intl.formatMessage(messages.featureName) },
      { key: 'type', header: intl.formatMessage(messages.type) },
    ],
    [intl]
  );

  /**
   * Rows for the available features table, derived from the upstream node's
   * `input_features` map. Helps users identify valid column names when writing
   * filter conditions.
   */
  const availableFeaturesRows: SharedDataTableRow[] = useMemo(
    () =>
      featureNames.map((name, idx) => ({
        id: String(idx),
        feature: name,
        type: inputFeatures[name]?.type ?? '',
      })),
    [featureNames, inputFeatures]
  );

  // ── Derived display flags ─────────────────────────────────────────────

  /**
   * `true` when at least one criterion is already saved.
   * Switches the Add/Update button label.
   */
  const hasCriteria = criteriaRows.length > 0;

  /**
   * Tooltip description for the Criteria list label.
   * Prefers the backend-provided description from operator metadata; falls
   * back to the localised default message.
   */
  const criteriaListAttrDescription: string =
    (nodeAttributes[ANNOTATION_FILTER_ATTRIBUTE.CRITERIA_JSON]?.description as string | undefined) ??
    intl.formatMessage(messages.criteriaDescription);

  // ── Render ────────────────────────────────────────────────────────────

  return (
    <div className={styles.panelBody}>
      {/* ── Criteria list ───────────────────────────────────────────── */}
      <div className={styles.formField}>
        <div className={styles.labelWithTooltip}>
          <DefinitionTooltip
            definition={criteriaListAttrDescription}
            openOnHover
            align="right"
          >
            {intl.formatMessage(messages.criteriaList)}
          </DefinitionTooltip>
        </div>

        {criteriaRows.length > 0 && (
          <SharedDataTable
            headers={criteriaTableHeaders}
            rows={criteriaTableRows}
            searchable
            searchPlaceholder={intl.formatMessage(messages.searchCriteria)}
            size="md"
            renderToolbarActions={() => (
              <Button
                kind="ghost"
                size="sm"
                hasIconOnly
                renderIcon={Maximize}
                iconDescription={intl.formatMessage(messages.expandView)}
                onClick={() => { setIsFullViewOpen(true); }}
              />
            )}
          />
        )}

        <Button
          kind="ghost"
          size="md"
          renderIcon={Add}
          className={styles.addCriteriaButton}
          onClick={() => { setIsConditionBuilderOpen(true); }}
        >
          {intl.formatMessage(hasCriteria ? messages.updateCriteria : messages.addCriteria)}
        </Button>
      </div>

      {/* ── Available features ──────────────────────────────────────── */}
      <div className={styles.formField}>
        <FormLabel>{intl.formatMessage(messages.availableFeatures)}</FormLabel>
        <div className={styles.availableFeaturesTable}>
          <SharedDataTable
            headers={availableFeaturesHeaders}
            rows={availableFeaturesRows}
            loading={appData.featuresLoading === true}
            emptyState={
              <p className={styles.emptyFeaturesMessage}>
                {intl.formatMessage(messages.noFeaturesMessage)}
              </p>
            }
            size="md"
          />
        </div>
      </div>

      {/* ── Condition builder tearsheet ─────────────────────────────── */}
      {isConditionBuilderOpen && (
        <ConditionBuilderTearsheet
          open={isConditionBuilderOpen}
          onClose={() => { setIsConditionBuilderOpen(false); }}
          onSave={handleSaveConditions}
          initialConditions={initialConditions}
          initialLogicalOperator={elyraCriteriaJson?.logical_operator ?? LOGICAL.AND}
          initialAdvancedExpression={initialAdvancedExpression}
          features={inputFeatures}
        />
      )}

      {/* ── Full-view tearsheet ─────────────────────────────────────── */}
      {isFullViewOpen && (
        <CriteriaFullViewTearsheet
          open={isFullViewOpen}
          onClose={() => { setIsFullViewOpen(false); }}
          criteriaRows={criteriaRows}
          logicalOperator={elyraCriteriaJson?.logical_operator ?? LOGICAL.AND}
        />
      )}
    </div>
  );
}
