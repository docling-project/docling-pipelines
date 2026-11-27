import { describe, it, expect } from 'vitest';
import {
  getProviderConfig,
  DEFAULT_ALGORITHM_VALUES,
  DEFAULT_INDEX_TYPE_VALUES,
} from '@/components/PropertiesPanel/CustomPanels/VectorDB/constants';

describe('getProviderConfig index algorithm fields', () => {
  it('maps OpenSearch to the algorithm key', () => {
    const cfg = getProviderConfig('opensearch');
    expect(cfg.indexTypeKey).toBe('algorithm');
    expect(cfg.indexTypeLabel).toBe('Algorithm');
    expect(cfg.defaultIndexType).toBe('hnsw');
    expect(cfg.defaultIndexTypeValues).toEqual(DEFAULT_ALGORITHM_VALUES);
    expect(cfg.resourceSpecificKeys).toContain('algorithm');
  });

  it('maps Milvus to the index_type key', () => {
    const cfg = getProviderConfig('milvus');
    expect(cfg.indexTypeKey).toBe('index_type');
    expect(cfg.indexTypeLabel).toBe('Index type');
    expect(cfg.defaultIndexType).toBe('HNSW');
    expect(cfg.defaultIndexTypeValues).toEqual(DEFAULT_INDEX_TYPE_VALUES);
    expect(cfg.resourceSpecificKeys).toContain('index_type');
  });

  it('keeps the Milvus fallback list free of removed sparse index types', () => {
    expect(DEFAULT_INDEX_TYPE_VALUES).not.toContain('SPARSE_INVERTED_INDEX');
    expect(DEFAULT_INDEX_TYPE_VALUES).not.toContain('SPARSE_WAND');
    expect(DEFAULT_INDEX_TYPE_VALUES).toHaveLength(13);
  });

  it('falls back to the OpenSearch config for unknown providers', () => {
    expect(getProviderConfig('unknown').indexTypeKey).toBe('algorithm');
  });
});
