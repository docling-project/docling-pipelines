/**
 * @file PiiAndHap.tsx
 *
 * Configuration panel body for the `pii_and_hap` operator node.
 *
 * **Parameters** (from PIIAndHAPAnnotator.get_metadata()["attributes"]):
 * - `expected_redactions`     — list; which targets to redact: ["PII", "HAP"]
 * - `pii_list`                — list; which PII entity types to detect
 * - `display_pii`             — boolean; include PII values in output columns
 * - `redaction`               — boolean (required); enable PII redaction
 * - `redaction_character`     — string; mask character for PII
 * - `hap_redaction`           — boolean (required); enable HAP redaction
 * - `hap_redaction_character` — string; mask character for HAP
 * - `pii_threshold`           — sfloat; confidence threshold for PII (0.0–1.0)
 * - `hap_threshold`           — sfloat; confidence threshold for HAP (0.0–1.0)
 * - `provider`                — string; LLM provider (litellm, watsonx)
 * - `provider_config`         — json; provider-specific configuration
 *
 * **Conditional rendering**:
 * - `showPII` — true when "PII" is in `expected_redactions`.
 *   Shows: `pii_list`, `redaction` toggle, `redaction_character`, `pii_threshold`, `display_pii`.
 * - `showHAP` — true when "HAP" is in `expected_redactions`.
 *   Shows: `hap_redaction` toggle, `hap_redaction_character`, `hap_threshold`.
 * - `provider` and `provider_config` are always visible.
 *
 * **Data flow**:
 * 1. `controller.getAppData().operatorMetadata` — backend attribute metadata
 * 2. `controller.getPropertyValue({ name })` — reads saved node parameter
 * 3. `controller.updatePropertyValue({ name }, value)` — writes on change
 */

import React, { useMemo, useState } from 'react';
import { useIntl } from 'react-intl';
import { getRequiredParamValidator } from '@/utils/requiredParamValidation';
import { RequiredParamTooltip } from '@/components/common';
import { JsonTextArea } from '@/components/common/JsonTextArea/JsonTextArea';
import { ProviderFieldsForm } from '../shared/ProviderFieldsForm';
import {
  Accordion,
  AccordionItem,
  DefinitionTooltip,
  Dropdown,
  FilterableMultiSelect,
  NumberInput,
  TextInput,
  Toggle,
} from '@carbon/react';
import type { OperatorFeature, OperatorMetadata } from '@/types';
import { NodeOperator } from '@/constants/operators';
import {
  PII_AND_HAP_ATTRIBUTE as ATTR,
  EXPECTED_REDACTIONS_OPTIONS,
  PII_LIST_OPTIONS,
} from './constants';
import { messages } from './PiiAndHap.messages';
import common from '../../CommonPropertiesPanel.module.scss';
import { useProviderConfigDefaults } from '@/hooks/useProviderConfigDefaults';

interface PiiAndHapPanelBodyProps {
  controller: any;
}

