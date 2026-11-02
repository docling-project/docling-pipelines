/**
 * @file LinkConditionTearsheet.tsx
 *
 * Tearsheet for setting a **link name** and optional **condition** on an
 * outgoing link from a Branching node, or a link name on a Merging node link.
 *
 * - **Branching links** — shows link name input + tabbed condition builder
 *   (Simple rows | Advanced free-text SQL expression).
 * - **Merging links** — shows link name input only (no condition needed).
 *
 * Tab-switch confirmation dialog prevents accidental data loss when the user
 * switches between Simple and Advanced tabs while unsaved content exists.
 *
 * @module LinkConditionTearsheet
 */

import React, { useState, useEffect } from 'react';
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
  TextInput,
} from '@carbon/react';
import { Tearsheet } from '@carbon/ibm-products';
import { useIntl } from 'react-intl';
import type { FeatureAttributes } from '@/types';
import {
  type Condition,
  type CriteriaJson,
  LOGICAL,
} from '../PropertiesPanel/CustomPanels/AnnotationFilter/conditionTypes';
import { ConditionBuilder } from '../PropertiesPanel/CustomPanels/AnnotationFilter/ConditionBuilder';
import {
  convertToEpoch,
  convertFromEpoch,
  isEpochValue,
} from '@/utils/dateTimeUtils';
import { messages } from './LinkConditionTearsheet.messages';
import styles from './LinkConditionTearsheet.module.scss';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** The condition payload stored in `link_conditions[n].condition`. */
export interface BranchLinkCondition {
  /** Simple mode — structured criteria. */
  criteria_json?: { logical_operator: string; criteria_list: CriteriaJson['criteria_list'] };
  /** Advanced mode — raw SQL expression string(s). */
  criteria_list?: string[];
}

export interface LinkConditionValues {
  linkName: string;
  /** Present for branching links; absent / undefined for merging links. */
  condition?: BranchLinkCondition;
}

