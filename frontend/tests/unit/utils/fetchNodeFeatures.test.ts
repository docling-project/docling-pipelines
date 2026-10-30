import { describe, it, expect } from 'vitest';
import { fetchNodeFeatures } from '@/utils/fetchNodeFeatures';
import { server } from '../../mocks/server';
import { http, HttpResponse } from 'msw';

const BASE_FLOW = {
  pipelines: [
    {
      nodes: [
        { id: 'node-1', op: 'chunker', parameters: { chunk_size: 500 } },
        { id: 'node-2', op: 'embeddings' },
      ],
    },
  ],
};

const ENRICHED_RESPONSE = {
  pipelines: [
    {
      nodes: [
        {
          id: 'node-1',
          parameters: {
            input_features: { content: { type: 'string' } },
            output_features: { chunks: { type: 'array' } },
          },
        },
        {
          id: 'node-2',
          parameters: {
            input_features: { chunks: { type: 'array' } },
            output_features: { embeddings: { type: 'array' } },
          },
        },
      ],
    },
  ],
};

describe('fetchNodeFeatures', () => {
  it('returns NodeFeatureMap keyed by node ID', async () => {
    server.use(
      http.post('/api/enrichFlowFeatures', () => HttpResponse.json(ENRICHED_RESPONSE))
    );
    const map = await fetchNodeFeatures(BASE_FLOW);
    expect(map['node-1']).toBeDefined();
    expect(map['node-2']).toBeDefined();
  });

  it('maps input_features for each node', async () => {
    server.use(
      http.post('/api/enrichFlowFeatures', () => HttpResponse.json(ENRICHED_RESPONSE))
    );
    const map = await fetchNodeFeatures(BASE_FLOW);
    expect(map['node-1']?.input_features).toEqual({ content: { type: 'string' } });
  });

  it('maps output_features for each node', async () => {
    server.use(
      http.post('/api/enrichFlowFeatures', () => HttpResponse.json(ENRICHED_RESPONSE))
    );
    const map = await fetchNodeFeatures(BASE_FLOW);
    expect(map['node-2']?.output_features).toEqual({ embeddings: { type: 'array' } });
  });

  it('injects parameters: {} for nodes that lack it', async () => {
    const flowWithoutParams = {
      pipelines: [{ nodes: [{ id: 'node-bare', op: 'noop' }] }],
    };
    server.use(
      http.post('/api/enrichFlowFeatures', async ({ request }) => {
        const body = await request.json() as typeof flowWithoutParams;
        const node = body.pipelines[0]?.nodes[0] as Record<string, unknown>;
        expect(node['parameters']).toBeDefined();
        return HttpResponse.json({ pipelines: [{ nodes: [{ id: 'node-bare', parameters: {} }] }] });
      })
    );
    const map = await fetchNodeFeatures(flowWithoutParams);
    expect(map['node-bare']).toBeDefined();
  });

  it('throws on network error', async () => {
    server.use(
      http.post('/api/enrichFlowFeatures', () => HttpResponse.error())
    );
    await expect(fetchNodeFeatures(BASE_FLOW)).rejects.toThrow();
  });
});
