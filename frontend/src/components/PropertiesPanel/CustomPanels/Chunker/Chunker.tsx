/**
 * @file Chunker operator properties panel body.
 *
 * Renders the configuration UI for the `chunker` node.
 *
 * Structure:
 *   - "Use Docling Serve" toggle — when on, writes provider='docling_serve' and
 *     auto-sets chunk_type='hybrid'. The provider_config JSON textarea appears
 *     beneath it.
 *   - chunk_type dropdown — always visible; drives conditional field visibility:
 *       simple:   chunk_size, chunk_overlap, chunk_overlap_percentage
 *       semantic: semantic_embeddings_model, breakpoint_threshold_type, breakpoint_threshold_amount
 *       hybrid:   chunk_size, chunk_overlap, chunk_overlap_percentage, docling_tokenizer
 *   - retain_original_content toggle — always visible
 *   - Summarization accordion — toggle to enable + JSON textarea when enabled
 */

import React, { useCallback, useState } from 'react';
import { useIntl, type MessageDescriptor } from 'react-intl';
import { getRequiredParamValidator } from '@/utils/requiredParamValidation';
import type { OperatorFeature, OperatorMetadata } from '@/types';
import { NodeOperator } from '@/constants/operators';
import { RequiredParamTooltip } from '@/components/common';
import { JsonTextArea } from '@/components/common/JsonTextArea/JsonTextArea';
import { ProviderFieldsForm } from '../shared/ProviderFieldsForm';
import {
  Accordion,
  AccordionItem,
  DefinitionTooltip,
  Dropdown,
  NumberInput,
  TextInput,
  Toggle,
} from '@carbon/react';
import {
  CHUNKER_ATTRIBUTE as ATTR,
  CHUNKER_DEFAULTS,
  CHUNK_TYPES,
  BREAKPOINT_THRESHOLD_TYPES,
  type ChunkType,
  type BreakpointThresholdType,
} from './constants';
import { messages } from './Chunker.messages';
import common from '../../CommonPropertiesPanel.module.scss';
import { useProviderConfigDefaults } from '@/hooks/useProviderConfigDefaults';

const DOCLING_SERVE_CONFIG_EXAMPLE =
  '{"api_base": "https://docling-serve.example.com", "api_key": "...", "timeout": 300}';
const SUMMARIZATION_CONFIG_EXAMPLE =
  '{"provider": "litellm", "provider_config": {"model_id": "ollama/llama3.2", "api_base": "http://localhost:11434/v1"}}';

/** Maps backend chunk_type value -> translated dropdown label. */
const CHUNK_TYPE_MESSAGES: Record<ChunkType, MessageDescriptor> = {
  simple: messages.chunkTypeSimple,
  semantic: messages.chunkTypeSemantic,
  hybrid: messages.chunkTypeHybrid,
};

/** Maps backend breakpoint_threshold_type value -> translated dropdown label. */
const BREAKPOINT_THRESHOLD_TYPE_MESSAGES: Record<BreakpointThresholdType, MessageDescriptor> = {
  percentile: messages.thresholdTypePercentile,
  standard_deviation: messages.thresholdTypeStandardDeviation,
  interquartile: messages.thresholdTypeInterquartile,
  gradient: messages.thresholdTypeGradient,
};

interface ChunkerPanelBodyProps {
  controller: any;
}

