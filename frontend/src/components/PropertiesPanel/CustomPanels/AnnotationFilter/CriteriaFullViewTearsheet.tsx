/**
 * @file CriteriaFullViewTearsheet.tsx
 *
 * Full-screen tearsheet opened when the user clicks the Maximize icon in the
 * criteria table toolbar. Renders all saved criteria in a searchable,
 * paginated table with logical-operator (`AND` / `OR`) badges between rows.
 *
 * Extracted as a standalone component so it can be reused by any operator
 * that uses the condition-builder pattern.
 *
 * @module CriteriaFullViewTearsheet
 */

import React, { useMemo } from 'react';
import { useIntl } from 'react-intl';
import { useThemeElement } from '@/contexts';
import { Tearsheet } from '@carbon/ibm-products';
import { SharedDataTable } from '@/components/common/SharedDataTable';
import type { SharedDataTableRow } from '@/components/common/SharedDataTable';
import { LOGICAL } from './conditionTypes';
import { messages } from './CriteriaFullViewTearsheet.messages';
import styles from './CriteriaFullViewTearsheet.module.scss';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * A single row in the criteria display table.
 *
 * Extends {@link SharedDataTableRow} so it can be passed directly to
 * {@link SharedDataTable} without transformation.
 */
export interface CriteriaDisplayRow extends SharedDataTableRow {
  /** Human-readable condition string (e.g. `"lang_score >= 0.3"`). */
  condition: string;
  /**
   * `true` when this row represents an Advanced-mode raw SQL expression.
   * Advanced rows never show a logical-operator badge between them.
   */
  isAdvanced?: boolean;
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

/**
 * Props for {@link CriteriaFullViewTearsheet}.
 */
export interface CriteriaFullViewTearsheetProps {
  /** Whether the tearsheet is visible. */
  open: boolean;
  /** Called when the user closes the tearsheet. */
  onClose: () => void;
  /** The criteria rows to display, sourced from the panel's derived state. */
  criteriaRows: CriteriaDisplayRow[];
  /**
   * The active logical operator shown as a badge between adjacent rows.
   * Accepts `"AND"` or `"OR"`. Defaults to `"AND"` when empty.
   */
  logicalOperator: string;
  /**
   * Optional tearsheet title override.
   * Defaults to `"Criteria"`.
   */
  title?: string;
  /**
   * Optional tearsheet description override.
   * Defaults to a generic SQL example string.
   */
  description?: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Full-screen tearsheet that renders all saved filter criteria in a
 * searchable, paginated table.
 *
 * Each row (except the last) shows a logical-operator badge (`AND` / `OR`)
 * on the right edge to indicate how adjacent conditions are combined.
 * Advanced-mode rows (raw SQL strings) never show the badge.
 *
 * @example
 * ```tsx
 * {isFullViewOpen && (
 *   <CriteriaFullViewTearsheet
 *     open={isFullViewOpen}
 *     onClose={() => setIsFullViewOpen(false)}
 *     criteriaRows={criteriaRows}
 *     logicalOperator={logicalOperator}
 *   />
 * )}
 * ```
 */
export function CriteriaFullViewTearsheet({
  open,
  onClose,
  criteriaRows,
  logicalOperator,
  title,
  description,
}: CriteriaFullViewTearsheetProps): React.JSX.Element {
  const intl = useIntl();
  /** Normalised logical operator string (always uppercase). */
  const portalTarget = useThemeElement();
  const logicalOp = (logicalOperator ?? LOGICAL.AND).toUpperCase();

  /**
   * Maps each {@link CriteriaDisplayRow} to a {@link SharedDataTableRow}
   * whose `conditionDisplay` cell contains the condition text plus an
   * optional logical-operator badge.
   *
   * Memoised on `criteriaRows` and `logicalOp` — only recalculated when the
   * criteria or logical operator changes.
   */
  const tableRows: SharedDataTableRow[] = useMemo(
    () =>
      criteriaRows.map((row, idx) => ({
        id: row.id,
        conditionDisplay: (
          <div className={styles.conditionCell}>
            <span>{row.condition}</span>
            {idx < criteriaRows.length - 1 && !row.isAdvanced && (
              <span className={styles.logicalOperatorBadge}>{logicalOp}</span>
            )}
          </div>
        ),
      })),
    [criteriaRows, logicalOp]
  );

  const fullViewTableHeaders = useMemo(
    () => [{ key: 'conditionDisplay', header: intl.formatMessage(messages.condition) }],
    [intl]
  );

  return (
    <Tearsheet
      open={open}
      onClose={onClose}
      title={title ?? intl.formatMessage(messages.title)}
      description={description ?? intl.formatMessage(messages.description)}
      hasCloseIcon
      closeIconDescription={intl.formatMessage(messages.close)}
      portalTarget={portalTarget}
      actions={[
        { label: intl.formatMessage(messages.close), kind: 'primary' as const, onClick: onClose },
      ]}
    >
      <div className={styles.fullViewTableWrapper}>
        <SharedDataTable
          headers={fullViewTableHeaders}
          rows={tableRows}
          searchable
          searchPlaceholder={intl.formatMessage(messages.searchCriteria)}
          size="md"
        />
      </div>
    </Tearsheet>
  );
}