export interface LinkConditionTearsheetProps {
  /** Whether the tearsheet is visible. */
  open: boolean;
  /** Called when the user dismisses the tearsheet without saving. */
  onClose: () => void;
  /**
   * Called when the user clicks Save.
   * @param linkName - The display name for the link.
   * @param condition - The condition (branching) or `undefined` (merging).
   * @param mergingNodeId - Supplied only for merging links; undefined otherwise.
   */
  onSave: (linkName: string, condition: LinkConditionValues['condition'], mergingNodeId?: string) => void;
  /** Pre-populated values when editing an existing link condition. */
  initialValues: LinkConditionValues;
  /** Id of the branching node — used to fetch upstream features for condition builder. */
  branchingNodeId: string;
  /** When true the tearsheet is opened for a Merging link (no condition tab). */
  isMergingNode: boolean;
  /** When true all controls are read-only. */
  isReadOnly?: boolean;
  /** Input features for the condition builder variable dropdown. */
  inputFeatures?: Record<string, FeatureAttributes>;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const TAB_SIMPLE = 'simple' as const;
const TAB_ADVANCED = 'advanced' as const;
type TabType = typeof TAB_SIMPLE | typeof TAB_ADVANCED;

/**
 * Tearsheet that lets the user assign a name and optional condition to a canvas link.
 */
export function LinkConditionTearsheet({
  open,
  onClose,
  onSave,
  initialValues,
  branchingNodeId,
  isMergingNode,
  isReadOnly = false,
  inputFeatures = {},
}: LinkConditionTearsheetProps): React.JSX.Element {
  const intl = useIntl();

  const [linkName, setLinkName] = useState(initialValues.linkName);
  const [activeTab, setActiveTab] = useState<TabType>(TAB_SIMPLE);
  const [conditions, setConditions] = useState<Condition[]>([]);
  const [logicalOperator, setLogicalOperator] = useState<string>(LOGICAL.AND);
  const [advancedExpression, setAdvancedExpression] = useState('');
  const [pendingTab, setPendingTab] = useState<TabType | null>(null);
  const [showConfirmModal, setShowConfirmModal] = useState(false);

  // Re-populate state whenever initialValues changes (i.e. a different link was clicked).
  useEffect(() => {
    setLinkName(initialValues.linkName ?? '');

    if (isMergingNode) {
      // Merging — no condition
      setActiveTab(TAB_SIMPLE);
      setConditions([]);
      setAdvancedExpression('');
      return;
    }

    const cond = initialValues.condition;
    if (cond && 'criteria_json' in cond && cond.criteria_json) {
      const { criteria_list, logical_operator } = cond.criteria_json;
      // Convert epoch → human-readable for display
      const displayConditions = criteria_list.map((c) => {
        if (isEpochValue(c.value) && c.value) {
          return { ...c, value: convertFromEpoch(c.value) };
        }
        return c;
      });
      setConditions(displayConditions);
      setLogicalOperator(logical_operator ?? LOGICAL.AND);
      setActiveTab(TAB_SIMPLE);
    } else if (cond && 'criteria_list' in cond && Array.isArray(cond.criteria_list)) {
      setAdvancedExpression(cond.criteria_list[0] ?? '');
      setActiveTab(TAB_ADVANCED);
    } else {
      setConditions([]);
      setLogicalOperator(LOGICAL.AND);
      setAdvancedExpression('');
      setActiveTab(TAB_SIMPLE);
    }
  }, [initialValues, isMergingNode]);

  // ── Tab-switch handling ────────────────────────────────────────────────────

  const handleTabChange = (index: number): void => {
    if (isReadOnly) { return; }
    const next: TabType = index === 0 ? TAB_SIMPLE : TAB_ADVANCED;
    if (next === activeTab) { return; }
    setPendingTab(next);
    setShowConfirmModal(true);
  };

  const confirmTabSwitch = (): void => {
    if (pendingTab === TAB_ADVANCED) {
      setAdvancedExpression('');
      setConditions([]);
    } else {
      setConditions([]);
      setAdvancedExpression('');
    }
    if (pendingTab) { setActiveTab(pendingTab); }
    setPendingTab(null);
    setShowConfirmModal(false);
  };

  const cancelTabSwitch = (): void => {
    setPendingTab(null);
    setShowConfirmModal(false);
  };

  // ── Save validation ────────────────────────────────────────────────────────

  const isSaveDisabled = (): boolean => {
    const trimmed = linkName.trim();
    const initialTrimmed = (initialValues.linkName ?? '').trim();
    const isLinkNameChanged = trimmed !== initialTrimmed;

    if (isMergingNode) {
      // Merging: save only if link name is non-empty and changed.
      return !trimmed || !isLinkNameChanged;
    }

    if (!trimmed) { return true; }

    if (activeTab === TAB_SIMPLE) {
      if (conditions.length === 0) {
        // No conditions set — allow save only if the link name changed
        return !isLinkNameChanged;
      }

      // Has conditions — disable if any condition row is incomplete
      const hasIncomplete = conditions.some((c) => {
        const noValue = ['is null', 'is not null'].includes(c.operator?.toLowerCase?.() ?? '');
        return !c.variable?.trim() || !c.operator?.trim() || (!noValue && !c.value?.trim());
      });
      return hasIncomplete && !isLinkNameChanged;
    }

    // Advanced tab — disable if no expression and link name unchanged
    return !advancedExpression.trim() && !isLinkNameChanged;
  };

  // ── Save handler ───────────────────────────────────────────────────────────

  const handleSave = (): void => {
    const name = linkName;

    if (isMergingNode) {
      onSave(name, undefined, branchingNodeId);
      return;
    }

    if (activeTab === TAB_SIMPLE) {
      const processedConditions = conditions.map((c) => {
        // Convert human-readable datetime → epoch for storage
        if (inputFeatures[c.variable]?.type === 'datetime' && c.value && !isEpochValue(c.value)) {
          return { ...c, value: String(convertToEpoch(c.value)) };
        }
        return c;
      });
      onSave(name, {
        criteria_json: {
          logical_operator: logicalOperator,
          criteria_list: processedConditions,
        },
      });
    } else {
      onSave(name, { criteria_list: [advancedExpression.trim()] });
    }
  };

  // ── Actions ────────────────────────────────────────────────────────────────

  const tearsheetActions = isReadOnly
    ? [{ kind: 'primary' as const, label: intl.formatMessage(messages.actionClose), onClick: onClose }]
    : [
        { kind: 'secondary' as const, label: intl.formatMessage(messages.actionCancel), onClick: onClose },
        { kind: 'primary' as const, label: intl.formatMessage(messages.actionSave), onClick: handleSave, disabled: isSaveDisabled() },
      ];

  return (
    <Tearsheet
      open={open}
      onClose={onClose}
      label={isMergingNode ? intl.formatMessage(messages.labelLinkName) : intl.formatMessage(messages.labelLinkCondition)}
      title={isMergingNode ? intl.formatMessage(messages.titleEditLinkName) : intl.formatMessage(messages.titleEditLinkCondition)}
      actions={tearsheetActions}
    >
      <div className={styles.container}>
        <Tabs
          selectedIndex={activeTab === TAB_SIMPLE ? 0 : 1}
          onChange={({ selectedIndex }) => { handleTabChange(selectedIndex); }}
        >
          <TabList aria-label="Condition type">
            <Tab disabled={isReadOnly}>{intl.formatMessage(messages.tabSimple)}</Tab>
            {!isMergingNode && <Tab disabled={isReadOnly}>{intl.formatMessage(messages.tabAdvanced)}</Tab>}
          </TabList>

          <TabPanels>
            {/* ── Simple tab ── */}
            <TabPanel>
              <div className={styles.linkNameField}>
                <TextInput
                  id="lct-link-name"
                  labelText={intl.formatMessage(messages.linkNameLabel)}
                  value={linkName}
                  onChange={(e) => { setLinkName(e.target.value); }}
                  required
                  readOnly={isReadOnly}
                />
              </div>
              {!isMergingNode && (
                <ConditionBuilder
                  conditions={conditions}
                  logicalOperator={logicalOperator}
                  features={inputFeatures}
                  onChange={({ conditions: updated, logicalOperator: op }) => {
                    setConditions(updated);
                    setLogicalOperator(op);
                  }}
                  isReadOnlyMode={isReadOnly}
                />
              )}
            </TabPanel>

            {/* ── Advanced tab (branching only) ── */}
            {!isMergingNode && (
              <TabPanel>
                <div className={styles.linkNameField}>
                  <TextInput
                    id="lct-link-name-adv"
                    labelText={intl.formatMessage(messages.linkNameLabel)}
                    value={linkName}
                    onChange={(e) => { setLinkName(e.target.value); }}
                    required
                    readOnly={isReadOnly}
                  />
                </div>
                <TextArea
                  id="lct-advanced-condition"
                  labelText={intl.formatMessage(messages.complexConditionLabel)}
                  placeholder={intl.formatMessage(messages.complexConditionPlaceholder)}
                  value={advancedExpression}
                  onChange={(e) => { setAdvancedExpression(e.target.value); }}
                  readOnly={isReadOnly}
                  rows={6}
                />
              </TabPanel>
            )}
          </TabPanels>
        </Tabs>

        {/* ── Tab-switch confirmation modal ── */}
        {showConfirmModal && (
          <ComposedModal open={showConfirmModal} onClose={cancelTabSwitch}>
            <ModalHeader
              title={
                pendingTab === TAB_ADVANCED
                  ? intl.formatMessage(messages.confirmSwitchToAdvanced)
                  : intl.formatMessage(messages.confirmSwitchToSimple)
              }
              closeModal={cancelTabSwitch}
            />
            <ModalFooter>
              <Button kind="secondary" onClick={cancelTabSwitch}>{intl.formatMessage(messages.cancel)}</Button>
              <Button kind="primary" onClick={confirmTabSwitch}>{intl.formatMessage(messages.confirm)}</Button>
            </ModalFooter>
          </ComposedModal>
        )}
      </div>
    </Tearsheet>
  );
}
