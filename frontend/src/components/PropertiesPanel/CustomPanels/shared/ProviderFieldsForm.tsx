/**
 * @file ProviderFieldsForm
 *
 * Renders a structured per-field form driven by the provider schema embedded
 * in the `provider_config.providers[provider]` entry of the operator metadata.
 *
 * Each field in the provider's `properties` map is rendered as the appropriate
 * Carbon input based on its `type` value:
 *
 *   string (sensitive) → VaultInput (supports plaintext or vault:// URI)
 *   string (non-sensitive) → TextInput
 *   int64 / double (nullable)  → NullableNumberInput (toggle + number input)
 *   int64 / double (required)  → NumberInput
 *   boolean → Toggle
 *   list → ListInput  (Add button + table; string[] stored as array)
 *   json → JsonTextArea  (raw JSON object)
 *
 * Sensitivity is determined by `keyInfo.sensitive === true` from operator metadata.
 * Nullability is determined by `keyInfo.default === null` from operator metadata.
 *
 * No wiring occurs here.
 * The component calls `onChange(fieldKey, value)` so the parent can
 * decide which controller attribute(s) to write to once.
 */

import React, { useEffect, useState } from 'react';
import {
  NumberInput,
  TextInput,
  Toggle,
} from '@carbon/react';
import { DefinitionTooltip } from '@carbon/react';
import { JsonTextArea, ListInput, VaultInput } from '@/components/common';
import type { OperatorFeature } from '@/types';
import common from '../../CommonPropertiesPanel.module.scss';

