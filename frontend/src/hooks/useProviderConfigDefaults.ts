/**
 * @file useProviderConfigDefaults
 *
 * Seeds provider-specific configuration defaults into the pipeline flow parameters
 * whenever a panel with provider-specific configuration UI is first opened or the active
 * provider changes.
 *
 * The effect only writes when the stored
 * config object is absent or empty (`null`, `undefined`, or `{}`), so it
 * never replaces values the user has already set or that were loaded from a
 * saved flow.
 *
 * ## Supported operators and their layouts
 *
 * Flat (top-level `provider` → top-level config param):
 *   ingest_source        provider → provider_config
 *   embeddings           provider → provider_config
 *   document_classifier  provider → provider_config
 *   pii_and_hap          provider → provider_config
 *
 * Nested (provider + provider_config both live inside one parent param):
 *   storage_output       destination_config.provider → destination_config.provider_config
 *   extract_operator     text_extraction.provider    → text_extraction.provider_config
 *                        entity_extraction.provider  → entity_extraction.provider_config
 *   chunker              summarization.provider      → summarization.provider_config
 */

import { useEffect } from 'react';
import type { OperatorFeature } from '@/types';
import { NodeOperator } from '@/constants/operators';
import { STORAGE_OUTPUT_ATTRIBUTE } from '@/components/PropertiesPanel/CustomPanels/StorageOutput/constants';
import { EXTRACT_ATTRIBUTE, EXTRACTION_KEY } from '@/components/PropertiesPanel/CustomPanels/Extract/constants';
import { CHUNKER_ATTRIBUTE } from '@/components/PropertiesPanel/CustomPanels/Chunker/constants';

// ── Param key constants ───────────────────────────────────────────────────────
const PROVIDER = EXTRACTION_KEY.PROVIDER;
const PROVIDER_CONFIG = EXTRACTION_KEY.PROVIDER_CONFIG;
const DESTINATION_CONFIG = STORAGE_OUTPUT_ATTRIBUTE.DESTINATION_CONFIG;
const TEXT_EXTRACTION = EXTRACT_ATTRIBUTE.TEXT_EXTRACTION;
const ENTITY_EXTRACTION = EXTRACT_ATTRIBUTE.ENTITY_EXTRACTION;
const SUMMARIZATION = CHUNKER_ATTRIBUTE.SUMMARIZATION;

/* eslint-disable @typescript-eslint/no-unsafe-call, @typescript-eslint/no-unsafe-member-access */

/**
 * Seeds provider-specific configuration defaults into pipeline flow
 *
 * @param controller     - Elyra properties controller (typed as `any` by Elyra)
 * @param nodeAttributes - Operator attribute metadata from `operatorMetadata[op].attributes`
 */
