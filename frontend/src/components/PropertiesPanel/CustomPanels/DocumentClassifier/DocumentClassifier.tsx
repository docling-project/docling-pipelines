/**
 * @file DocumentClassifier properties panel body.
 *
 * Renders the configuration UI for the `document_classifier` operator node.
 *
 * **UI conventions**:
 * - `DefinitionTooltip` with `openOnHover` → description on hover, no `helperText` clutter
 * - `hideLabel` on every Carbon input → prevents duplicate label text
 * - Each field wrapped in `.formField` → consistent vertical spacing
 *
 * **Data flow**:
 * 1. `Canvas.tsx` fetches operator metadata on mount and stores it in Redux
 * 2. On node edit, `operatorMetadata` is passed into `propertiesInfo.appData`
 * 3. This component reads it via `controller.getAppData().operatorMetadata`
 * 4. Field values are read from `controller.getPropertyValue()` (saved node params),
 *    falling back to `nodeAttributes[key].default` from metadata
 *
 * **Document types** are loaded from `GET /api/v1/document_classes` on panel mount.
 * If the request fails, a warning is shown and a free-text `TextArea` fallback is rendered.
 *
 * All attribute keys and labels live in `./constants` — not hardcoded here.
 */

import React, { useEffect, useMemo, useState } from 'react';
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
  InlineLoading,
  InlineNotification,
  NumberInput,
  TextArea,
  TextInput,
  Toggle,
} from '@carbon/react';
import type { OperatorFeature, OperatorMetadata, DocumentClassItem } from '@/types';
import { getDocumentClasses } from '@/services/api';
import { NodeOperator } from '@/constants/operators';
import { DOCUMENT_CLASSIFIER_ATTRIBUTE as ATTR } from './constants';
import { messages } from './DocumentClassifier.messages';
import common from '../../CommonPropertiesPanel.module.scss';
import { useProviderConfigDefaults } from '@/hooks/useProviderConfigDefaults';

/**
 * Props for {@link DocumentClassifierPanelBody}.
 *
 * `controller` is the Elyra `CommonProperties` controller instance injected
 * by `CommonPropertiesPanelWrapper`. It is typed as `any` because Elyra does
 * not export a public TypeScript interface for it.
 *
 * Relevant methods used in this panel:
 * - `controller.getAppData()` — returns `{ operatorMetadata, nodeId, … }`
 * - `controller.getPropertyValue({ name })` — reads a saved node parameter
 * - `controller.updatePropertyValue({ name }, value)` — writes a node parameter
 */
interface DocumentClassifierPanelBodyProps {
  controller: any;
}

