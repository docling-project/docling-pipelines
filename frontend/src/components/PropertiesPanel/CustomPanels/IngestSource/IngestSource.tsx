/**
 * @file IngestSource properties panel body.
 *
 * Renders the configuration UI for the `ingest_source` operator node.
 *
 * **Data flow**:
 * - `controller.getAppData().operatorMetadata` — backend attribute metadata (descriptions, defaults)
 * - `controller.getPropertyValue({ name })` — reads saved node parameter
 * - `controller.updatePropertyValue({ name }, value)` — writes node parameter on change
 */

import React, { useMemo, useState } from 'react';
import {
  Accordion,
  AccordionItem,
  Dropdown,
  FilterableMultiSelect,
  NumberInput,
  Toggle,
} from '@carbon/react';
import { useIntl, type MessageDescriptor } from 'react-intl';
import type { OperatorFeature, OperatorMetadata } from '@/types';
import { NodeOperator } from '@/constants/operators';
import {
  CUSTOM_PROVIDER,
  INGEST_SOURCE_ATTRIBUTE as ATTR,
  PROVIDER_BRAND_LABELS,
  SUPPORTED_FILE_EXTENSIONS,
} from './constants';
import { messages } from './IngestSource.messages';
import { ProviderFieldsForm } from '../shared/ProviderFieldsForm';
import { JsonTextArea } from '@/components/common/JsonTextArea/JsonTextArea';
import common from '../../CommonPropertiesPanel.module.scss';
import { getRequiredParamValidator } from '@/utils/requiredParamValidation';
import { RequiredParamTooltip } from '@/components/common';
import { useProviderConfigDefaults } from '@/hooks/useProviderConfigDefaults';

/** Maps generic (non-brand) backend provider keys to translated display labels. */
const PROVIDER_LABEL_MESSAGES: Record<string, MessageDescriptor> = {
  filesystem: messages.providerLabelFilesystem,
  web: messages.providerLabelWeb,
  custom: messages.providerLabelCustom,
};

/** Maps backend provider keys to translated descriptions shown under Provider configuration. */
const PROVIDER_DESCRIPTION_MESSAGES: Record<string, MessageDescriptor> = {
  s3: messages.providerDescriptionS3,
  ibm_cos: messages.providerDescriptionIbmCos,
  sharepoint: messages.providerDescriptionSharepoint,
  onedrive: messages.providerDescriptionOnedrive,
  google_drive: messages.providerDescriptionGoogleDrive,
  box_driver: messages.providerDescriptionBoxDriver,
  filesystem: messages.providerDescriptionFilesystem,
  web: messages.providerDescriptionWeb,
  custom: messages.providerDescriptionCustom,
};

interface IngestSourcePanelBodyProps {
  controller: any;
}

/**
 * Normalizes filter extensions from string or array to an array of extension names.
 */
function normalizeFilterExtensions(raw: unknown): string[] {
  if (Array.isArray(raw)) {
    return raw.map((item) => String(item).trim().replace(/^\./, '')).filter(Boolean);
  }
  if (typeof raw === 'string' && raw.trim() !== '') {
    return raw
      .split(',')
      .map((item) => item.trim().replace(/^\./, ''))
      .filter(Boolean);
  }
  return [];
}

