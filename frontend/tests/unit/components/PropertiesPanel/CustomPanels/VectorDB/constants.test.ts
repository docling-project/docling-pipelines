import { describe, it, expect } from 'vitest';
import {
  getProviderConfig,
  VECTORDB_PROVIDERS,
} from '@/components/PropertiesPanel/CustomPanels/VectorDB/constants';

describe('getProviderConfig', () => {
  it('returns the Weaviate entry, not the OpenSearch fallback', () => {
    const cfg = getProviderConfig('weaviate');
    expect(cfg).toBe(getProviderConfig(VECTORDB_PROVIDERS.WEAVIATE));
    expect(cfg).not.toBe(getProviderConfig('opensearch'));
    expect(cfg.resourceNameKey).toBe('collection_name');
    expect(cfg.similarityKey).toBe('distance_metric');
    expect(cfg.hasEngine).toBe(false);
    expect(cfg.defaultSimilarityValues).toEqual(['cosine', 'dot', 'l2-squared', 'manhattan', 'hamming']);
    expect(cfg.supportsSparse).toBe(true);
    expect(cfg.sparseLabel).toBe('bm25');
    expect(cfg.advancedOnlyKeys).toEqual(['index_type', 'index_parameters']);
    expect(cfg.resourceNameExample).toBe('DocumentChunks');
  });

  it('falls back to OpenSearch for an unknown provider', () => {
    expect(getProviderConfig('unknown')).toBe(getProviderConfig('opensearch'));
  });

  it('keeps the Advanced-only keys out of the managed connection keys of every provider', () => {
    for (const provider of Object.values(VECTORDB_PROVIDERS)) {
      const cfg = getProviderConfig(provider);
      for (const key of cfg.advancedOnlyKeys) {
        expect(cfg.connectionKeys).not.toContain(key);
        expect(cfg.resourceSpecificKeys).toContain(key);
      }
    }
  });
});