// ── Hidden fields ─────────────────────────────────────────────────────────────
// Fields that are intentionally suppressed from the provider form because they
// are already covered by a dedicated top-level operator attribute.
const HIDDEN_FIELDS = new Set([
  'file_extensions',
]);

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ProviderFieldsFormProps {
  /** Property definitions from `provider_config.providers[provider].properties`. */
  properties: Record<string, OperatorFeature>;
  /** Current field values keyed by property key. */
  values: Record<string, unknown>;
  /**
   * Called when the user changes a field.
   * Parent component decides how to persist the value.
   */
  onChange: (fieldKey: string, value: unknown) => void;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function asString(v: unknown): string {
  if (v === undefined || v === null) {return '';}
  return String(v);
}

function asNumber(v: unknown): number | string {
  if (v === undefined || v === null) {return '';}
  const n = Number(v);
  return Number.isFinite(n) ? n : '';
}

function asBoolean(v: unknown, defaultValue = false): boolean {
  if (typeof v === 'boolean') {return v;}
  return defaultValue;
}

function asStringArray(v: unknown): string[] {
  if (Array.isArray(v)) {return v.map(String);}
  if (typeof v === 'string' && v.trim()) {
    return v.split(',').map((s) => s.trim()).filter(Boolean);
  }
  return [];
}

function buildRangeText(minValue?: number, maxValue?: number): string | undefined {
  if (minValue !== undefined && maxValue !== undefined) {
    return `Range allowed: ${minValue}–${maxValue}`;
  }
  if (minValue !== undefined) {return `Minimum value allowed: ${minValue}`;}
  if (maxValue !== undefined) {return `Maximum value allowed: ${maxValue}`;}
  return undefined;
}

function isOutOfRange(value: number | string, minValue?: number, maxValue?: number): boolean {
  if (value === '') {return false;}
  const n = Number(value);
  if (!Number.isFinite(n)) {return false;}
  if (minValue !== undefined && n < minValue) {return true;}
  if (maxValue !== undefined && n > maxValue) {return true;}
  return false;
}

// ── NullableNumberInput ───────────────────────────────────────────────────────
// Used for int64/double fields whose backend type is `int | None`.
// A toggle controls whether the field is set (on) or null/no-limit (off).

interface NullableNumberInputProps {
  id: string;
  label: string;
  value: number | null | undefined;
  minValue?: number;
  maxValue?: number;
  onChange: (value: number | null) => void;
}

function NullableNumberInput({
  id,
  label,
  value,
  minValue,
  maxValue,
  onChange,
}: NullableNumberInputProps): React.JSX.Element {
  const isEnabled = value !== null && value !== undefined;
  const [draft, setDraft] = useState<number | string>(isEnabled ? value : '');

  useEffect(() => {
    setDraft(isEnabled ? value : '');
  }, [isEnabled, value]);

  const outOfRange = isOutOfRange(draft, minValue, maxValue);

  const rangeText = buildRangeText(minValue, maxValue);

  function handleToggle(checked: boolean): void {
    if (checked) {
      const initial = minValue ?? 1;
      setDraft(initial);
      onChange(initial);
    } else {
      setDraft('');
      onChange(null);
    }
  }

  function handleNumberChange(_e: unknown, { value: v }: { value: number | string }): void {
    setDraft(v);
    if (v === '' || v === undefined) {
      onChange(null);
      return;
    }
    const n = Number(v);
    if (Number.isFinite(n)) {
      onChange(n);
    }
  }

  return (
    <div className={common.nullableNumberInputWrapper}>
      <Toggle
        id={`${id}-toggle`}
        labelA="No limit"
        labelB="Set limit"
        toggled={isEnabled}
        onToggle={handleToggle}
      />
      {isEnabled && (
        <NumberInput
          id={id}
          label={label}
          hideLabel
          value={draft}
          {...(minValue !== undefined && { min: minValue })}
          {...(maxValue !== undefined && { max: maxValue })}
          helperText={!outOfRange ? rangeText : undefined}
          invalid={outOfRange}
          invalidText={outOfRange ? rangeText : undefined}
          onChange={handleNumberChange}
        />
      )}
    </div>
  );
}

// ── ProviderFieldsForm ────────────────────────────────────────────────────────

/**
 * Renders one Carbon input per property defined in the provider schema.
 * Ordering follows the natural order of the `properties` object.
 */
export function ProviderFieldsForm({
  properties,
  values,
  onChange,
}: ProviderFieldsFormProps): React.JSX.Element {
  return (
    <>
      {Object.entries(properties).map(([fieldKey, keyInfo]: [string, OperatorFeature]) => {
        if (HIDDEN_FIELDS.has(fieldKey)) {return null;}
        const label = keyInfo.name ?? fieldKey;
        const description = keyInfo.description ?? '';
        const isRequired = keyInfo.required === true;
        const labelText = isRequired ? `${label} (required)` : label;
        const inputId = `provider-field-${fieldKey}`;

        // VaultInput owns its own header row.
        const isSensitive = keyInfo.type === 'string' && keyInfo.sensitive === true;

        if (isSensitive) {
          return (
            <div key={fieldKey} className={common.formField}>
              <VaultInput
                id={inputId}
                labelText={labelText}
                labelComponent={
                  <DefinitionTooltip
                    definition={description}
                    openOnHover
                    align="right"
                  >
                    {labelText}
                  </DefinitionTooltip>
                }
                value={asString(values[fieldKey])}
                onChange={(v: string) => {onChange(fieldKey, v);}}
              />
            </div>
          );
        }

        const isNumeric = keyInfo.type === 'int64' || keyInfo.type === 'double';
        const isNullable = isNumeric && keyInfo.default === null;
        const currentNum = asNumber(values[fieldKey]);
        const numOutOfRange = currentNum !== '' && isOutOfRange(currentNum, keyInfo.min_value, keyInfo.max_value);
        const numRangeText = buildRangeText(keyInfo.min_value, keyInfo.max_value);

        return (
          <div key={fieldKey} className={common.formField}>
            <div className={common.labelWithTooltip}>
              <DefinitionTooltip
                definition={description}
                openOnHover
                align="right"
              >
                {labelText}
              </DefinitionTooltip>
            </div>

            {/* boolean → Toggle */}
            {keyInfo.type === 'boolean' && (
              <Toggle
                id={inputId}
                labelText={label}
                hideLabel
                labelA="Off"
                labelB="On"
                toggled={asBoolean(values[fieldKey], keyInfo.default as boolean | undefined ?? false)}
                onToggle={(checked: boolean) => {onChange(fieldKey, checked);}}
              />
            )}

            {/* int64 / double, nullable (default: null) → NullableNumberInput */}
            {isNullable && (
              <NullableNumberInput
                id={inputId}
                label={label}
                value={values[fieldKey] as number | null | undefined}
                minValue={keyInfo.min_value}
                maxValue={keyInfo.max_value}
                onChange={(v) => {onChange(fieldKey, v);}}
              />
            )}

            {/* int64 / double, non-null default → NumberInput */}
            {isNumeric && !isNullable && (
              <NumberInput
                id={inputId}
                label={label}
                hideLabel
                value={currentNum !== '' ? currentNum : keyInfo.default as number | undefined}
                {...(keyInfo.min_value !== undefined && { min: keyInfo.min_value })}
                {...(keyInfo.max_value !== undefined && { max: keyInfo.max_value })}
                helperText={!numOutOfRange ? numRangeText : undefined}
                invalid={numOutOfRange}
                invalidText={numOutOfRange ? numRangeText : undefined}
                onChange={(_e: unknown, { value }: { value: number | string }) => {
                  onChange(fieldKey, value === '' ? undefined : Number(value));
                }}
              />
            )}

            {/* list → ListInput (explicit Add button; never commits on blur) */}
            {keyInfo.type === 'list' && (
              <ListInput
                id={inputId}
                labelText={label}
                tableTitle={`Added ${label.toLowerCase()}`}
                items={asStringArray(values[fieldKey])}
                placeholder={`Enter ${label.toLowerCase()}`}
                helperText="Type a value and press Enter, comma, or click Add to add it."
                onChange={(items: string[]) => {onChange(fieldKey, items);}}
              />
            )}

            {/* json → JsonTextArea */}
            {keyInfo.type === 'json' && (
              <JsonTextArea
                id={inputId}
                labelText={label}
                rows={3}
                storedValue={typeof values[fieldKey] === 'object' && values[fieldKey] !== null
                  ? values[fieldKey] as Record<string, unknown>
                  : null}
                onChange={(value) => {onChange(fieldKey, value ?? undefined);}}
              />
            )}

            {/* string non-sensitive → TextInput */}
            {keyInfo.type === 'string' && keyInfo.sensitive !== true && (
              <TextInput
                id={inputId}
                labelText={label}
                hideLabel
                value={asString(values[fieldKey])}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                  onChange(fieldKey, e.target.value);
                }}
              />
            )}
          </div>
        );
      })}
    </>
  );
}
