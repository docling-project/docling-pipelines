/**
 * @file ConditionBuilderTearsheet.tsx
 *
 * Tabbed tearsheet for building SQL filter criteria. Shared between operators
 * that accept annotation-based filtering (e.g. `sql_filter`, `branching`).
 *
 * **Simple tab** — delegates to {@link ConditionBuilder} for row-by-row
 * condition editing with type-aware operator filtering and value inputs.
 *
 * **Advanced tab** — Free-text `TextArea` for writing arbitrary SQL
 * expressions that cannot be expressed as individual condition rows.
 *
 * **Tab-switch confirmation** — Switching tabs while the active tab contains
 * unsaved content shows a `ComposedModal` placed inside the Tearsheet children
 * so it renders on top of the Tearsheet overlay correctly.
 *
 * @module ConditionBuilderTearsheet
 */

import React, { useState } from 'react';
import { useIntl } from 'react-intl';
import { useThemeElement } from '@/contexts';
import {
  Button,
  ComposedModal,
  ModalFooter,
  ModalHeader,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
  TextArea,
} from '@carbon/react';
import { Tearsheet } from '@carbon/ibm-products';
import type { FeatureAttributes } from '@/types';
import {
  type Condition,
  generateConditionId,
  LOGICAL,
} from './conditionTypes';
import { ConditionBuilder } from './ConditionBuilder';
import { messages } from './ConditionBuilderTearsheet.messages';
import styles from './ConditionBuilderTearsheet.module.scss';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

/**
 * Props for {@link ConditionBuilderTearsheet}.
 */