export function ChunkerPanelBody({ controller }: ChunkerPanelBodyProps): React.JSX.Element {
  const intl = useIntl();

  // ── Operator attribute metadata ──────────────────────────────────────────
  // eslint-disable-next-line @typescript-eslint/no-unsafe-call, @typescript-eslint/no-unsafe-member-access
  const operatorMetadata = (controller?.getAppData?.()?.operatorMetadata ?? {}) as Record<string, OperatorMetadata>;
  const nodeAttributes: Record<string, OperatorFeature> = operatorMetadata[NodeOperator.CHUNKER]?.attributes ?? {};

  // ── Read persisted values ────────────────────────────────────────────────

  const chunkType: ChunkType =
    // eslint-disable-next-line @typescript-eslint/no-unsafe-call
    (controller?.getPropertyValue?.({ name: ATTR.CHUNK_TYPE }) as ChunkType | undefined)
    ?? CHUNKER_DEFAULTS.CHUNK_TYPE;

  const chunkSize: number =
    // eslint-disable-next-line @typescript-eslint/no-unsafe-call
    (controller?.getPropertyValue?.({ name: ATTR.CHUNK_SIZE }) as number | undefined)
    ?? CHUNKER_DEFAULTS.CHUNK_SIZE;

  const chunkOverlap: number =
    // eslint-disable-next-line @typescript-eslint/no-unsafe-call
    (controller?.getPropertyValue?.({ name: ATTR.CHUNK_OVERLAP }) as number | undefined)
    ?? CHUNKER_DEFAULTS.CHUNK_OVERLAP;

  const chunkOverlapPercentage: number =
    // eslint-disable-next-line @typescript-eslint/no-unsafe-call
    (controller?.getPropertyValue?.({ name: ATTR.CHUNK_OVERLAP_PERCENTAGE }) as number | undefined)
    ?? CHUNKER_DEFAULTS.CHUNK_OVERLAP_PERCENTAGE;

  const semanticEmbeddingsModel: string =
    // eslint-disable-next-line @typescript-eslint/no-unsafe-call
    (controller?.getPropertyValue?.({ name: ATTR.SEMANTIC_EMBEDDINGS_MODEL }) as string | undefined)
    ?? '';

  const breakpointThresholdType: BreakpointThresholdType =
    // eslint-disable-next-line @typescript-eslint/no-unsafe-call
    (controller?.getPropertyValue?.({ name: ATTR.BREAKPOINT_THRESHOLD_TYPE }) as BreakpointThresholdType | undefined)
    ?? CHUNKER_DEFAULTS.BREAKPOINT_THRESHOLD_TYPE;

  const breakpointThresholdAmount: number | undefined =
    // eslint-disable-next-line @typescript-eslint/no-unsafe-call
    controller?.getPropertyValue?.({ name: ATTR.BREAKPOINT_THRESHOLD_AMOUNT }) as number | undefined;

  const doclingTokenizer: string =
    // eslint-disable-next-line @typescript-eslint/no-unsafe-call
    (controller?.getPropertyValue?.({ name: ATTR.DOCLING_TOKENIZER }) as string | undefined)
    ?? CHUNKER_DEFAULTS.DOCLING_TOKENIZER;

  const retainOriginalContent: boolean =
    // eslint-disable-next-line @typescript-eslint/no-unsafe-call
    (controller?.getPropertyValue?.({ name: ATTR.RETAIN_ORIGINAL_CONTENT }) as boolean | undefined)
    ?? CHUNKER_DEFAULTS.RETAIN_ORIGINAL_CONTENT;

  // summarization: controller stores an object (or null when disabled).
  // null/undefined = disabled.
  const summarizationStored =
    // eslint-disable-next-line @typescript-eslint/no-unsafe-call
    controller?.getPropertyValue?.({ name: ATTR.SUMMARIZATION }) as Record<string, unknown> | null | undefined;

  // ── Summarization schema from operator metadata ──────────────────────────
  const summarizationProperties = nodeAttributes[ATTR.SUMMARIZATION]?.properties ?? {};
  const hasSummarizationProperties = Object.keys(summarizationProperties).length > 0;
  const summarizationProviderConfigDef = summarizationProperties['provider_config'];
  const summarizationProviderSchemas = summarizationProviderConfigDef?.providers ?? {};
  const summarizationProviderItems: string[] =
    (summarizationProperties['provider']?.valid_values) ?? [];

  const provider: string | null =
    // eslint-disable-next-line @typescript-eslint/no-unsafe-call
    (controller?.getPropertyValue?.({ name: ATTR.PROVIDER }) as string | undefined)
    ?? null;

  // provider_config: controller stores an object; stringify only for display.
  const providerConfigStored =
    // eslint-disable-next-line @typescript-eslint/no-unsafe-call
    controller?.getPropertyValue?.({ name: ATTR.PROVIDER_CONFIG }) as Record<string, unknown> | null | undefined;

  // ── Derived state ────────────────────────────────────────────────────────

  const doclingServeEnabled = provider === 'docling_serve';
  const isSimple = chunkType === 'simple';
  const isSemantic = chunkType === 'semantic';
  const isHybrid = chunkType === 'hybrid';
  const showSizeOverlap = isSimple || isHybrid;
  const summarizationEnabled = summarizationStored !== null && summarizationStored !== undefined;

  // Selected provider within the summarization config
  const summarizationProvider: string =
    (typeof summarizationStored?.provider === 'string' ? summarizationStored.provider : null)
    ?? (summarizationProperties['provider']?.default as string | undefined)
    ?? 'litellm';

  // Per-field state for the nested summarization provider_config
  const summarizationProviderConfigStored =
    (typeof summarizationStored?.provider_config === 'object' && summarizationStored?.provider_config !== null)
      ? summarizationStored.provider_config as Record<string, unknown>
      : {};
  const [summarizationProviderConfigValues, setSummarizationProviderConfigValues] =
    useState<Record<string, unknown>>(summarizationProviderConfigStored);

  useProviderConfigDefaults(controller, nodeAttributes);

  // ── Helpers ──────────────────────────────────────────────────────────────

  // ── Required param validator ──────────────────────────────────────────────
  const validate = getRequiredParamValidator(nodeAttributes);
  const chunkTypeValidation = validate(ATTR.CHUNK_TYPE, chunkType);
  const chunkSizeValidation = validate(ATTR.CHUNK_SIZE, chunkSize);
  const chunkOverlapValidation = validate(ATTR.CHUNK_OVERLAP, chunkOverlap);
  const chunkOverlapPercentageValidation = validate(
    ATTR.CHUNK_OVERLAP_PERCENTAGE, chunkOverlapPercentage
  );
  const semanticEmbeddingsModelValidation = validate(
    ATTR.SEMANTIC_EMBEDDINGS_MODEL, semanticEmbeddingsModel
  );
  const breakpointThresholdTypeValidation = validate(
    ATTR.BREAKPOINT_THRESHOLD_TYPE, breakpointThresholdType
  );
  const breakpointThresholdAmountValidation = validate(
    ATTR.BREAKPOINT_THRESHOLD_AMOUNT, breakpointThresholdAmount
  );
  const doclingTokenizerValidation = validate(ATTR.DOCLING_TOKENIZER, doclingTokenizer);
  const summarizationValidation = validate(ATTR.SUMMARIZATION, summarizationStored);
  const providerConfigValidation = validate(ATTR.PROVIDER_CONFIG, providerConfigStored);

  const update = useCallback((name: string, value: unknown): void => {
    // eslint-disable-next-line @typescript-eslint/no-unsafe-call
    controller?.updatePropertyValue?.({ name }, value);
  }, [controller]);

  const handleChunkTypeChange = useCallback(
    ({ selectedItem }: { selectedItem: ChunkType | null }): void => {
      if (selectedItem) { update(ATTR.CHUNK_TYPE, selectedItem); }
    }, [update]
  );

  const handleBreakpointTypeChange = useCallback(
    ({ selectedItem }: { selectedItem: BreakpointThresholdType | null }): void => {
      if (selectedItem) { update(ATTR.BREAKPOINT_THRESHOLD_TYPE, selectedItem); }
    }, [update]
  );

  const handleDoclingServeToggle = useCallback(
    (checked: boolean): void => {
      update(ATTR.PROVIDER, checked ? 'docling_serve' : null);
      if (checked) {
        // Auto-set hybrid — docling_serve works best with hybrid and the backend
        // will warn if chunk_type is anything else (DOCLING_SERVE_CHUNK_TYPE_MISMATCH)
        update(ATTR.CHUNK_TYPE, 'hybrid');
      } else {
        // Clear provider_config so stale config isn't sent
        update(ATTR.PROVIDER_CONFIG, null);
      }
    }, [update]
  );

  const handleSummarizationToggle = useCallback(
    (checked: boolean): void => {
      // Enable: seed with minimum meaningful object
      // Disable: write null so backend omits the key entirely.
      const seed = checked ? { provider: 'litellm', provider_config: {} } : null;
      update(ATTR.SUMMARIZATION, seed);
      setSummarizationProviderConfigValues({});
    }, [update]
  );

  return (
    <div className={common.commonPropertiesPanelBody}>

      {/* ═══════════════════════════════════════════════════════════════════
          DOCLING SERVE TOGGLE
      ═══════════════════════════════════════════════════════════════════ */}
      <div className={common.formField}>
        <div className={common.labelWithTooltip}>
          <DefinitionTooltip
            definition={intl.formatMessage(messages.useDoclingServeDescription)}
            openOnHover
            align="right"
          >
            {intl.formatMessage(messages.useDoclingServe)}
          </DefinitionTooltip>
        </div>
        <Toggle
          id="chunker-use-docling-serve"
          labelText={intl.formatMessage(messages.useDoclingServe)}
          hideLabel
          labelA={intl.formatMessage(messages.off)}
          labelB={intl.formatMessage(messages.on)}
          toggled={doclingServeEnabled}
          onToggle={handleDoclingServeToggle}
        />
      </div>

      {/* Provider config — only when Docling Serve is active */}
      {doclingServeEnabled && (
        <div className={common.subSection}>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={ATTR.PROVIDER_CONFIG}
                nodeAttributes={nodeAttributes}
                definition={intl.formatMessage(messages.providerConfigDescription, { example: DOCLING_SERVE_CONFIG_EXAMPLE })}
              >
                {intl.formatMessage(messages.providerConfig)}
              </RequiredParamTooltip>
            </div>
            <JsonTextArea
              id="chunker-provider-config"
              labelText={intl.formatMessage(messages.providerConfig)}
              rows={4}
              storedValue={providerConfigStored ?? null}
              placeholder='{"api_base": "https://docling-serve.example.com"}'
              invalid={providerConfigValidation.isInvalid}
              invalidText={providerConfigValidation.errorMessage}
              onChange={(value) => {
                update(ATTR.PROVIDER_CONFIG, value);
              }}
            />
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════════
          CHUNK TYPE
      ═══════════════════════════════════════════════════════════════════ */}
      <div className={common.formField}>
        <div className={common.labelWithTooltip}>
          <RequiredParamTooltip
            paramId={ATTR.CHUNK_TYPE}
            nodeAttributes={nodeAttributes}
            definition={intl.formatMessage(messages.chunkTypeDescription)}
          >
            {intl.formatMessage(messages.chunkType)}
          </RequiredParamTooltip>
        </div>
        <Dropdown
          id="chunker-chunk-type"
          titleText={intl.formatMessage(messages.chunkType)}
          hideLabel
          label={intl.formatMessage(messages.selectChunkType)}
          items={[...CHUNK_TYPES]}
          selectedItem={chunkType}
          itemToString={(item: ChunkType | null) => (item ? intl.formatMessage(CHUNK_TYPE_MESSAGES[item]) : '')}
          invalid={chunkTypeValidation.isInvalid}
          invalidText={chunkTypeValidation.errorMessage}
          onChange={handleChunkTypeChange}
        />
      </div>

      {/* ═══════════════════════════════════════════════════════════════════
          SIMPLE / HYBRID — size + overlap
      ═══════════════════════════════════════════════════════════════════ */}
      {showSizeOverlap && (
        <div className={common.subSection}>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={ATTR.CHUNK_SIZE}
                nodeAttributes={nodeAttributes}
                definition={
                  isHybrid
                    ? intl.formatMessage(messages.chunkSizeTokensDescription)
                    : intl.formatMessage(messages.chunkSizeCharsDescription)
                }
              >
                {intl.formatMessage(messages.chunkSize)}
              </RequiredParamTooltip>
            </div>
            <NumberInput
              id="chunker-chunk-size"
              label={intl.formatMessage(messages.chunkSize)}
              hideLabel
              value={chunkSize}
              min={isHybrid ? 100 : 500}
              max={isHybrid ? 2048 : 5000}
              step={isHybrid ? 64 : 100}
              invalid={chunkSizeValidation.isInvalid}
              invalidText={chunkSizeValidation.errorMessage}
              onChange={(_e: unknown, { value }: { value: number | string }) => {
                const n = Number(value);
                if (Number.isFinite(n) && n > 0) { update(ATTR.CHUNK_SIZE, n); }
              }}
            />
          </div>

          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={ATTR.CHUNK_OVERLAP}
                nodeAttributes={nodeAttributes}
                definition={intl.formatMessage(messages.chunkOverlapDescription)}
              >
                {intl.formatMessage(messages.chunkOverlap)}
              </RequiredParamTooltip>
            </div>
            <NumberInput
              id="chunker-chunk-overlap"
              label={intl.formatMessage(messages.chunkOverlap)}
              hideLabel
              value={chunkOverlap}
              min={0}
              max={512}
              step={10}
              invalid={chunkOverlapValidation.isInvalid}
              invalidText={chunkOverlapValidation.errorMessage}
              onChange={(_e: unknown, { value }: { value: number | string }) => {
                const n = Number(value);
                if (Number.isFinite(n) && n >= 0) { update(ATTR.CHUNK_OVERLAP, n); }
              }}
            />
          </div>

          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={ATTR.CHUNK_OVERLAP_PERCENTAGE}
                nodeAttributes={nodeAttributes}
                definition={intl.formatMessage(messages.chunkOverlapPercentageDescription)}
              >
                {intl.formatMessage(messages.chunkOverlapPercentage)}
              </RequiredParamTooltip>
            </div>
            <NumberInput
              id="chunker-chunk-overlap-percentage"
              label={intl.formatMessage(messages.chunkOverlapPercentage)}
              hideLabel
              value={chunkOverlapPercentage}
              min={0}
              max={40}
              step={1}
              invalid={chunkOverlapPercentageValidation.isInvalid}
              invalidText={chunkOverlapPercentageValidation.errorMessage}
              onChange={(_e: unknown, { value }: { value: number | string }) => {
                const n = Number(value);
                if (Number.isFinite(n) && n >= 0) { update(ATTR.CHUNK_OVERLAP_PERCENTAGE, n); }
              }}
            />
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════════
          HYBRID — Docling tokenizer
      ═══════════════════════════════════════════════════════════════════ */}
      {isHybrid && (
        <div className={common.formField}>
          <div className={common.labelWithTooltip}>
            <RequiredParamTooltip
              paramId={ATTR.DOCLING_TOKENIZER}
              nodeAttributes={nodeAttributes}
              definition={intl.formatMessage(messages.doclingTokenizerDescription)}
            >
              {intl.formatMessage(messages.doclingTokenizer)}
            </RequiredParamTooltip>
          </div>
          <TextInput
            id="chunker-docling-tokenizer"
            labelText={intl.formatMessage(messages.doclingTokenizer)}
            hideLabel
            placeholder="sentence-transformers/all-MiniLM-L6-v2"
            value={doclingTokenizer}
            invalid={doclingTokenizerValidation.isInvalid}
            invalidText={doclingTokenizerValidation.errorMessage}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
              update(ATTR.DOCLING_TOKENIZER, e.target.value);
            }}
          />
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════════
          SEMANTIC — embeddings model + breakpoint settings
      ═══════════════════════════════════════════════════════════════════ */}
      {isSemantic && (
        <div className={common.subSection}>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={ATTR.SEMANTIC_EMBEDDINGS_MODEL}
                nodeAttributes={nodeAttributes}
                definition={intl.formatMessage(messages.semanticEmbeddingsModelDescription)}
              >
                {intl.formatMessage(messages.semanticEmbeddingsModel)}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="chunker-semantic-embeddings-model"
              labelText={intl.formatMessage(messages.semanticEmbeddingsModel)}
              hideLabel
              placeholder={intl.formatMessage(messages.semanticEmbeddingsModelPlaceholder)}
              value={semanticEmbeddingsModel}
              invalid={semanticEmbeddingsModelValidation.isInvalid || semanticEmbeddingsModel.trim() === ''}
              invalidText={
                semanticEmbeddingsModelValidation.isInvalid
                  ? semanticEmbeddingsModelValidation.errorMessage
                  : intl.formatMessage(messages.semanticEmbeddingsModelRequired)
              }
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                update(ATTR.SEMANTIC_EMBEDDINGS_MODEL, e.target.value);
              }}
            />
          </div>

          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={ATTR.BREAKPOINT_THRESHOLD_TYPE}
                nodeAttributes={nodeAttributes}
                definition={intl.formatMessage(messages.breakpointThresholdTypeDescription)}
              >
                {intl.formatMessage(messages.breakpointThresholdType)}
              </RequiredParamTooltip>
            </div>
            <Dropdown
              id="chunker-breakpoint-threshold-type"
              titleText={intl.formatMessage(messages.breakpointThresholdType)}
              hideLabel
              label={intl.formatMessage(messages.selectThresholdType)}
              items={[...BREAKPOINT_THRESHOLD_TYPES]}
              selectedItem={breakpointThresholdType}
              itemToString={(item: BreakpointThresholdType | null) =>
                item ? intl.formatMessage(BREAKPOINT_THRESHOLD_TYPE_MESSAGES[item]) : ''
              }
              invalid={breakpointThresholdTypeValidation.isInvalid}
              invalidText={breakpointThresholdTypeValidation.errorMessage}
              onChange={handleBreakpointTypeChange}
            />
          </div>

          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={ATTR.BREAKPOINT_THRESHOLD_AMOUNT}
                nodeAttributes={nodeAttributes}
                definition={intl.formatMessage(messages.breakpointThresholdAmountDescription)}
              >
                {intl.formatMessage(messages.breakpointThresholdAmount)}
              </RequiredParamTooltip>
            </div>
            <NumberInput
              id="chunker-breakpoint-threshold-amount"
              label={intl.formatMessage(messages.breakpointThresholdAmount)}
              hideLabel
              value={breakpointThresholdAmount ?? ''}
              min={0}
              step={0.5}
              invalid={breakpointThresholdAmountValidation.isInvalid}
              invalidText={breakpointThresholdAmountValidation.errorMessage}
              onChange={(_e: unknown, { value }: { value: number | string }) => {
                const n = Number(value);
                update(ATTR.BREAKPOINT_THRESHOLD_AMOUNT, Number.isFinite(n) && n >= 0 ? n : undefined);
              }}
            />
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════════
          RETAIN ORIGINAL CONTENT
      ═══════════════════════════════════════════════════════════════════ */}
      <div className={common.formField}>
        <div className={common.labelWithTooltip}>
          <RequiredParamTooltip
            paramId={ATTR.RETAIN_ORIGINAL_CONTENT}
            nodeAttributes={nodeAttributes}
            definition={intl.formatMessage(messages.retainOriginalContentDescription)}
          >
            {intl.formatMessage(messages.retainOriginalContent)}
          </RequiredParamTooltip>
        </div>
        <Toggle
          id="chunker-retain-original-content"
          labelText={intl.formatMessage(messages.retainOriginalContent)}
          hideLabel
          labelA={intl.formatMessage(messages.off)}
          labelB={intl.formatMessage(messages.on)}
          toggled={retainOriginalContent}
          onToggle={(checked: boolean) => { update(ATTR.RETAIN_ORIGINAL_CONTENT, checked); }}
        />
      </div>

      {/* ═══════════════════════════════════════════════════════════════════
          SUMMARIZATION
      ═══════════════════════════════════════════════════════════════════ */}
     <Accordion align="start">
        <AccordionItem title={intl.formatMessage(messages.summarizationAccordion)}>
          <div className={common.accordionContent}>

            <p className={common.accordionDescription}>
              {intl.formatMessage(messages.summarizationAccordionDescription)}
            </p>

          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={ATTR.SUMMARIZATION}
                nodeAttributes={nodeAttributes}
                definition={intl.formatMessage(messages.summarizationDescription)}
              >
                {intl.formatMessage(messages.summarization)}
              </RequiredParamTooltip>
            </div>
            <Toggle
              id="chunker-summarization-toggle"
              labelText={intl.formatMessage(messages.summarization)}
              hideLabel
              labelA={intl.formatMessage(messages.off)}
              labelB={intl.formatMessage(messages.on)}
              toggled={summarizationEnabled}
              onToggle={handleSummarizationToggle}
            />
          </div>

          {summarizationEnabled && (
            <>
              {hasSummarizationProperties ? (
                <>
                  {/* Provider dropdown */}
                  <div className={common.formField}>
                    <div className={common.labelWithTooltip}>
                      <DefinitionTooltip
                        definition={summarizationProperties['provider']?.description ?? ''}
                        openOnHover
                        align="right"
                      >
                        {intl.formatMessage(messages.provider)}
                      </DefinitionTooltip>
                    </div>
                    <Dropdown
                      id="chunker-summarization-provider"
                      titleText={intl.formatMessage(messages.provider)}
                      hideLabel
                      label={intl.formatMessage(messages.selectProvider)}
                      items={summarizationProviderItems}
                      selectedItem={summarizationProvider}
                      itemToString={(item: string | null) => item ?? ''}
                      onChange={({ selectedItem }: { selectedItem: string | null }) => {
                        if (selectedItem) {
                          const updated = { ...summarizationStored, provider: selectedItem, provider_config: {} };
                          update(ATTR.SUMMARIZATION, updated);
                          setSummarizationProviderConfigValues({});
                        }
                      }}
                    />
                  </div>

                  {/* Provider config fields indented under provider dropdown */}
                  {summarizationProviderSchemas[summarizationProvider]?.properties && (
                    <div className={common.subSection}>
                      <ProviderFieldsForm
                        properties={summarizationProviderSchemas[summarizationProvider].properties}
                        values={summarizationProviderConfigValues}
                        onChange={(fieldKey, value) => {
                          const updatedConfig = { ...summarizationProviderConfigValues, [fieldKey]: value };
                          setSummarizationProviderConfigValues(updatedConfig);
                          update(ATTR.SUMMARIZATION, { ...summarizationStored, provider_config: updatedConfig });
                        }}
                      />
                    </div>
                  )}
                </>
              ) : (
                /* JSON fallback when no schema is available */
                <div className={common.formField}>
                  <div className={common.labelWithTooltip}>
                    <RequiredParamTooltip
                      paramId={ATTR.SUMMARIZATION}
                      nodeAttributes={nodeAttributes}
                      definition={intl.formatMessage(messages.summarizationConfigDescription, { example: SUMMARIZATION_CONFIG_EXAMPLE })}
                    >
                      {intl.formatMessage(messages.summarizationConfig)}
                    </RequiredParamTooltip>
                  </div>
                  <JsonTextArea
                    id="chunker-summarization-config"
                    labelText={intl.formatMessage(messages.summarizationConfig)}
                    rows={5}
                    storedValue={summarizationStored ?? null}
                    invalid={summarizationValidation.isInvalid}
                    invalidText={summarizationValidation.errorMessage}
                    onChange={(value) => {
                      update(ATTR.SUMMARIZATION, value ?? null);
                    }}
                  />
                </div>
              )}
            </>
          )}
          </div>
        </AccordionItem>
      </Accordion>
    </div>
  );
}