export function useProviderConfigDefaults(
  controller: any,
  nodeAttributes: Record<string, OperatorFeature>
): void {
  // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment
  const currentNodeId: string = controller?.getAppData?.()?.nodeId ?? '';
  // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment
  const nodes: any[] = controller?.getAppData?.()?.pipelineFlow?.pipelines?.[0]?.nodes ?? [];
  const nodeOp: string = (nodes.find((n: any) => n.id === currentNodeId)?.op as string | undefined) ?? '';

  // Read the active provider value as effect dependencies so the effect
  // re-runs whenever the user switches provider in any of the covered panels.
  const flatProvider: string | undefined =
    controller?.getPropertyValue?.({ name: PROVIDER }) as string | undefined;

  const destinationConfigProvider: string | undefined =
    (controller?.getPropertyValue?.({ name: DESTINATION_CONFIG }) as
      | Record<string, unknown>
      | undefined)?.[PROVIDER] as string | undefined;

  const textExtractionProvider: string | undefined =
    (controller?.getPropertyValue?.({ name: TEXT_EXTRACTION }) as
      | Record<string, unknown>
      | undefined)?.[PROVIDER] as string | undefined;

  const entityExtractionProvider: string | undefined =
    (controller?.getPropertyValue?.({ name: ENTITY_EXTRACTION }) as
      | Record<string, unknown>
      | undefined)?.[PROVIDER] as string | undefined;

  const summarizationProvider: string | undefined =
    (controller?.getPropertyValue?.({ name: SUMMARIZATION }) as
      | Record<string, unknown>
      | undefined)?.[PROVIDER] as string | undefined;

  /**
   * Flat layout: top-level `provider` param → top-level config param.
   * Looks up the active provider, finds its schema at
   * `nodeAttributes[configKey].providers[provider]`, and seeds defaults
   * into `configKey` if it is currently empty.
   */
  const seedFlat = (configKey: string): void => {
    const activeProvider = controller?.getPropertyValue?.({ name: PROVIDER }) as string | undefined;
    if (!activeProvider) { return; }

    const schema = nodeAttributes[configKey]?.providers?.[activeProvider];
    if (!schema?.properties) { return; }

    const stored = controller?.getPropertyValue?.({ name: configKey }) as
      | Record<string, unknown>
      | null
      | undefined;
    if (!isEmptyConfig(stored)) { return; }

    const defaults = buildDefaults(schema.properties);
    if (Object.keys(defaults).length > 0) {
      controller?.updatePropertyValue?.({ name: configKey }, defaults);
    }
  };

  /**
   * Nested layout: `parentKey.provider` → `parentKey.provider_config`.
   * Reads the parent object, finds the active provider inside it, looks up
   * the schema at `nodeAttributes[parentKey].properties.provider_config
   * .providers[provider]`, and seeds defaults into `parentKey.provider_config`
   * if it is currently empty.
   */
  const seedNested = (parentKey: string): void => {
    const parent = (controller?.getPropertyValue?.({ name: parentKey }) as
      | Record<string, unknown>
      | undefined) ?? {};

    const activeProvider = parent[PROVIDER] as string | undefined;
    if (!activeProvider) { return; }

    const parentMeta = (nodeAttributes[parentKey] as Record<string, unknown> | undefined)
      ?.properties as Record<string, OperatorFeature> | undefined ?? {};
    const schema = parentMeta[PROVIDER_CONFIG]?.providers?.[activeProvider];
    if (!schema?.properties) { return; }

    const stored = parent[PROVIDER_CONFIG] as Record<string, unknown> | null | undefined;
    if (!isEmptyConfig(stored)) { return; }

    const defaults = buildDefaults(schema.properties);
    if (Object.keys(defaults).length > 0) {
      controller?.updatePropertyValue?.(
        { name: parentKey },
        { ...parent, [PROVIDER_CONFIG]: defaults }
      );
    }
  };

  useEffect(() => {
    if (!controller || !nodeOp || Object.keys(nodeAttributes).length === 0) {
      return;
    }

    // ── flat provider_config operators ────────────────────────────────────────
    if (
      nodeOp === NodeOperator.INGEST_SOURCE ||
      nodeOp === NodeOperator.EMBEDDINGS ||
      nodeOp === NodeOperator.DOCUMENT_CLASSIFIER ||
      nodeOp === NodeOperator.PII_AND_HAP
    ) {
      seedFlat(PROVIDER_CONFIG);
    }

    // ── storage_output — provider_config nested inside destination_config ─────
    else if (nodeOp === NodeOperator.STORAGE_OUTPUT) {
      seedNested(DESTINATION_CONFIG);
    }

    // ── extract_operator — two independent nested sub-objects ─────────────────
    else if (nodeOp === NodeOperator.EXTRACT) {
      seedNested(TEXT_EXTRACTION);
      seedNested(ENTITY_EXTRACTION);
    }

    // ── chunker — provider_config nested inside summarization ─────────────────
    else if (nodeOp === NodeOperator.CHUNKER) {
      seedNested(SUMMARIZATION);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    nodeOp,
    nodeAttributes,
    flatProvider,
    destinationConfigProvider,
    textExtractionProvider,
    entityExtractionProvider,
    summarizationProvider,
  ]);
}

/** Returns true when the stored config should be seeded with defaults. */
function isEmptyConfig(stored: Record<string, unknown> | null | undefined): boolean {
  return stored === null || stored === undefined || Object.keys(stored).length === 0;
}

/** Collects all fields from a provider schema's `properties` that have a `default`. */
function buildDefaults(properties: Record<string, OperatorFeature>): Record<string, unknown> {
  const defaults: Record<string, unknown> = {};
  for (const [key, def] of Object.entries(properties)) {
    if (def.default !== undefined) {
      defaults[key] = def.default;
    }
  }
  return defaults;
}
