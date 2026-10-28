/**
 * @file ConditionBuilder.tsx
 *
 * Row-by-row GUI condition editor rendered inside the Simple tab of
 * {@link ConditionBuilderTearsheet}.
 *
 * Each condition row contains:
 * - **Variable dropdown** — selects a feature from the upstream node
 * - **Operator dropdown** — filtered to operators valid for the feature's type
 * - **Value input** — adapts to the feature type (TextInput / NumberInput /
 *   RadioButtonGroup / TextArea / dual BETWEEN inputs)
 * - **Delete button** — removes the row
 *
 * A logical-operator (`AND` / `OR`) `RadioButtonGroup` appears above the
 * second row once two or more conditions exist.
 *
 * @module ConditionBuilder
 */

import React, { useState } from 'react';
import {
  Button,
  Dropdown,
  InlineLoading,
  NumberInput,
  RadioButton,
  RadioButtonGroup,
  TextArea,
  TextInput,
  Tooltip,
} from '@carbon/react';
import { Add, Information, TrashCan } from '@carbon/icons-react';
import { useIntl } from 'react-intl';
import type { FeatureAttributes } from '@/types';
import {
  type Condition,
  DATETIME_PLACEHOLDER,
  FEATURE_TYPES,
  generateConditionId,
  isValidJSON,
  LOGICAL,
  NUMERIC_TYPES,
  OPERATORS_BY_TYPE,
  SQL_OPERATORS,
  TIMESTAMP_REGEX,
} from './conditionTypes';
import { messages } from './ConditionBuilder.messages';
import styles from './ConditionBuilder.module.scss';

// ---------------------------------------------------------------------------
// Module-level pure helpers (no component closure needed)
// ---------------------------------------------------------------------------

/**
 * Returns the filtered operator dropdown items for a given feature type.
 * Extracted outside the component — the result depends only on module-level
 * constants so it does not need to re-close over component state on every render.
 *
 * @param featureType - The feature's type string (e.g. `"float"`, `"boolean"`).
 */