/* eslint-disable @typescript-eslint/no-unsafe-call, @typescript-eslint/no-unsafe-member-access */
export function PiiAndHapPanelBody({ controller }: PiiAndHapPanelBodyProps): React.JSX.Element {
  const intl = useIntl();
  // ── Read operator attribute metadata from Redux (passed via Canvas.tsx) ──
  const operatorMetadata = (controller?.getAppData?.()?.operatorMetadata ?? {}) as Record<string, OperatorMetadata>;
  const nodeAttributes: Record<string, OperatorFeature> = operatorMetadata[NodeOperator.PII_AND_HAP]?.attributes ?? {};

  // ── Provider-specific field schema from provider_config metadata ──
  const providerConfigAttr = nodeAttributes[ATTR.PROVIDER_CONFIG];
  const providerSchemas = providerConfigAttr?.providers ?? {};

  // ── Read current saved values, falling back to backend defaults ────────

  // expected_redactions — may arrive as an array (from applyNodeDefaults) or
  // as a comma-separated string (from a previous updatePropertyValue call).
  const expectedRedactionsRaw = controller?.getPropertyValue?.({ name: ATTR.EXPECTED_REDACTIONS }) as
    | string[]
    | string
    | undefined;

  const selectedExpectedRedactions: string[] = useMemo(() => {
    if (Array.isArray(expectedRedactionsRaw)) { return expectedRedactionsRaw; }
    if (typeof expectedRedactionsRaw === 'string' && expectedRedactionsRaw.length > 0) {
      return expectedRedactionsRaw.split(',').map((s: string) => s.trim()).filter(Boolean);
    }
    const metaDefault = nodeAttributes[ATTR.EXPECTED_REDACTIONS]?.default;
    if (Array.isArray(metaDefault)) { return metaDefault as string[]; }
    return ['PII', 'HAP'];
  }, [
    Array.isArray(expectedRedactionsRaw) ? expectedRedactionsRaw.join(',') : (expectedRedactionsRaw ?? ''),
    nodeAttributes,
  ]);

  // pii_list — may arrive as an array (from applyNodeDefaults) or as a string.
  const piiListRaw = controller?.getPropertyValue?.({ name: ATTR.PII_LIST }) as
    | string[]
    | string
    | undefined;

  const selectedPiiList: string[] = useMemo(() => {
    if (Array.isArray(piiListRaw)) { return piiListRaw; }
    if (typeof piiListRaw === 'string' && piiListRaw.length > 0) {
      return piiListRaw.split(',').map((s: string) => s.trim()).filter(Boolean);
    }
    const metaDefault = nodeAttributes[ATTR.PII_LIST]?.default;
    if (Array.isArray(metaDefault)) { return metaDefault as string[]; }
    return [...PII_LIST_OPTIONS];
  }, [
    Array.isArray(piiListRaw) ? piiListRaw.join(',') : (piiListRaw ?? ''),
    nodeAttributes,
  ]);

  const displayPii: boolean =
    (controller?.getPropertyValue?.({ name: ATTR.DISPLAY_PII }) as boolean | undefined)
    ?? (nodeAttributes[ATTR.DISPLAY_PII]?.default as boolean | undefined)
    ?? false;

  const redaction: boolean =
    (controller?.getPropertyValue?.({ name: ATTR.REDACTION }) as boolean | undefined)
    ?? (nodeAttributes[ATTR.REDACTION]?.default as boolean | undefined)
    ?? false;

  const redactionCharacter: string =
    (controller?.getPropertyValue?.({ name: ATTR.REDACTION_CHARACTER }) as string | undefined)
    ?? (nodeAttributes[ATTR.REDACTION_CHARACTER]?.default as string | undefined)
    ?? '*';

  const hapRedaction: boolean =
    (controller?.getPropertyValue?.({ name: ATTR.HAP_REDACTION }) as boolean | undefined)
    ?? (nodeAttributes[ATTR.HAP_REDACTION]?.default as boolean | undefined)
    ?? false;

  const hapRedactionCharacter: string =
    (controller?.getPropertyValue?.({ name: ATTR.HAP_REDACTION_CHARACTER }) as string | undefined)
    ?? (nodeAttributes[ATTR.HAP_REDACTION_CHARACTER]?.default as string | undefined)
    ?? '*';

  const piiThreshold: number =
    (controller?.getPropertyValue?.({ name: ATTR.PII_THRESHOLD }) as number | undefined)
    ?? (nodeAttributes[ATTR.PII_THRESHOLD]?.default as number | undefined)
    ?? 0.5;

  const hapThreshold: number =
    (controller?.getPropertyValue?.({ name: ATTR.HAP_THRESHOLD }) as number | undefined)
    ?? (nodeAttributes[ATTR.HAP_THRESHOLD]?.default as number | undefined)
    ?? 0.8;

  const provider: string | undefined =
    (controller?.getPropertyValue?.({ name: ATTR.PROVIDER }) as string | undefined)
    ?? (nodeAttributes[ATTR.PROVIDER]?.default as string | undefined);

  const providerConfigRaw = controller?.getPropertyValue?.({ name: ATTR.PROVIDER_CONFIG }) as
    | Record<string, unknown>
    | null
    | undefined;

  // ── Per-provider structured field state ──
  const [providerFieldValues, setProviderFieldValues] = useState<Record<string, unknown>>(
    (typeof providerConfigRaw === 'object' && providerConfigRaw !== null)
      ? providerConfigRaw
      : {}
  );

  // Provider dropdown options sourced exclusively from operator metadata valid_values.
  // No hardcoded fallback — the Dropdown renders an empty list until metadata loads.
  const providerValidValues = (nodeAttributes[ATTR.PROVIDER] as Record<string, unknown> | undefined)?.valid_values;
  const providerItems: string[] = Array.isArray(providerValidValues) ? (providerValidValues as string[]) : [];

  useProviderConfigDefaults(controller, nodeAttributes);

  // ── Required param validation ─────────────────────────────────────────────
  const validate = getRequiredParamValidator(nodeAttributes);
  const expectedRedactionsValidation = validate(ATTR.EXPECTED_REDACTIONS, selectedExpectedRedactions);
  const piiListValidation = validate(ATTR.PII_LIST, selectedPiiList);
  const redactionCharacterValidation = validate(ATTR.REDACTION_CHARACTER, redactionCharacter);
  const piiThresholdValidation = validate(ATTR.PII_THRESHOLD, piiThreshold);
  const hapRedactionCharacterValidation = validate(ATTR.HAP_REDACTION_CHARACTER, hapRedactionCharacter);
  const hapThresholdValidation = validate(ATTR.HAP_THRESHOLD, hapThreshold);
  const providerValidation = validate(ATTR.PROVIDER, provider);
  const providerConfigValidation = validate(ATTR.PROVIDER_CONFIG, providerConfigRaw ?? null);

  // ── Conditional section visibility ────────────────────────────────────
  // PII-specific fields are only shown when "PII" is in expected_redactions.
  // HAP-specific fields are only shown when "HAP" is in expected_redactions.
  const showPII = selectedExpectedRedactions.includes('PII');
  const showHAP = selectedExpectedRedactions.includes('HAP');

  return (
    <div className={common.commonPropertiesPanelBody}>

      {/* ── Redaction targets — always visible ───────────────────────── */}
      <div className={common.formField}>
        <div className={common.labelWithTooltip}>
          <RequiredParamTooltip
            paramId={ATTR.EXPECTED_REDACTIONS}
            nodeAttributes={nodeAttributes}
            definition={nodeAttributes[ATTR.EXPECTED_REDACTIONS]?.description
              ?? intl.formatMessage(messages.expectedRedactionsDescription)}
          >
            {intl.formatMessage(messages.expectedRedactions)}
          </RequiredParamTooltip>
        </div>
        <FilterableMultiSelect
          key={selectedExpectedRedactions.join(',')}
          id="expected_redactions"
          titleText={intl.formatMessage(messages.expectedRedactions)}
          hideLabel
          placeholder={intl.formatMessage(messages.expectedRedactionsPlaceholder)}
          items={[...EXPECTED_REDACTIONS_OPTIONS]}
          itemToString={(item: string | null) => item ?? ''}
          initialSelectedItems={selectedExpectedRedactions}
          onChange={({ selectedItems }: { selectedItems: string[] }) => {
            controller?.updatePropertyValue?.({ name: ATTR.EXPECTED_REDACTIONS }, selectedItems);
          }}
          invalid={expectedRedactionsValidation.isInvalid}
          invalidText={expectedRedactionsValidation.errorMessage}
        />
      </div>

      {/* ── PII section — only when "PII" is selected ────────────────── */}
      {showPII && (
        <>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={ATTR.PII_LIST}
                nodeAttributes={nodeAttributes}
                definition={nodeAttributes[ATTR.PII_LIST]?.description
                  ?? intl.formatMessage(messages.piiListDescription)}
              >
                {intl.formatMessage(messages.piiList)}
              </RequiredParamTooltip>
            </div>
            <FilterableMultiSelect
              key={selectedPiiList.join(',')}
              id="pii_list"
              titleText={intl.formatMessage(messages.piiList)}
              hideLabel
              placeholder={intl.formatMessage(messages.piiListPlaceholder)}
              items={[...PII_LIST_OPTIONS]}
              itemToString={(item: string | null) => item ?? ''}
              initialSelectedItems={selectedPiiList}
              onChange={({ selectedItems }: { selectedItems: string[] }) => {
                controller?.updatePropertyValue?.({ name: ATTR.PII_LIST }, selectedItems);
              }}
              invalid={piiListValidation.isInvalid}
              invalidText={piiListValidation.errorMessage}
            />
          </div>

          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <DefinitionTooltip
                definition={nodeAttributes[ATTR.REDACTION]?.description
                  ?? intl.formatMessage(messages.redactionDescription)}
                openOnHover
                align="right"
              >
                {intl.formatMessage(messages.redaction)}
              </DefinitionTooltip>
            </div>
            <Toggle
              id="redaction"
              labelText={intl.formatMessage(messages.redaction)}
              hideLabel
              labelA={intl.formatMessage(messages.off)}
              labelB={intl.formatMessage(messages.on)}
              toggled={redaction}
              onToggle={(checked: boolean) => {
                controller?.updatePropertyValue?.({ name: ATTR.REDACTION }, checked);
              }}
            />
          </div>

          {redaction && (
            <div className={common.formField}>
              <div className={common.labelWithTooltip}>
                <RequiredParamTooltip
                  paramId={ATTR.REDACTION_CHARACTER}
                  nodeAttributes={nodeAttributes}
                  definition={nodeAttributes[ATTR.REDACTION_CHARACTER]?.description
                    ?? intl.formatMessage(messages.redactionCharacterDescription)}
                >
                  {intl.formatMessage(messages.redactionCharacter)}
                </RequiredParamTooltip>
              </div>
              <TextInput
                id="redaction_character"
                labelText={intl.formatMessage(messages.redactionCharacter)}
                hideLabel
                placeholder="*"
                maxLength={1}
                value={redactionCharacter}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                  controller?.updatePropertyValue?.({ name: ATTR.REDACTION_CHARACTER }, e.target.value);
                }}
                invalid={redactionCharacterValidation.isInvalid}
                invalidText={redactionCharacterValidation.errorMessage}
              />
            </div>
          )}

          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={ATTR.PII_THRESHOLD}
                nodeAttributes={nodeAttributes}
                definition={nodeAttributes[ATTR.PII_THRESHOLD]?.description
                  ?? intl.formatMessage(messages.piiThresholdDescription)}
              >
                {intl.formatMessage(messages.piiThreshold)}
              </RequiredParamTooltip>
            </div>
            <NumberInput
              id="pii_threshold"
              label={intl.formatMessage(messages.piiThreshold)}
              hideLabel
              value={piiThreshold}
              min={0}
              max={1}
              step={0.05}
              onChange={(_e: unknown, { value }: { value: number | string }) => {
                controller?.updatePropertyValue?.({ name: ATTR.PII_THRESHOLD }, Number(value));
              }}
              invalid={piiThresholdValidation.isInvalid}
              invalidText={piiThresholdValidation.errorMessage}
            />
          </div>

          {/* ── Display PII toggle — only relevant when PII is selected ── */}
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <DefinitionTooltip
                definition={nodeAttributes[ATTR.DISPLAY_PII]?.description
                  ?? intl.formatMessage(messages.displayPiiDescription)}
                openOnHover
                align="right"
              >
                {intl.formatMessage(messages.displayPii)}
              </DefinitionTooltip>
            </div>
            <Toggle
              id="display_pii"
              labelText={intl.formatMessage(messages.displayPii)}
              hideLabel
              labelA={intl.formatMessage(messages.off)}
              labelB={intl.formatMessage(messages.on)}
              toggled={displayPii}
              onToggle={(checked: boolean) => {
                controller?.updatePropertyValue?.({ name: ATTR.DISPLAY_PII }, checked);
              }}
            />
          </div>
        </>
      )}

      {/* ── HAP section — only when "HAP" is selected ────────────────── */}
      {showHAP && (
        <>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <DefinitionTooltip
                definition={nodeAttributes[ATTR.HAP_REDACTION]?.description
                  ?? intl.formatMessage(messages.hapRedactionDescription)}
                openOnHover
                align="right"
              >
                {intl.formatMessage(messages.hapRedaction)}
              </DefinitionTooltip>
            </div>
            <Toggle
              id="hap_redaction"
              labelText={intl.formatMessage(messages.hapRedaction)}
              hideLabel
              labelA={intl.formatMessage(messages.off)}
              labelB={intl.formatMessage(messages.on)}
              toggled={hapRedaction}
              onToggle={(checked: boolean) => {
                controller?.updatePropertyValue?.({ name: ATTR.HAP_REDACTION }, checked);
              }}
            />
          </div>

          {hapRedaction && (
            <div className={common.formField}>
              <div className={common.labelWithTooltip}>
                <RequiredParamTooltip
                  paramId={ATTR.HAP_REDACTION_CHARACTER}
                  nodeAttributes={nodeAttributes}
                  definition={nodeAttributes[ATTR.HAP_REDACTION_CHARACTER]?.description
                    ?? intl.formatMessage(messages.hapRedactionCharacterDescription)}
                >
                  {intl.formatMessage(messages.hapRedactionCharacter)}
                </RequiredParamTooltip>
              </div>
              <TextInput
                id="hap_redaction_character"
                labelText={intl.formatMessage(messages.hapRedactionCharacter)}
                hideLabel
                placeholder="*"
                maxLength={1}
                value={hapRedactionCharacter}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                  controller?.updatePropertyValue?.({ name: ATTR.HAP_REDACTION_CHARACTER }, e.target.value);
                }}
                invalid={hapRedactionCharacterValidation.isInvalid}
                invalidText={hapRedactionCharacterValidation.errorMessage}
              />
            </div>
          )}

          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={ATTR.HAP_THRESHOLD}
                nodeAttributes={nodeAttributes}
                definition={nodeAttributes[ATTR.HAP_THRESHOLD]?.description
                  ?? intl.formatMessage(messages.hapThresholdDescription)}
              >
                {intl.formatMessage(messages.hapThreshold)}
              </RequiredParamTooltip>
            </div>
            <NumberInput
              id="hap_threshold"
              label={intl.formatMessage(messages.hapThreshold)}
              hideLabel
              value={hapThreshold}
              min={0}
              max={1}
              step={0.05}
              onChange={(_e: unknown, { value }: { value: number | string }) => {
                controller?.updatePropertyValue?.({ name: ATTR.HAP_THRESHOLD }, Number(value));
              }}
              invalid={hapThresholdValidation.isInvalid}
              invalidText={hapThresholdValidation.errorMessage}
            />
          </div>
        </>
      )}

      {/* ── Provider dropdown always visible ───────────────────────── */}
      <div className={common.formField}>
        <div className={common.labelWithTooltip}>
          <RequiredParamTooltip
            paramId={ATTR.PROVIDER}
            nodeAttributes={nodeAttributes}
            definition={nodeAttributes[ATTR.PROVIDER]?.description
              ?? intl.formatMessage(messages.providerDescription)}
          >
            {intl.formatMessage(messages.provider)}
          </RequiredParamTooltip>
        </div>
        <Dropdown
          id="provider"
          titleText={intl.formatMessage(messages.provider)}
          hideLabel
          label={intl.formatMessage(messages.selectProvider)}
          items={providerItems}
          selectedItem={provider ?? null}
          onChange={({ selectedItem }: { selectedItem: string | null }) => {
            if (selectedItem) {
              controller?.updatePropertyValue?.({ name: ATTR.PROVIDER }, selectedItem);
              controller?.updatePropertyValue?.({ name: ATTR.PROVIDER_CONFIG }, null);
              setProviderFieldValues({});
            }
          }}
          invalid={providerValidation.isInvalid}
          invalidText={providerValidation.errorMessage}
        />
      </div>

      {/* ── Provider configuration accordion ─────────────────────────── */}
      <Accordion align="start">
        <AccordionItem title={intl.formatMessage(messages.providerConfigAccordion)}>
          <div className={common.accordionContent}>

            <p className={common.accordionDescription}>
              {intl.formatMessage(messages.providerConfigAccordionDescription)}
            </p>

            {provider && (
              <div className={common.subSection}>
                {providerSchemas[provider]?.properties && (
                  <ProviderFieldsForm
                    properties={providerSchemas[provider].properties}
                    values={providerFieldValues}
                    onChange={(fieldKey, value) => {
                      const updated = { ...providerFieldValues, [fieldKey]: value };
                      setProviderFieldValues(updated);
                      controller?.updatePropertyValue?.({ name: ATTR.PROVIDER_CONFIG }, updated);
                    }}
                  />
                )}

                {!providerSchemas[provider]?.properties && (
                  <div className={common.formField}>
                    <div className={common.labelWithTooltip}>
                      <RequiredParamTooltip
                        paramId={ATTR.PROVIDER_CONFIG}
                        nodeAttributes={nodeAttributes}
                        definition={nodeAttributes[ATTR.PROVIDER_CONFIG]?.description
                          ?? intl.formatMessage(messages.providerConfigDescription)}
                      >
                        {intl.formatMessage(messages.providerConfig)}
                      </RequiredParamTooltip>
                    </div>
                    <JsonTextArea
                      id="provider_config"
                      labelText={intl.formatMessage(messages.providerConfig)}
                      placeholder='{"model": "ollama/mistral", "api_base": "http://localhost:11434/v1"}'
                      storedValue={providerConfigRaw ?? null}
                      rows={3}
                      invalid={providerConfigValidation.isInvalid}
                      invalidText={providerConfigValidation.errorMessage}
                      onChange={(value) => {
                        controller?.updatePropertyValue?.({ name: ATTR.PROVIDER_CONFIG }, value);
                      }}
                    />
                  </div>
                )}
              </div>
            )}

          </div>
        </AccordionItem>
      </Accordion>

    </div>
  );
}