/* eslint-disable @typescript-eslint/no-unsafe-call, @typescript-eslint/no-unsafe-member-access */
export function IngestSourcePanelBody({
  controller,
}: IngestSourcePanelBodyProps): React.JSX.Element {
  const intl = useIntl();

  // ── Read operator attribute metadata ──
  const operatorMetadata = (controller?.getAppData?.()?.operatorMetadata ?? {}) as Record<string, OperatorMetadata>;
  const nodeAttributes: Record<string, OperatorFeature> = operatorMetadata[NodeOperator.INGEST_SOURCE]?.attributes ?? {};

  // ── Provider dropdown: items come from operator metadata ──
  const providerValidValues = (nodeAttributes[ATTR.PROVIDER] as Record<string, unknown> | undefined)?.valid_values;
  const providerItems: string[] = Array.isArray(providerValidValues) ? (providerValidValues as string[]) : [];

  // ── Provider-specific field schema from provider_config metadata ──
  const providerConfigAttr = nodeAttributes[ATTR.PROVIDER_CONFIG];
  const providerSchemas = providerConfigAttr?.providers ?? {};

  // ── Read current saved values, falling back to backend defaults ──────────

  const provider = (controller?.getPropertyValue?.({ name: ATTR.PROVIDER }) as string | undefined)
    ?? (nodeAttributes[ATTR.PROVIDER]?.default as string | undefined)
    ?? '';

  const providerConfigRaw = controller?.getPropertyValue?.({ name: ATTR.PROVIDER_CONFIG });

  const maxFiles = (controller?.getPropertyValue?.({ name: ATTR.MAX_FILES }) as number | undefined)
    ?? (nodeAttributes[ATTR.MAX_FILES]?.default as number | undefined)
    ?? 100;

  const includeFilterRaw = controller?.getPropertyValue?.({ name: ATTR.INCLUDE_FILTER })
    ?? nodeAttributes[ATTR.INCLUDE_FILTER]?.default;
  const selectedIncludeFilter = useMemo(
    () => normalizeFilterExtensions(includeFilterRaw),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [JSON.stringify(includeFilterRaw)]
  );

  const excludeFilterRaw = controller?.getPropertyValue?.({ name: ATTR.EXCLUDE_FILTER })
    ?? nodeAttributes[ATTR.EXCLUDE_FILTER]?.default;
  const selectedExcludeFilter = useMemo(
    () => normalizeFilterExtensions(excludeFilterRaw),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [JSON.stringify(excludeFilterRaw)]
  );

  const ignoreHiddenFiles = (controller?.getPropertyValue?.({ name: ATTR.IGNORE_HIDDEN_FILES }) as boolean | undefined)
    ?? (nodeAttributes[ATTR.IGNORE_HIDDEN_FILES]?.default as boolean | undefined)
    ?? true;

  // ── Per-provider structured field state ──
  // Holds the in-progress field values when a provider schema is available.
  // Initialised from the persisted provider_config object on first render.
  const [providerFieldValues, setProviderFieldValues] = useState<Record<string, unknown>>(
    (typeof providerConfigRaw === 'object' && providerConfigRaw !== null)
      ? providerConfigRaw as Record<string, unknown>
      : {}
  );

  useProviderConfigDefaults(controller, nodeAttributes);

  // ── Required field validator ──────────────────────────────────────────────
  const validate = getRequiredParamValidator(nodeAttributes);
  const providerValidation = validate(ATTR.PROVIDER, provider || undefined);
  const providerConfigValidation = validate(
    ATTR.PROVIDER_CONFIG,
    providerConfigRaw ?? null
  );
  const maxFilesValidation = validate(ATTR.MAX_FILES, maxFiles);
  const includeFilterValidation = validate(
    ATTR.INCLUDE_FILTER,
    selectedIncludeFilter.length > 0 ? selectedIncludeFilter : undefined
  );
  const excludeFilterValidation = validate(
    ATTR.EXCLUDE_FILTER,
    selectedExcludeFilter.length > 0 ? selectedExcludeFilter : undefined
  );

  // ── Include/exclude conflict detection ───────────────────────────────────
  const conflictingExtensions = useMemo(
    () => selectedIncludeFilter.filter((ext) => selectedExcludeFilter.includes(ext)),
    [selectedIncludeFilter, selectedExcludeFilter]
  );
  const filterConflictWarning = conflictingExtensions.length > 0
    ? intl.formatMessage(messages.filterConflict, {
      extensions: intl.formatList(
        conflictingExtensions.map((extension) => intl.formatMessage(
          messages.filterConflictExtension,
          { extension }
        ))
      ),
      count: conflictingExtensions.length,
    })
    : null;

  return (
    <div className={common.commonPropertiesPanelBody}>

      {/* ── Provider ───────────────────────────────────────────────── */}
      <div className={common.formField}>
        <div className={common.labelWithTooltip}>
          <RequiredParamTooltip
            paramId={ATTR.PROVIDER}
            nodeAttributes={nodeAttributes}
            definition={nodeAttributes[ATTR.PROVIDER]?.description ?? ''}
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
          selectedItem={provider || null}
          itemToString={(item: string | null) => {
            if (!item) { return ''; }
            const descriptor = PROVIDER_LABEL_MESSAGES[item];
            return descriptor ? intl.formatMessage(descriptor) : (PROVIDER_BRAND_LABELS[item] ?? item);
          }}
          invalid={providerValidation.isInvalid}
          invalidText={providerValidation.errorMessage}
          onChange={({ selectedItem }: { selectedItem: string | null }) => {
              if (selectedItem) {
                controller?.updatePropertyValue?.({ name: ATTR.PROVIDER }, selectedItem);
                controller?.updatePropertyValue?.({ name: ATTR.PROVIDER_CONFIG }, null);
                setProviderFieldValues({});
              }
            }}
        />
      </div>

      {/* ── Provider-dependent fields hidden until a provider is selected ── */}
      {provider && (
        <Accordion align="start" className={common.fullWidthAccordion}>

          {/* ── Provider configuration ──────────────────────────────── */}
          <AccordionItem title={intl.formatMessage(messages.providerConfig)} open>
            <div className={common.accordionContent}>

              {PROVIDER_DESCRIPTION_MESSAGES[provider] && (
                <p className={common.accordionDescription}>
                  {intl.formatMessage(PROVIDER_DESCRIPTION_MESSAGES[provider])}
                </p>
              )}

              {/* Per-provider structured fields */}
              {provider !== CUSTOM_PROVIDER && providerSchemas[provider]?.properties && (
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

              {/* Generic JSON fallback shown for 'custom' or when no schema is available */}
              {(provider === CUSTOM_PROVIDER || !providerSchemas[provider]?.properties) && (
                <div className={common.formField}>
                  <JsonTextArea
                    id="provider_config"
                    labelText={intl.formatMessage(messages.providerConfig)}
                    placeholder='{"loader_class_path": "my_package.loaders.MyLoader"}'
                    storedValue={typeof providerConfigRaw === 'object' ? providerConfigRaw as Record<string, unknown> : null}
                    rows={4}
                    invalid={providerConfigValidation.isInvalid}
                    invalidText={providerConfigValidation.errorMessage}
                    onChange={(value) => {
                      controller?.updatePropertyValue?.({ name: ATTR.PROVIDER_CONFIG }, value);
                    }}
                  />
                </div>
              )}

            </div>
          </AccordionItem>

          {/* ── Ingestion settings ──────────────────────────────────── */}
          <AccordionItem title={intl.formatMessage(messages.ingestionSettings)}>
            <div className={common.accordionContent}>

              <p className={common.accordionDescription}>
                {intl.formatMessage(messages.ingestionSettingsDescription)}
              </p>

              <div className={common.formField}>
                <div className={common.labelWithTooltip}>
                  <RequiredParamTooltip
                    paramId={ATTR.MAX_FILES}
                    nodeAttributes={nodeAttributes}
                    definition={nodeAttributes[ATTR.MAX_FILES]?.description ?? ''}
                  >
                    {intl.formatMessage(messages.maxFiles)}
                  </RequiredParamTooltip>
                </div>
                <NumberInput
                  id="max_files"
                  label={intl.formatMessage(messages.maxFiles)}
                  hideLabel
                  value={maxFiles}
                  min={1}
                  invalid={maxFilesValidation.isInvalid}
                  invalidText={maxFilesValidation.errorMessage}
                  onChange={(_e: unknown, { value }: { value: number | string }) => {
                    controller?.updatePropertyValue?.({ name: ATTR.MAX_FILES }, Number(value));
                  }}
                />
              </div>

              <div className={common.formField}>
                <div className={common.labelWithTooltip}>
                  <RequiredParamTooltip
                    paramId={ATTR.INCLUDE_FILTER}
                    nodeAttributes={nodeAttributes}
                    definition={nodeAttributes[ATTR.INCLUDE_FILTER]?.description ?? ''}
                  >
                    {intl.formatMessage(messages.includeFilter)}
                  </RequiredParamTooltip>
                </div>
                <FilterableMultiSelect
                  key={selectedIncludeFilter.join(',')}
                  id="include_filter"
                  titleText={intl.formatMessage(messages.includeFilter)}
                  hideLabel
                  placeholder={intl.formatMessage(messages.includeFilterPlaceholder)}
                  items={[...SUPPORTED_FILE_EXTENSIONS]}
                  itemToString={(item: string | null) => item ?? ''}
                  initialSelectedItems={selectedIncludeFilter}
                  onChange={({ selectedItems }: { selectedItems: string[] }) => {
                    controller?.updatePropertyValue?.({ name: ATTR.INCLUDE_FILTER }, selectedItems);
                  }}
                  invalid={includeFilterValidation.isInvalid}
                  invalidText={includeFilterValidation.errorMessage}
                  warn={!!filterConflictWarning}
                  warnText={filterConflictWarning ?? undefined}
                />
              </div>

              <div className={common.formField}>
                <div className={common.labelWithTooltip}>
                  <RequiredParamTooltip
                    paramId={ATTR.EXCLUDE_FILTER}
                    nodeAttributes={nodeAttributes}
                    definition={nodeAttributes[ATTR.EXCLUDE_FILTER]?.description ?? ''}
                  >
                    {intl.formatMessage(messages.excludeFilter)}
                  </RequiredParamTooltip>
                </div>
                <FilterableMultiSelect
                  key={selectedExcludeFilter.join(',')}
                  id="exclude_filter"
                  titleText={intl.formatMessage(messages.excludeFilter)}
                  hideLabel
                  placeholder={intl.formatMessage(messages.excludeFilterPlaceholder)}
                  items={[...SUPPORTED_FILE_EXTENSIONS]}
                  itemToString={(item: string | null) => item ?? ''}
                  initialSelectedItems={selectedExcludeFilter}
                  onChange={({ selectedItems }: { selectedItems: string[] }) => {
                    controller?.updatePropertyValue?.({ name: ATTR.EXCLUDE_FILTER }, selectedItems);
                  }}
                  invalid={excludeFilterValidation.isInvalid}
                  invalidText={excludeFilterValidation.errorMessage}
                  warn={!!filterConflictWarning}
                  warnText={filterConflictWarning ?? undefined}
                />
              </div>

              <div className={common.formField}>
                <div className={common.labelWithTooltip}>
                  <RequiredParamTooltip
                    paramId={ATTR.IGNORE_HIDDEN_FILES}
                    nodeAttributes={nodeAttributes}
                    definition={nodeAttributes[ATTR.IGNORE_HIDDEN_FILES]?.description ?? ''}
                  >
                    {intl.formatMessage(messages.ignoreHiddenFiles)}
                  </RequiredParamTooltip>
                </div>
                <Toggle
                  id="ignore_hidden_files"
                  labelText={intl.formatMessage(messages.ignoreHiddenFiles)}
                  hideLabel
                  labelA={intl.formatMessage(messages.off)}
                  labelB={intl.formatMessage(messages.on)}
                  toggled={ignoreHiddenFiles}
                  onToggle={(checked: boolean) => {
                    controller?.updatePropertyValue?.({ name: ATTR.IGNORE_HIDDEN_FILES }, checked);
                  }}
                />
              </div>

            </div>
          </AccordionItem>

        </Accordion>
      )}

    </div>
  );
}