function getOperatorItems(featureType: string): Array<typeof SQL_OPERATORS[number]> {
  const allowed = OPERATORS_BY_TYPE[featureType] ?? OPERATORS_BY_TYPE['default']!;
  return (SQL_OPERATORS as unknown as Array<typeof SQL_OPERATORS[number]>).filter((o) =>
    (allowed).includes(o.value)
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Props shared by both the Variable and Operator dropdown sub-components. */
interface ConditionDropdownProps {
  conditionId: string;
  isReadOnlyMode: boolean;
}

/** Props for the Variable dropdown. */
interface VariableDropdownProps extends ConditionDropdownProps {
  variable: string;
  features: Record<string, FeatureAttributes>;
  onVariableChange: (conditionId: string, variable: string) => void;
}

/**
 * Variable dropdown — shows `"name (type)"` in the open list but the bare
 * feature name when an item is selected.
 */
function VariableDropdown({
  conditionId,
  variable,
  features,
  isReadOnlyMode,
  onVariableChange,
}: VariableDropdownProps): React.JSX.Element {
  const intl = useIntl();
  const featureNames = Object.keys(features);
  const variableItems = featureNames.map((name) => ({
    id: name,
    label: `${name} (${features[name]?.type ?? 'string'})`,
  }));
  const selectedVariable = variableItems.find((item) => item.id === variable) ?? null;
  return (
    <Dropdown
      id={`var-${conditionId}`}
      titleText={intl.formatMessage(messages.variable)}
      label={intl.formatMessage(messages.chooseVariable)}
      items={variableItems}
      itemToString={(item: { id: string; label: string } | null) => item?.id ?? ''}
      selectedItem={selectedVariable}
      onChange={({ selectedItem }: { selectedItem: { id: string; label: string } | null }) => {
        onVariableChange(conditionId, selectedItem?.id ?? '');
      }}
      disabled={isReadOnlyMode}
    />
  );
}

/** Props for the Operator dropdown. */
interface OperatorDropdownProps extends ConditionDropdownProps {
  featureType: string;
  operator: string;
  onOperatorChange: (conditionId: string, operator: string) => void;
}

/**
 * Operator dropdown — filtered to the operators valid for the selected feature type.
 */
function OperatorDropdown({
  conditionId,
  featureType,
  operator,
  isReadOnlyMode,
  onOperatorChange,
}: OperatorDropdownProps): React.JSX.Element {
  const intl = useIntl();
  const items = getOperatorItems(featureType);
  return (
    <Dropdown
      id={`op-${conditionId}`}
      titleText={intl.formatMessage(messages.operator)}
      label={intl.formatMessage(messages.chooseOperator)}
      items={items}
      itemToString={(item: typeof SQL_OPERATORS[number] | null) => (item ? intl.formatMessage(item.label) : '')}
      selectedItem={items.find((o) => o.value === operator) ?? null}
      onChange={({
        selectedItem,
      }: {
        selectedItem: typeof SQL_OPERATORS[number] | null;
      }) => {
        onOperatorChange(conditionId, selectedItem?.value ?? '');
      }}
      disabled={isReadOnlyMode}
    />
  );
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

/**
 * Props for {@link ConditionBuilder}.
 */
export interface ConditionBuilderProps {
  /** Current list of condition rows. Controlled by the parent tearsheet. */
  conditions: Condition[];
  /** Whether multiple conditions are combined with AND or OR. */
  logicalOperator: string;
  /**
   * Called whenever conditions or the logical operator change.
   *
   * @param updated - The new conditions array and logical operator.
   */
  onChange: (updated: { conditions: Condition[]; logicalOperator: string }) => void;
  /**
   * Typed input features from the upstream node.
   * Keys are feature names; values carry `type`, `description`, etc.
   */
  features: Record<string, FeatureAttributes>;
  /** When `true`, all inputs and buttons are rendered as read-only / disabled. */
  isReadOnlyMode?: boolean;
  /** When `true`, shows an `InlineLoading` spinner instead of the condition rows. */
  isLoading?: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Row-by-row GUI condition editor for building SQL filter criteria.
 *
 * @param props - {@link ConditionBuilderProps}
 */
export function ConditionBuilder({
  conditions,
  logicalOperator,
  onChange,
  features,
  isReadOnlyMode = false,
  isLoading = false,
}: ConditionBuilderProps): React.JSX.Element {
  const intl = useIntl();
  /**
   * Per-condition validation error messages, keyed by `Condition.id`.
   * Errors are set on blur, not on every keystroke — see `handleBlur`.
   */
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({});

  // ── Derived data ────────────────────────────────────────────────────────
  const featureNames = Object.keys(features);

  // ── Helpers ─────────────────────────────────────────────────────────────

  /**
   * Resolves the type for a given feature name.
   * Falls back to `"string"` if the feature is unknown.
   *
   * @param variable - Feature name as returned by the backend.
   * @returns The feature type string.
   */
  const getFeatureType = (variable: string): string =>
    features[variable]?.type ?? 'string';

  /**
   * Validates the value string for a condition row.
   * Returns an error message string, or `""` if valid.
   */
  const validateValue = (condition: Condition, value: string): string => {
    if (!value) {return '';}
    if (condition.operator === 'is null' || condition.operator === 'is not null') {return '';}

    const featureType = getFeatureType(condition.variable);

    if (featureType === FEATURE_TYPES.DATETIME) {
      if (condition.operator === 'between') {
        const [v1, v2] = value.split('|');
        if (!v1 || !v2 || !TIMESTAMP_REGEX.test(v1) || !TIMESTAMP_REGEX.test(v2)) {
          return intl.formatMessage(messages.errorInvalidTimestampRange);
        }
      } else if (!TIMESTAMP_REGEX.test(value)) {
        return intl.formatMessage(messages.errorInvalidTimestamp);
      }
    }

    if (featureType === FEATURE_TYPES.JSON && !isValidJSON(value)) {
      return intl.formatMessage(messages.errorInvalidJson);
    }

    return '';
  };

  // ── Condition mutations ──────────────────────────────────────────────────

  const addCondition = (): void => {
    onChange({
      conditions: [
        ...conditions,
        { id: generateConditionId(), variable: '', operator: '', value: '' },
      ],
      logicalOperator,
    });
  };

  const removeCondition = (idx: number): void => {
    const removed = conditions[idx];
    if (!removed) {return;}
    onChange({
      conditions: conditions.filter((_, i) => i !== idx),
      logicalOperator,
    });
    setValidationErrors((prev) => {
      const next = { ...prev };
      delete next[removed.id];
      return next;
    });
  };

  /**
   * Updates condition fields without triggering validation.
   * Clears any stale validation error for the field so the red border
   * disappears as soon as the user starts editing.
   */
  const updateCondition = (conditionId: string, updates: Partial<Condition>): void => {
    const updated = conditions.map((c) => {
      if (c.id !== conditionId) {return c;}
      const next = { ...c, ...updates };
      // Auto-set boolean default when variable changes
      if ('variable' in updates) {
        const type = getFeatureType(updates.variable ?? '');
        if (
          (type === FEATURE_TYPES.BOOLEAN || type === FEATURE_TYPES.BOOL) &&
          !next.value
        ) {
          next.value = 'false';
        }
        // Clear value (not operator) when variable changes.
        // Keeping the operator lets users switch variables without losing their chosen operator.
        next.value = '';
      }
      return next;
    });
    onChange({ conditions: updated, logicalOperator });

    // Validate on every value change (not just on blur) to give immediate feedback.
    if ('value' in updates) {
      const condition = updated.find((c) => c.id === conditionId);
      if (condition) {
        const error = validateValue(condition, updates.value ?? '');
        setValidationErrors((prev) => ({ ...prev, [conditionId]: error }));
      }
    }
  };

  /**
   * Runs validation for a condition's current value when the input loses focus.
   * This prevents error messages from appearing mid-keystroke.
   */
  const handleBlur = (conditionId: string): void => {
    const condition = conditions.find((c) => c.id === conditionId);
    if (!condition) {return;}
    const error = validateValue(condition, condition.value);
    setValidationErrors((prev) => ({ ...prev, [conditionId]: error }));
  };

  // ── Value input rendering ────────────────────────────────────────────────

  /**
   * Returns the appropriate input element for the condition's feature type
   * and selected operator. Returns `null` for null-check operators.
   */
  const renderValueInput = (condition: Condition): React.ReactNode => {
    if (
      condition.operator === 'is null' ||
      condition.operator === 'is not null'
    ) {
      return null;
    }

    const featureType = getFeatureType(condition.variable);
    const error = validationErrors[condition.id] ?? '';
    const isBetween = condition.operator === 'between';

    // ── Boolean ────────────────────────────────────────────────────────────
    if (
      featureType === FEATURE_TYPES.BOOLEAN ||
      featureType === FEATURE_TYPES.BOOL
    ) {
      const key = `bool-${condition.id}`;
      const boolValue = condition.value === 'true';
      return (
        <RadioButtonGroup
          key={key}
          name={key}
          legendText={intl.formatMessage(messages.value)}
          className={styles.booleanInputWrapper}
          onChange={(evt: React.ChangeEvent<HTMLInputElement> | string | number | undefined) => {
            // Carbon's RadioButtonGroup passes the value directly in some versions
            // and an event object in others — handle both forms.
            const val = typeof evt === 'object' && evt !== null && 'target' in evt
              ? (evt).target.value
              : String(evt ?? 'false');
            updateCondition(condition.id, { value: val });
          }}
        >
          <RadioButton
            id={`${key}-true`}
            value="true"
            labelText={intl.formatMessage(messages.valueTrue)}
            checked={boolValue}
            disabled={isReadOnlyMode}
          />
          <RadioButton
            id={`${key}-false`}
            value="false"
            labelText={intl.formatMessage(messages.valueFalse)}
            checked={!boolValue}
            disabled={isReadOnlyMode}
          />
        </RadioButtonGroup>
      );
    }

    // ── Numeric ────────────────────────────────────────────────────────────
    if (NUMERIC_TYPES.includes(featureType)) {
      if (isBetween) {
        const [v1 = '', v2 = ''] = condition.value.split(',');
        return (
          <div className={styles.betweenInputWrapper}>
            <NumberInput
              id={`num-start-${condition.id}`}
              label={intl.formatMessage(messages.startValue)}
              value={v1}
              invalid={!!error}
              invalidText={error}
              allowEmpty
              hideSteppers={false}
              size="md"
              onChange={(_e: unknown, { value: newV1 }: { value: string | number }) => {
                updateCondition(condition.id, { value: `${String(newV1 ?? '')},${v2}` });
              }}
            />
            <NumberInput
              id={`num-end-${condition.id}`}
              label={intl.formatMessage(messages.endValue)}
              value={v2}
              invalid={!!error}
              invalidText={error}
              allowEmpty
              hideSteppers={false}
              size="md"
              onChange={(_e: unknown, { value: newV2 }: { value: string | number }) => {
                updateCondition(condition.id, { value: `${v1},${String(newV2 ?? '')}` });
              }}
            />
          </div>
        );
      }
      return (
        <NumberInput
          id={`num-${condition.id}`}
          label={intl.formatMessage(messages.value)}
          value={condition.value}
          invalid={!!error}
          invalidText={error}
          allowEmpty
          hideSteppers={false}
          size="md"
          onChange={(_e: unknown, { value: newVal }: { value: string | number }) => {
            updateCondition(condition.id, { value: String(newVal ?? '') });
          }}
        />
      );
    }

    // ── DateTime ───────────────────────────────────────────────────────────
    if (featureType === FEATURE_TYPES.DATETIME) {
      if (isBetween) {
        const [v1 = '', v2 = ''] = condition.value.split('|');
        return (
          <div className={styles.betweenInputWrapper}>
            <TextInput
              id={`dt-start-${condition.id}`}
              labelText={intl.formatMessage(messages.startValue)}
              placeholder={DATETIME_PLACEHOLDER}
              helperText={intl.formatMessage(messages.datetimeHelper)}
              value={v1}
              invalid={!!error}
              invalidText={error}
              readOnly={isReadOnlyMode}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                updateCondition(condition.id, { value: `${e.target.value}|${v2}` });
              }}
              onBlur={() => { handleBlur(condition.id); }}
            />
            <TextInput
              id={`dt-end-${condition.id}`}
              labelText={intl.formatMessage(messages.endValue)}
              placeholder={DATETIME_PLACEHOLDER}
              helperText={intl.formatMessage(messages.datetimeHelper)}
              value={v2}
              invalid={!!error}
              invalidText={error}
              readOnly={isReadOnlyMode}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                updateCondition(condition.id, { value: `${v1}|${e.target.value}` });
              }}
              onBlur={() => { handleBlur(condition.id); }}
            />
          </div>
        );
      }
      return (
        <TextInput
          id={`dt-${condition.id}`}
          labelText={intl.formatMessage(messages.value)}
          placeholder={DATETIME_PLACEHOLDER}
          helperText={intl.formatMessage(messages.datetimeHelper)}
          value={condition.value}
          invalid={!!error}
          invalidText={error}
          readOnly={isReadOnlyMode}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
            updateCondition(condition.id, { value: e.target.value });
          }}
          onBlur={() => { handleBlur(condition.id); }}
        />
      );
    }

    // ── JSON ───────────────────────────────────────────────────────────────
    if (featureType === FEATURE_TYPES.JSON) {
      return (
        <TextArea
          id={`json-${condition.id}`}
          labelText={intl.formatMessage(messages.value)}
          placeholder={intl.formatMessage(messages.enterJsonValue)}
          helperText={intl.formatMessage(messages.jsonHelper)}
          value={condition.value}
          invalid={!!error}
          invalidText={error}
          rows={4}
          readOnly={isReadOnlyMode}
          onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => {
            updateCondition(condition.id, { value: e.target.value });
          }}
          onBlur={() => { handleBlur(condition.id); }}
        />
      );
    }

    // ── String / default — BETWEEN ──────────────────────────────────────────
    if (isBetween) {
      const [v1 = '', v2 = ''] = condition.value.split(',');
      return (
        <div className={styles.betweenInputWrapper}>
          <TextInput
            id={`str-start-${condition.id}`}
            labelText={intl.formatMessage(messages.startValue)}
            value={v1}
            readOnly={isReadOnlyMode}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
              updateCondition(condition.id, { value: `${e.target.value},${v2}` });
            }}
          />
          <TextInput
            id={`str-end-${condition.id}`}
            labelText={intl.formatMessage(messages.endValue)}
            value={v2}
            readOnly={isReadOnlyMode}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
              updateCondition(condition.id, { value: `${v1},${e.target.value}` });
            }}
          />
        </div>
      );
    }

    // ── String / default — single input ────────────────────────────────────
    const isMultiValue =
      condition.operator === 'in' || condition.operator === 'not in';

    return (
      <TextInput
        id={`val-${condition.id}`}
        labelText={intl.formatMessage(messages.value)}
        placeholder={intl.formatMessage(isMultiValue ? messages.enterMultipleValues : messages.enterValue)}
        helperText={isMultiValue ? intl.formatMessage(messages.commaSeparatedHelper) : undefined}
        value={condition.value}
        readOnly={isReadOnlyMode}
        onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
          updateCondition(condition.id, { value: e.target.value });
        }}
      />
    );
  };

  // ── Loading / empty states ───────────────────────────────────────────────

  if (isLoading) {
    return <InlineLoading description={intl.formatMessage(messages.loadingFeatures)} />;
  }

  if (featureNames.length === 0) {
    return (
      <div className={styles.noDataWrapper}>
        {intl.formatMessage(messages.noFeatures)}
      </div>
    );
  }

  // ── Render ───────────────────────────────────────────────────────────────

  /** Renders a single condition card (shared between primary and sub-conditions). */
  const renderConditionCard = (c: Condition, idx: number): React.JSX.Element => (
    <div className={styles.conditionCard} key={c.id}>
      <div className={styles.conditionFields}>
        <VariableDropdown
          conditionId={c.id}
          variable={c.variable}
          features={features}
          isReadOnlyMode={isReadOnlyMode}
          onVariableChange={(id, variable) => { updateCondition(id, { variable }); }}
        />
        <OperatorDropdown
          conditionId={c.id}
          featureType={getFeatureType(c.variable)}
          operator={c.operator}
          isReadOnlyMode={isReadOnlyMode}
          onOperatorChange={(id, operator) => { updateCondition(id, { operator }); }}
        />
        {/* Value — type-aware */}
        {renderValueInput(c)}
      </div>

      {/* AND / OR pill — shown on sub-condition cards (idx > 0), right of Value */}
      {idx > 0 && (
        <span className={styles.logicalPill}>{logicalOperator}</span>
      )}

      {/* Delete button — far right */}
      {!isReadOnlyMode && (
        <Button
          kind="ghost"
          size="sm"
          hasIconOnly
          renderIcon={TrashCan}
          iconDescription={intl.formatMessage(messages.deleteCondition)}
          className={styles.deleteButton}
          onClick={() => { removeCondition(idx); }}
        />
      )}
    </div>
  );

  const [primaryCondition, ...subConditions] = conditions;

  return (
    <div className={styles.conditionsWrapper}>

      {/* Primary condition — no blue rail, stands alone */}
      {primaryCondition && renderConditionCard(primaryCondition, 0)}

      {/* Logical operator selector — only visible once a second condition exists */}
      {subConditions.length > 0 && (
        <div className={styles.logicalOperatorStrip}>
          <div className={styles.logicalOperatorLabel}>
            {intl.formatMessage(messages.logicalOperator)}
            <Tooltip align="top" label={intl.formatMessage(messages.logicalOperatorTooltip)}>
              <button type="button" className={styles.infoButton}>
                <Information />
              </button>
            </Tooltip>
          </div>
          <RadioButtonGroup
            name="logical-operator"
            legendText=""
            valueSelected={logicalOperator}
            className={styles.equalColumns}
            onChange={(val: string | number | undefined) => {
              onChange({ conditions: [...conditions], logicalOperator: String(val ?? LOGICAL.AND) });
            }}
          >
            <RadioButton
              id="logic-and"
              value={LOGICAL.AND}
              labelText={intl.formatMessage(messages.and)}
              disabled={isReadOnlyMode}
            />
            <RadioButton
              id="logic-or"
              value={LOGICAL.OR}
              labelText={intl.formatMessage(messages.or)}
              disabled={isReadOnlyMode}
            />
          </RadioButtonGroup>
        </div>
      )}

      {/* Sub-conditions rail — blue left border signals these are joined conditions */}
      {subConditions.length > 0 && (
        <div className={styles.conditionsRail}>
          {subConditions.map((c, subIdx) =>
            renderConditionCard(c, subIdx + 1)
          )}
        </div>
      )}

      {/* Add condition button */}
      {!isReadOnlyMode && (
        <div className={styles.addButtonWrapper}>
          <Button kind="ghost" renderIcon={Add} onClick={addCondition}>
            {intl.formatMessage(messages.addCondition)}
          </Button>
        </div>
      )}
    </div>
  );
}
