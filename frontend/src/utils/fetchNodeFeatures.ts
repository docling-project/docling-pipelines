/**
 * Fetches enriched input/output feature metadata for all nodes in a flow.
 * Returns a map of nodeId → { input_features, output_features }.
 * Plain async function — no Redux, no hooks — safe to call from anywhere.
 */

import { enrichFlowFeatures } from '@/services/api';
import { log4js, logUtil } from '@/utils/logger';
import type { FeatureAttributes } from '@/types';
import { VECTORDB_ATTRIBUTES } from '@/components/PropertiesPanel';

const logger = log4js.getLogger('fetchNodeFeatures');

export interface NodeFeatureMap {
  [nodeId: string]: {
    input_features: Record<string, FeatureAttributes>;
    output_features: Record<string, FeatureAttributes>;
  };
}

export async function fetchNodeFeatures(pipelineFlow: object): Promise<NodeFeatureMap> {
  // Ensure every node has a `parameters` key before sending
  const flowToSend = JSON.parse(JSON.stringify(pipelineFlow)) as {
    pipelines?: Array<{ nodes?: Array<Record<string, unknown>> }>;
  };
  for (const pipeline of flowToSend.pipelines ?? []) {
    for (const node of pipeline.nodes ?? []) {
      if (!('parameters' in node)) {
        node.parameters = {};
      }
      // provider_config is stored as a JSON string in node parameters when the
      // user edits the textarea (updatePropertyValue writes the raw string).
      // The backend expects an object — parse it here before sending.
      const params = node.parameters as Record<string, unknown>;
      if (typeof params[VECTORDB_ATTRIBUTES.PROVIDER_CONFIG] === 'string') {
        try {
          params[VECTORDB_ATTRIBUTES.PROVIDER_CONFIG] = JSON.parse(params[VECTORDB_ATTRIBUTES.PROVIDER_CONFIG] as string) as Record<string, unknown>;
        } catch {
          // Leave malformed strings as-is; the backend will surface the error.
        }
      }
    }
  }

  const response = await enrichFlowFeatures(flowToSend);
  const enrichedFlow = response.data as {
    pipelines?: Array<{ nodes?: Array<{ id: string; parameters?: Record<string, unknown> }> }>;
  };

  const map: NodeFeatureMap = {};
  for (const pipeline of enrichedFlow.pipelines ?? []) {
    for (const node of pipeline.nodes ?? []) {
      map[node.id] = {
        input_features: (node.parameters?.input_features ?? {}) as Record<string, FeatureAttributes>,
        output_features: (node.parameters?.output_features ?? {}) as Record<string, FeatureAttributes>,
      };
    }
  }

  logUtil.info({ logger, message: 'Node features fetched', data: { nodeCount: Object.keys(map).length } });
  return map;
}