/* eslint-disable @typescript-eslint/no-unsafe-call, @typescript-eslint/no-unsafe-member-access */
export function DocumentClassifierPanelBody({
  controller,
}: DocumentClassifierPanelBodyProps): React.JSX.Element {
  const intl = useIntl();

  // ── Document classes fetched from API ────────────────────────────────
  const [documentClassItems, setDocumentClassItems] = useState<DocumentClassItem[]>([]);
  const [classesLoading, setClassesLoading] = useState(true);
  const [classesError, setClassesError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setClassesLoading(true);
    setClassesError(null);

    getDocumentClasses()
      .then((response) => {
        if (!cancelled) {
          setDocumentClassItems(response.data);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setClassesError(intl.formatMessage(messages.loadDocumentTypesError));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setClassesLoading(false);
        }
      });

    return () => { cancelled = true; };
    // Fetch once on mount; re-running on intl change would trigger a redundant request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Read operator attribute metadata from Redux (passed in via Canvas.tsx) ──
  const operatorMetadata = (controller?.getAppData?.()?.operatorMetadata ?? {}) as Record<string, OperatorMetadata>;
  const nodeAttributes: Record<string, OperatorFeature> = operatorMetadata[NodeOperator.DOCUMENT_CLASSIFIER]?.attributes ?? {};

  // ── Provider dropdown: items and default come entirely from operator metadata ──
  const providerValidValues = (nodeAttributes[ATTR.PROVIDER] as Record<string, unknown> | undefined)?.valid_values;
  const providerItems: string[] = Array.isArray(providerValidValues) ? (providerValidValues as string[]) : [];

  // ── Provider-specific field schema from provider_config metadata ──
  const providerConfigAttr = nodeAttributes[ATTR.PROVIDER_CONFIG];
  const providerSchemas = providerConfigAttr?.providers ?? {};

  // ── Read current saved values from Elyra, falling back to backend defaults ──

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

  // document_types stored as a string array
  const documentTypesRaw = controller?.getPropertyValue?.({ name: ATTR.DOCUMENT_TYPES })
    ?? nodeAttributes[ATTR.DOCUMENT_TYPES]?.default
    ?? [];

  const selectedDocumentTypes: string[] = useMemo(
    () => {
      if (Array.isArray(documentTypesRaw)) {
        return documentTypesRaw.map(String);
      }
      if (typeof documentTypesRaw === 'string' && documentTypesRaw.trim()) {
        return documentTypesRaw.split(',').map((s) => s.trim()).filter(Boolean);
      }
      return [];
    },
    [documentTypesRaw]
  );

  const initialSelectedItems = useMemo(
    () => documentClassItems.filter((item) => selectedDocumentTypes.includes(item.document_type)),
    [documentClassItems, selectedDocumentTypes]
  );

  const confidenceThreshold = (controller?.getPropertyValue?.({ name: ATTR.CONFIDENCE_THRESHOLD }) as number | undefined)
    ?? (nodeAttributes[ATTR.CONFIDENCE_THRESHOLD]?.default as number | undefined);

  const outputColumn = (controller?.getPropertyValue?.({ name: ATTR.OUTPUT_COLUMN }) as string | undefined)
    ?? (nodeAttributes[ATTR.OUTPUT_COLUMN]?.default as string | undefined);

  const includeConfidence = (controller?.getPropertyValue?.({ name: ATTR.INCLUDE_CONFIDENCE }) as boolean | undefined)
    ?? (nodeAttributes[ATTR.INCLUDE_CONFIDENCE]?.default as boolean | undefined);

  const includeReasoning = (controller?.getPropertyValue?.({ name: ATTR.INCLUDE_REASONING }) as boolean | undefined)
    ?? (nodeAttributes[ATTR.INCLUDE_REASONING]?.default as boolean | undefined);

  const docColumn = (controller?.getPropertyValue?.({ name: ATTR.DOC_COLUMN }) as string | undefined)
    ?? (nodeAttributes[ATTR.DOC_COLUMN]?.default as string | undefined);

  useProviderConfigDefaults(controller, nodeAttributes);

  // ── Required param validation ─────────────────────────────────────────────
  const validate = getRequiredParamValidator(nodeAttributes);
  const providerValidation = validate(ATTR.PROVIDER, provider);
  const providerConfigValidation = validate(ATTR.PROVIDER_CONFIG, providerConfigRaw ?? null);
  const documentTypesValidation = validate(ATTR.DOCUMENT_TYPES, documentTypesRaw);
  const confidenceThresholdValidation = validate(ATTR.CONFIDENCE_THRESHOLD, confidenceThreshold);
  const outputColumnValidation = validate(ATTR.OUTPUT_COLUMN, outputColumn);
  const docColumnValidation = validate(ATTR.DOC_COLUMN, docColumn);

  return (
    <div className={common.commonPropertiesPanelBody}>

      {/* ── Provider dropdown — always visible ───────────────────────── */}
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
          selectedItem={provider}
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

      <Accordion align="start">

        {/* ── Provider configuration ──────────────────────────────────── */}
        <AccordionItem title={intl.formatMessage(messages.providerConfigAccordion)}>
          <div className={common.accordionContent}>

            <p className={common.accordionDescription}>
              {intl.formatMessage(messages.providerConfigAccordionDescription)}
            </p>

            {/* Structured fields when provider schema is available */}
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
                        definition={nodeAttributes[ATTR.PROVIDER_CONFIG]?.description ?? ''}
                      >
                        {intl.formatMessage(messages.providerConfig)}
                      </RequiredParamTooltip>
                    </div>
                    <JsonTextArea
                      id="provider_config"
                      labelText={intl.formatMessage(messages.providerConfig)}
                      placeholder='{"model": "ollama/mistral", "api_base": "http://localhost:11434"}'
                      storedValue={typeof providerConfigRaw === 'object' ? providerConfigRaw : null}
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

        {/* ── Classification configuration ─────────────────────────────── */}
        <AccordionItem title={intl.formatMessage(messages.classificationConfigAccordion)}>
          <div className={common.accordionContent}>

            <p className={common.accordionDescription}>
              {intl.formatMessage(messages.classificationConfigDescription)}
            </p>

            {/* Document types */}
            <div className={common.formField}>
              <div className={common.labelWithTooltip}>
                <RequiredParamTooltip
                  paramId={ATTR.DOCUMENT_TYPES}
                  nodeAttributes={nodeAttributes}
                  definition={nodeAttributes[ATTR.DOCUMENT_TYPES]?.description ?? ''}
                >
                  {intl.formatMessage(messages.documentTypes)}
                </RequiredParamTooltip>
              </div>

              {classesLoading && (
                <InlineLoading description={intl.formatMessage(messages.loadingDocumentTypes)} />
              )}

              {!classesLoading && classesError && (
                <>
                  <InlineNotification
                    kind="warning"
                    title=""
                    subtitle={classesError}
                    lowContrast
                    hideCloseButton
                  />
                  <TextArea
                    id="document_types_fallback"
                    labelText={intl.formatMessage(messages.documentTypes)}
                    hideLabel
                    placeholder={intl.formatMessage(messages.documentTypesFallbackPlaceholder)}
                    value={Array.isArray(documentTypesRaw) ? documentTypesRaw.join(', ') : (typeof documentTypesRaw === 'string' ? documentTypesRaw : '')}
                    rows={2}
                    onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => {
                      const types = e.target.value.split(',').map((s) => s.trim()).filter(Boolean);
                      controller?.updatePropertyValue?.({ name: ATTR.DOCUMENT_TYPES }, types);
                    }}
                  />
                </>
              )}

              {!classesLoading && !classesError && (
                <FilterableMultiSelect
                  id="document_types"
                  titleText={intl.formatMessage(messages.documentTypes)}
                  hideLabel
                  placeholder={intl.formatMessage(messages.documentTypesPlaceholder)}
                  items={documentClassItems}
                  itemToString={(item: DocumentClassItem | null) => item?.document_type ?? ''}
                  initialSelectedItems={initialSelectedItems}
                  onChange={({ selectedItems }: { selectedItems: DocumentClassItem[] }) => {
                    const value = selectedItems.map((item) => item.document_type);
                    controller?.updatePropertyValue?.({ name: ATTR.DOCUMENT_TYPES }, value);
                  }}
                  invalid={documentTypesValidation.isInvalid}
                  invalidText={documentTypesValidation.errorMessage}
                />
              )}
            </div>

            {/* Confidence threshold */}
            <div className={common.formField}>
              <div className={common.labelWithTooltip}>
                <RequiredParamTooltip
                  paramId={ATTR.CONFIDENCE_THRESHOLD}
                  nodeAttributes={nodeAttributes}
                  definition={nodeAttributes[ATTR.CONFIDENCE_THRESHOLD]?.description ?? ''}
                >
                  {intl.formatMessage(messages.confidenceThreshold)}
                </RequiredParamTooltip>
              </div>
              <NumberInput
                id="confidence_threshold"
                label={intl.formatMessage(messages.confidenceThreshold)}
                hideLabel
                value={confidenceThreshold}
                min={1}
                max={10}
                step={0.5}
                onChange={(_e: unknown, { value }: { value: number | string }) => {
                  controller?.updatePropertyValue?.({ name: ATTR.CONFIDENCE_THRESHOLD }, Number(value));
                }}
                invalid={confidenceThresholdValidation.isInvalid}
                invalidText={confidenceThresholdValidation.errorMessage}
              />
            </div>

            {/* Output column */}
            <div className={common.formField}>
              <div className={common.labelWithTooltip}>
                <RequiredParamTooltip
                  paramId={ATTR.OUTPUT_COLUMN}
                  nodeAttributes={nodeAttributes}
                  definition={nodeAttributes[ATTR.OUTPUT_COLUMN]?.description ?? ''}
                >
                  {intl.formatMessage(messages.outputColumn)}
                </RequiredParamTooltip>
              </div>
              <TextInput
                id="output_column"
                labelText={intl.formatMessage(messages.outputColumn)}
                hideLabel
                value={outputColumn}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                  controller?.updatePropertyValue?.({ name: ATTR.OUTPUT_COLUMN }, e.target.value);
                }}
                invalid={outputColumnValidation.isInvalid}
                invalidText={outputColumnValidation.errorMessage}
              />
            </div>

            {/* Include confidence toggle */}
            <div className={common.formField}>
              <div className={common.labelWithTooltip}>
                <DefinitionTooltip
                  definition={nodeAttributes[ATTR.INCLUDE_CONFIDENCE]?.description ?? ''}
                  openOnHover
                  align="right"
                >
                  {intl.formatMessage(messages.includeConfidence)}
                </DefinitionTooltip>
              </div>
              <Toggle
                id="include_confidence"
                labelText={intl.formatMessage(messages.includeConfidence)}
                hideLabel
                labelA={intl.formatMessage(messages.off)}
                labelB={intl.formatMessage(messages.on)}
                toggled={includeConfidence}
                onToggle={(checked: boolean) => {
                  controller?.updatePropertyValue?.({ name: ATTR.INCLUDE_CONFIDENCE }, checked);
                }}
              />
            </div>

            {/* Include reasoning toggle */}
            <div className={common.formField}>
              <div className={common.labelWithTooltip}>
                <DefinitionTooltip
                  definition={nodeAttributes[ATTR.INCLUDE_REASONING]?.description ?? ''}
                  openOnHover
                  align="right"
                >
                  {intl.formatMessage(messages.includeReasoning)}
                </DefinitionTooltip>
              </div>
              <Toggle
                id="include_reasoning"
                labelText={intl.formatMessage(messages.includeReasoning)}
                hideLabel
                labelA={intl.formatMessage(messages.off)}
                labelB={intl.formatMessage(messages.on)}
                toggled={includeReasoning}
                onToggle={(checked: boolean) => {
                  controller?.updatePropertyValue?.({ name: ATTR.INCLUDE_REASONING }, checked);
                }}
              />
            </div>

            {/* Document content column */}
            <div className={common.formField}>
              <div className={common.labelWithTooltip}>
                <RequiredParamTooltip
                  paramId={ATTR.DOC_COLUMN}
                  nodeAttributes={nodeAttributes}
                  definition={nodeAttributes[ATTR.DOC_COLUMN]?.description ?? ''}
                >
                  {intl.formatMessage(messages.docColumn)}
                </RequiredParamTooltip>
              </div>
              <TextInput
                id="doc_column"
                labelText={intl.formatMessage(messages.docColumn)}
                hideLabel
                value={docColumn}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                  controller?.updatePropertyValue?.({ name: ATTR.DOC_COLUMN }, e.target.value);
                }}
                invalid={docColumnValidation.isInvalid}
                invalidText={docColumnValidation.errorMessage}
              />
            </div>

          </div>
        </AccordionItem>

      </Accordion>

    </div>
  );
}
