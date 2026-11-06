import { describe, it, expect } from 'vitest';
import { buildVectorDBEnrichmentFlow, extractVectorDBNodeResult } from '@/components/PropertiesPanel/CustomPanels/VectorDB/vectordb-enrichment';

describe('vectordb-enrichment', () => {
  describe('buildVectorDBEnrichmentFlow', () => {
    const makePipelineFlow = () => ({
      pipelines: [
        {
          nodes: [
            { id: 'node-1', parameters: { provider: 'opensearch', provider_config: '{"host":"localhost"}' } },
            { id: 'node-2', parameters: { provider: 'milvus', provider_config: {} } },
          ],
        },
      ],
    });

    it('returns a patched flow object', () => {
      const result = buildVectorDBEnrichmentFlow(makePipelineFlow(), 'node-1', 'opensearch', { host: 'localhost' }, 'index_name');
      expect(result).toHaveProperty('pipelines');
    });

    it('normalises provider_config from string to object on each node', () => {
      const result = buildVectorDBEnrichmentFlow(makePipelineFlow(), 'node-1', 'opensearch', { host: 'localhost' }, 'index_name') as any;
      // node-1's provider_config was a string '{"host":"localhost"}' — after patching it becomes an object
      const node = result.pipelines[0].nodes[0];
      expect(typeof node.parameters.provider_config).toBe('object');
    });

    it('does not mutate the original flow', () => {
      const original = makePipelineFlow();
      buildVectorDBEnrichmentFlow(original, 'node-1', 'opensearch', { host: 'h' }, 'index_name');
      expect(original.pipelines[0]?.nodes[0]?.parameters.provider_config).toBe('{"host":"localhost"}');
    });
  });

  describe('extractVectorDBNodeResult', () => {
    it('returns null when response has no pipelines', () => {
      const result = extractVectorDBNodeResult({} as any, 'node-1');
      expect(result).toBeNull();
    });

    it('returns null when nodeId is not found', () => {
      const response = { pipelines: [{ nodes: [{ id: 'other-node', parameters: {} }] }] };
      const result = extractVectorDBNodeResult(response as any, 'node-1');
      expect(result).toBeNull();
    });

    it('returns null when node exists but available_resources is not an array', () => {
      // extractVectorDBNodeResult only returns non-null when available_resources is present
      const response = {
        pipelines: [{ nodes: [{ id: 'node-1', parameters: { enriched_data: true } }] }],
      };
      const result = extractVectorDBNodeResult(response as any, 'node-1');
      expect(result).toBeNull();
    });

    it('returns VectorDBEnrichmentResult when node has available_resources array', () => {
      const response = {
        pipelines: [{
          nodes: [{
            id: 'node-1',
            parameters: {
              available_resources: ['idx-1'],
              feature_mappings: [],
              available_features: {},
              selected_resource_schema: {},
              is_docpipe_supported_resource: {},
              stored_resource_metadata: { vector_similarity: null, dimension_size: null },
            },
          }],
        }],
      };
      const result = extractVectorDBNodeResult(response as any, 'node-1');
      expect(result).not.toBeNull();
      expect(result?.available_resources).toEqual(['idx-1']);
    });
  });
});
