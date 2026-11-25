/**
 * @file VectorDB flow enrichment helpers.
 *
 * Contains all VectorDB-specific logic for preparing a pipeline flow before an
 * enrichment API call and for extracting the result from the backend response.
 * HTTP transport is delegated to the generic `enrichFlowFeatures` function in
 * `operator-actions.ts`, keeping this module free of transport concerns.
 *
 * Exported functions:
 * - `buildVectorDBEnrichmentFlow`  — pure flow patching (no I/O)
 * - `extractVectorDBNodeResult`    — pure response parsing (no I/O)
 * - `enrichFlowFeaturesForNode`    — orchestrates the two helpers + HTTP call
 */

import { enrichFlowFeatures } from '@/services/api';
import { log4js, logUtil } from '@/utils/logger';
import type { VectorDBEnrichmentResult } from '@/types';

const logger = log4js.getLogger('vectordb.enrichment');

/** Typed shape of the enriched pipeline response. */
type EnrichedPipelineResponse = {
  pipelines?: Array<{
    nodes?: Array<{ id: string; parameters?: Record<string, unknown> }>;
  }>;
};

/**
 * Build a patched copy of the pipeline flow ready for a VectorDB enrichment call.
 *
 * - Deep-copies the flow so the live canvas state is never mutated.
 * - Normalises `provider_config` from string → object on every node (Elyra
 *   writes it as a raw string; the backend expects a plain object).
 * - For the target node: injects the current `provider` and `provider_config`.
 * - Optionally patches `resourceNameKey` (e.g. `"index_name"` / `"collection_name"`)
 *   into `provider_config` so the backend returns metadata for a specific resource.
 */
export function buildVectorDBEnrichmentFlow(
  pipelineFlow: object,
  nodeId: string,
  provider: string,
  parsedProviderConfig: Record<string, unknown>,
  resourceNameKey: string,
  selectedResourceName?: string,
  addSparseVector?: boolean
): object {
  const flowToSend = JSON.parse(JSON.stringify(pipelineFlow)) as {
    pipelines?: Array<{ nodes?: Array<Record<string, unknown>> }>;
  };

  for (const pipeline of flowToSend.pipelines ?? []) {
    for (const node of pipeline.nodes ?? []) {
      if (!('parameters' in node)) { node['parameters'] = {}; }
      const params = node['parameters'] as Record<string, unknown>;

      // Normalise provider_config string → object on every node.
      if (typeof params['provider_config'] === 'string') {
        try {
          params['provider_config'] = JSON.parse(params['provider_config']) as Record<string, unknown>;
        } catch {
          // Leave malformed strings as-is; the backend will surface the error.
        }
      }

      if (node['id'] === nodeId) {
        params['provider'] = provider;
        const configPatch = { ...parsedProviderConfig };
        if (selectedResourceName !== undefined) {
          configPatch[resourceNameKey] = selectedResourceName;
        }
        params['provider_config'] = configPatch;
        // Always clear saved feature_mappings so the backend computes fresh ones.
        // Saved mappings are UI state — they must never influence the API response.
        params['feature_mappings'] = [];
        // Patch add_sparse_vector at the top level so the backend's compute_default_feature_mappings
        // knows whether to include sparse embeddings and the content column in the defaults.
        // Only set when explicitly provided; omit otherwise to preserve whatever is already on the node.
        if (addSparseVector !== undefined) {
          params['add_sparse_vector'] = addSparseVector;
        }
      }
    }
  }

  return flowToSend;
}

/**
 * Extract VectorDB-specific metadata for a single node from the enriched response.
 *
 * Returns `null` when:
 * - The node is not found in the response (wrong `nodeId`).
 * - `available_resources` is absent — the backend did not populate VDB metadata
 *   (provider_config was empty, invalid, or the provider was not recognised).
 */
export function extractVectorDBNodeResult(
  data: EnrichedPipelineResponse,
  nodeId: string
): VectorDBEnrichmentResult | null {
  for (const pipeline of data.pipelines ?? []) {
    for (const node of pipeline.nodes ?? []) {
      if (node.id !== nodeId) { continue; }
      const p = (node.parameters ?? {}) as Partial<VectorDBEnrichmentResult>;
      if (!Array.isArray(p.available_resources)) { return null; }
      return {
        available_resources: p.available_resources,
        selected_resource_schema: p.selected_resource_schema ?? {},
        feature_mappings: p.feature_mappings ?? [],
        is_docpipe_supported_resource: p.is_docpipe_supported_resource ?? {},
        stored_resource_metadata: {
          vector_similarity: p.stored_resource_metadata?.vector_similarity ?? null,
          dimension_size: p.stored_resource_metadata?.dimension_size ?? null,
          // Absent from older backends and from providers that do not report it (e.g. Weaviate).
          index_type: p.stored_resource_metadata?.index_type ?? null,
        },
        available_features: p.available_features ?? {},
      };
    }
  }
  return null;
}

/**
 * Enrich a flow and extract VectorDB-specific metadata for a single node.
 *
 * Orchestrates:
 * 1. `buildVectorDBEnrichmentFlow` — patches the flow with current provider values.
 * 2. `enrichFlowFeatures`          — single HTTP transport (generic, in operator-actions).
 * 3. `extractVectorDBNodeResult`   — pulls the target node's VDB metadata out of the response.
 *
 * @param pipelineFlow         - Full Elyra pipeline JSON
 * @param nodeId               - Elyra node ID of the vectordb node being configured
 * @param provider             - Provider string, e.g. `"opensearch"` or `"milvus"`
 * @param parsedProviderConfig - Already-parsed provider_config with resource-specific
 *                               keys stripped by the caller (index_name / collection_name
 *                               / space_type / metric_type / engine)
 * @param resourceNameKey          - Provider-specific key for the resource name in provider_config
 *                               (`"index_name"` for OpenSearch, `"collection_name"` for Milvus)
 * @param selectedResourceName - When set, patches `resourceNameKey` into provider_config so the
 *                               backend returns metadata for that specific existing resource
 */
export const enrichFlowFeaturesForNode = async (
  pipelineFlow: object,
  nodeId: string,
  provider: string,
  parsedProviderConfig: Record<string, unknown>,
  resourceNameKey: string,
  selectedResourceName?: string,
  addSparseVector?: boolean
): Promise<VectorDBEnrichmentResult | null> => {
  const patchedFlow = buildVectorDBEnrichmentFlow(
    pipelineFlow, nodeId, provider, parsedProviderConfig, resourceNameKey, selectedResourceName, addSparseVector
  );

  try {
    const response = await enrichFlowFeatures<EnrichedPipelineResponse>(patchedFlow);
    const result = extractVectorDBNodeResult(response.data, nodeId);

    if (result === null) {
      logUtil.info({
        logger,
        message: 'VectorDB enrichment: no VDB metadata returned for node',
        data: { nodeId },
      });
    }

    return result;

  } catch (error) {
    logUtil.error({
      logger,
      message: 'Failed to enrich VectorDB node features',
      data: { nodeId, error },
    });
    throw error;
  }
};