export interface ConditionBuilderTearsheetProps {
  /** Whether the tearsheet is visible. */
  open: boolean;
  /** Called when the user dismisses the tearsheet without saving. */
  onClose: () => void;
  /**
   * Called when the user clicks Save.
   *
   * Exactly one of `conditions` / `advancedExpression` carries meaningful data;
   * the other is always empty (empty array / empty string).
   *
   * @param conditions - Structured condition rows from the Simple tab.
   *   Empty array when Advanced mode is active.
   * @param logicalOperator - `"AND"` or `"OR"` selected in the Simple tab.
   * @param advancedExpression - Raw SQL string from the Advanced tab.
   *   Empty string when Simple mode is active.
   */
  onSave: (conditions: Condition[], logicalOperator: string, advancedExpression: string) => void;
  /** Conditions to pre-populate the Simple tab with on open. */
  initialConditions: Condition[];
  /** Logical operator to pre-select on open (`"AND"` or `"OR"`). */
  initialLogicalOperator: string;
  /** Raw SQL expression to pre-populate the Advanced tab with on open. */
  initialAdvancedExpression: string;
  /**
   * Typed input features from the upstream node used to populate the Variable
   * dropdown and filter the Operator dropdown per feature type.
   *
   * Keys are feature names; values carry `type`, `description`, etc.
   */
  features: Record<string, FeatureAttributes>;
  /** When `true`, shows a loading spinner inside the Simple tab. */
  featuresLoading?: boolean;
  /**
   * Optional title override for the tearsheet header.
   * Defaults to `"Criteria"`.
   */
  title?: string;
  /**
   * Optional description override for the tearsheet header.
   * Defaults to a generic SQL example string.
   */
  description?: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Tabbed tearsheet for building SQL filter criteria.
 *
 * Mount it conditionally (`{isOpen && <ConditionBuilderTearsheet … />}`) to
 * reset internal state automatically each time it is opened.
 *
 * @example
 * ```tsx
 * {isBuilderOpen && (
 *   <ConditionBuilderTearsheet
 *     open={isBuilderOpen}
 *     onClose={() => setIsBuilderOpen(false)}
 *     onSave={handleSave}
 *     initialConditions={savedConditions}
 *     initialLogicalOperator="AND"
 *     initialAdvancedExpression=""
 *     features={inputFeatures}
 *   />
 * )}
 * ```
 */
export function ConditionBuilderTearsheet({
  open,
  onClose,
  onSave,
  initialConditions,
  initialLogicalOperator,
  initialAdvancedExpression,
  features,
  featuresLoading = false,
  title,
  description,
}: ConditionBuilderTearsheetProps): React.JSX.Element {
  const intl = useIntl();
  const portalTarget = useThemeElement();
  const [activeTab, setActiveTab] = useState<'simple' | 'advanced'>(
    initialAdvancedExpression ? 'advanced' : 'simple'
  );
  const [conditions, setConditions] = useState<Condition[]>(
    initialConditions.map((c) => (c.id ? c : { ...c, id: generateConditionId() }))
  );
  const [logicalOperator, setLogicalOperator] = useState(
    initialLogicalOperator ?? LOGICAL.AND
  );
  const [advancedExpression, setAdvancedExpression] = useState(initialAdvancedExpression);

  /** The tab the user wants to switch to, held while awaiting confirmation. */
  const [pendingTab, setPendingTab] = useState<'simple' | 'advanced' | null>(null);
  /** Controls visibility of the tab-switch confirmation modal. */
  const [showConfirmModal, setShowConfirmModal] = useState(false);

  // ── Tab switching ─────────────────────────────────────────────────────────

  const handleTabChange = ({ selectedIndex }: { selectedIndex: number }): void => {
    const next: 'simple' | 'advanced' = selectedIndex === 0 ? 'simple' : 'advanced';
    if (next === activeTab) {return;}

    const wouldDiscard =
      (activeTab === 'simple' && conditions.length > 0) ||
      (activeTab === 'advanced' && advancedExpression.trim().length > 0);

    if (wouldDiscard) {
      setPendingTab(next);
      setShowConfirmModal(true);
    } else {
      setActiveTab(next);
    }
  };

  const confirmSwitch = (): void => {
    if (pendingTab === null) { return; }
    if (pendingTab === 'advanced') { setConditions([]); }
    else { setAdvancedExpression(''); }
    setActiveTab(pendingTab);
    setShowConfirmModal(false);
    setPendingTab(null);
  };

  const cancelSwitch = (): void => {
    setShowConfirmModal(false);
    setPendingTab(null);
  };

  // ── Save ──────────────────────────────────────────────────────────────────

  const handleSave = (): void => {
    onSave(
      activeTab === 'simple' ? conditions : [],
      logicalOperator,
      activeTab === 'advanced' ? advancedExpression : ''
    );
  };

  // ── Render ────────────────────────────────────────────────────────────────

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
        { label: intl.formatMessage(messages.cancel), kind: 'secondary' as const, onClick: onClose },
        { label: intl.formatMessage(messages.save), kind: 'primary' as const, onClick: handleSave },
      ]}
    >
      <div className={styles.tearsheetBody}>

        <Tabs
          selectedIndex={activeTab === 'simple' ? 0 : 1}
          onChange={handleTabChange}
        >
          <TabList aria-label={intl.formatMessage(messages.criteriaMode)}>
            <Tab>{intl.formatMessage(messages.simple)}</Tab>
            <Tab>{intl.formatMessage(messages.advanced)}</Tab>
          </TabList>
          <TabPanels>

            {/* ── Simple tab — delegates to ConditionBuilder ────────────── */}
            <TabPanel>
              <ConditionBuilder
                conditions={conditions}
                logicalOperator={logicalOperator}
                features={features}
                isLoading={featuresLoading}
                onChange={({ conditions: updated, logicalOperator: updatedOp }) => {
                  setConditions(updated);
                  setLogicalOperator(updatedOp);
                }}
              />
            </TabPanel>

            {/* ── Advanced tab ──────────────────────────────────────────── */}
            <TabPanel>
              <div className={styles.advancedTabPanel}>
                <TextArea
                  id="advanced-expression"
                  labelText=""
                  placeholder={intl.formatMessage(messages.advancedPlaceholder)}
                  value={advancedExpression}
                  onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => {
                    setAdvancedExpression(e.target.value);
                  }}
                  rows={10}
                />
              </div>
            </TabPanel>

          </TabPanels>
        </Tabs>

        {/* Tab-switch confirmation modal — placed inside the Tearsheet children
            so it renders within the Tearsheet's stacking context, appearing as
            a popup over the Tearsheet overlay. */}
        {showConfirmModal && (
          <ComposedModal open={showConfirmModal} onClose={cancelSwitch}>
            <ModalHeader
              title={
                intl.formatMessage(
                  pendingTab === 'advanced'
                    ? messages.switchToAdvancedConfirm
                    : messages.switchToSimpleConfirm
                )
              }
              closeModal={cancelSwitch}
            />
            <ModalFooter>
              <Button kind="secondary" onClick={cancelSwitch}>
                {intl.formatMessage(messages.cancel)}
              </Button>
              <Button kind="primary" onClick={confirmSwitch}>
                {intl.formatMessage(messages.continue)}
              </Button>
            </ModalFooter>
          </ComposedModal>
        )}

      </div>
    </Tearsheet>
  );
}
