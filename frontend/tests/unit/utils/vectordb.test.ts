import { describe, it, expect } from 'vitest';
import {
  FALLBACK_MILVUS_FAMILIES,
  getMilvusDefaultIndexType,
  getMilvusFamily,
  getMilvusIndexTypeOptions,
  getMilvusMetricOptions,
  getOpenSearchAlgorithmOptions,
  isMilvusGpuMode,
  type VectorDBApplicability,
} from '@/utils/vectordb';

const ALL_METRICS = ['L2', 'IP', 'COSINE', 'BM25', 'HAMMING', 'JACCARD'];
const ALL_INDEX_TYPES = [
  'FLAT', 'IVF_FLAT', 'IVF_SQ8', 'IVF_PQ', 'HNSW', 'DISKANN', 'AUTOINDEX',
  'GPU_CAGRA', 'GPU_IVF_FLAT', 'GPU_IVF_PQ', 'GPU_BRUTE_FORCE',
  'BIN_FLAT', 'BIN_IVF_FLAT',
];
const CPU = ['FLAT', 'IVF_FLAT', 'IVF_SQ8', 'IVF_PQ', 'HNSW', 'DISKANN', 'AUTOINDEX'];
const GPU = ['GPU_CAGRA', 'GPU_IVF_FLAT', 'GPU_IVF_PQ', 'GPU_BRUTE_FORCE'];
const BIN = ['BIN_FLAT', 'BIN_IVF_FLAT'];

const applicability: VectorDBApplicability = {
  index_families: FALLBACK_MILVUS_FAMILIES,
  lite: { index_types: ['FLAT'], default: 'FLAT' },
  engine_algorithms: {
    faiss: ['hnsw', 'ivf'],
    lucene: ['hnsw'],
    nmslib: ['hnsw'],
    jvector: ['hnsw'],
  },
};

describe('isMilvusGpuMode', () => {
  it('is true when vector_mode is gpu', () => {
    expect(isMilvusGpuMode({ vector_mode: 'gpu' })).toBe(true);
  });

  it('is true when vector_mode is unset and index_type starts with GPU_', () => {
    expect(isMilvusGpuMode({ index_type: 'GPU_CAGRA' })).toBe(true);
    expect(isMilvusGpuMode({ index_type: 'GPU_IVF_FLAT' })).toBe(true);
  });

  it('lets an explicit non-gpu vector_mode override a GPU_ index_type', () => {
    expect(isMilvusGpuMode({ vector_mode: 'dense', index_type: 'GPU_CAGRA' })).toBe(false);
  });

  it('is false for CPU index types and empty config', () => {
    expect(isMilvusGpuMode({ index_type: 'HNSW' })).toBe(false);
    expect(isMilvusGpuMode({})).toBe(false);
  });

  it('is false when index_type is not a string', () => {
    expect(isMilvusGpuMode({ index_type: 5 })).toBe(false);
  });
});

describe('getMilvusFamily', () => {
  it('finds the family of an index type', () => {
    expect(getMilvusFamily('HNSW', applicability)?.id).toBe('cpu_dense');
    expect(getMilvusFamily('GPU_CAGRA', applicability)?.id).toBe('gpu');
    expect(getMilvusFamily('BIN_FLAT', applicability)?.id).toBe('binary');
  });

  it('returns undefined for an unknown index type', () => {
    expect(getMilvusFamily('SPARSE_WAND', applicability)).toBeUndefined();
  });

  it('uses the static fallback when metadata has no applicability', () => {
    expect(getMilvusFamily('IVF_PQ')?.id).toBe('cpu_dense');
  });
});

describe('getMilvusIndexTypeOptions', () => {
  it('offers only FLAT on Milvus Lite', () => {
    expect(
      getMilvusIndexTypeOptions({ applicability, authType: 'lite', featureTypes: ['vector'], validValues: ALL_INDEX_TYPES })
    ).toEqual(['FLAT']);
  });

  it('offers only BIN_* types when every vector feature is binary', () => {
    expect(
      getMilvusIndexTypeOptions({ applicability, featureTypes: ['vector_binary'], validValues: ALL_INDEX_TYPES })
    ).toEqual(BIN);
  });

  it('offers CPU dense and GPU types for dense features, without sparse types', () => {
    const options = getMilvusIndexTypeOptions({
      applicability, featureTypes: ['vector'], validValues: ALL_INDEX_TYPES,
    });
    expect(options).toEqual([...CPU, ...GPU]);
    expect(options.some((o) => o.startsWith('SPARSE_'))).toBe(false);
  });

  it('offers dense, GPU and binary types for mixed dense and binary features', () => {
    expect(
      getMilvusIndexTypeOptions({ applicability, featureTypes: ['vector', 'vector_binary'], validValues: ALL_INDEX_TYPES })
    ).toEqual([...CPU, ...GPU, ...BIN]);
  });

  it('offers every type when no vector feature is known', () => {
    expect(
      getMilvusIndexTypeOptions({ applicability, featureTypes: ['string'], validValues: ALL_INDEX_TYPES })
    ).toEqual(ALL_INDEX_TYPES);
  });

  it('narrows to the explicit vector_mode family', () => {
    expect(
      getMilvusIndexTypeOptions({ applicability, featureTypes: ['vector'], vectorMode: 'gpu', validValues: ALL_INDEX_TYPES })
    ).toEqual(GPU);
    expect(
      getMilvusIndexTypeOptions({ applicability, featureTypes: ['vector'], vectorMode: 'dense', validValues: ALL_INDEX_TYPES })
    ).toEqual(CPU);
  });

  it('ignores a vector_mode that would leave no options for the mapped features', () => {
    expect(
      getMilvusIndexTypeOptions({ applicability, featureTypes: ['vector'], vectorMode: 'binary', validValues: ALL_INDEX_TYPES })
    ).toEqual([...CPU, ...GPU]);
  });

  it('ignores vector_mode sparse (no dense family to narrow to)', () => {
    expect(
      getMilvusIndexTypeOptions({ applicability, featureTypes: ['vector'], vectorMode: 'sparse', validValues: ALL_INDEX_TYPES })
    ).toEqual([...CPU, ...GPU]);
  });

  it('drops options missing from valid_values', () => {
    expect(
      getMilvusIndexTypeOptions({ applicability, featureTypes: ['vector'], validValues: ['HNSW', 'FLAT'] })
    ).toEqual(['FLAT', 'HNSW']);
  });

  it('works against metadata without applicability using the static fallback', () => {
    expect(getMilvusIndexTypeOptions({ featureTypes: ['vector_binary'] })).toEqual(BIN);
    expect(getMilvusIndexTypeOptions({ authType: 'lite', featureTypes: ['vector'] })).toEqual(['FLAT']);
  });
});

describe('getMilvusDefaultIndexType', () => {
  it('uses the Lite default on Lite', () => {
    expect(getMilvusDefaultIndexType(['FLAT'], 'HNSW', 'lite', applicability)).toBe('FLAT');
  });

  it('uses the metadata default when it is offered', () => {
    expect(getMilvusDefaultIndexType([...CPU, ...GPU], 'HNSW', 'standalone', applicability)).toBe('HNSW');
  });

  it('falls back to the first option when the metadata default is not offered', () => {
    expect(getMilvusDefaultIndexType(BIN, 'HNSW', 'standalone', applicability)).toBe('BIN_FLAT');
  });

  it('returns an empty string when there are no options', () => {
    expect(getMilvusDefaultIndexType([], undefined, undefined)).toBe('');
  });
});

describe('getMilvusMetricOptions', () => {
  const base = { applicability, providerConfig: {}, sparseEnabled: false, validValues: ALL_METRICS };

  it('offers L2, IP and COSINE for a CPU dense index', () => {
    expect(getMilvusMetricOptions({ ...base, indexType: 'HNSW', featureTypes: ['vector'] })).toEqual(['L2', 'IP', 'COSINE']);
  });

  it('offers L2 and IP for a GPU index', () => {
    expect(getMilvusMetricOptions({ ...base, indexType: 'GPU_CAGRA', featureTypes: ['vector'] })).toEqual(['L2', 'IP']);
  });

  it('offers HAMMING and JACCARD for a binary index', () => {
    expect(getMilvusMetricOptions({ ...base, indexType: 'BIN_FLAT', featureTypes: ['vector_binary'] })).toEqual([
      'HAMMING', 'JACCARD',
    ]);
  });

  it('uses the index selected in the form even when saved config says GPU', () => {
    expect(
      getMilvusMetricOptions({
        ...base, indexType: 'HNSW', featureTypes: ['vector'], providerConfig: { vector_mode: 'gpu' },
      })
    ).toEqual(['L2', 'IP', 'COSINE']);
  });

  it('reflects a GPU selection immediately although saved config is dense', () => {
    expect(
      getMilvusMetricOptions({
        ...base, indexType: 'GPU_IVF_FLAT', featureTypes: ['vector'], providerConfig: { index_type: 'HNSW' },
      })
    ).toEqual(['L2', 'IP']);
  });

  it('reads GPU mode from saved config before any form selection exists', () => {
    expect(
      getMilvusMetricOptions({ ...base, featureTypes: ['vector'], providerConfig: { vector_mode: 'gpu' } })
    ).toEqual(['L2', 'IP']);
    expect(
      getMilvusMetricOptions({ ...base, featureTypes: ['vector'], providerConfig: { index_type: 'GPU_CAGRA' } })
    ).toEqual(['L2', 'IP']);
  });

  it('never offers BM25 for a dense field, even with sparse on', () => {
    const options = getMilvusMetricOptions({ ...base, indexType: 'HNSW', featureTypes: ['vector'], sparseEnabled: true });
    expect(options).toEqual(['L2', 'IP', 'COSINE']);
    expect(options).not.toContain('BM25');
  });

  it('offers BM25 alongside binary metrics for binary-only features with sparse on', () => {
    expect(
      getMilvusMetricOptions({ ...base, indexType: 'BIN_FLAT', featureTypes: ['vector_binary'], sparseEnabled: true })
    ).toEqual(['HAMMING', 'JACCARD', 'BM25']);
  });

  it('keeps binary metrics for binary-only features in gpu mode', () => {
    expect(
      getMilvusMetricOptions({ ...base, featureTypes: ['vector_binary'], providerConfig: { vector_mode: 'gpu' } })
    ).toEqual(['HAMMING', 'JACCARD']);
  });

  it('offers only L2 and IP for mixed dense, binary and sparse features in gpu mode', () => {
    expect(
      getMilvusMetricOptions({
        ...base,
        indexType: 'GPU_CAGRA',
        featureTypes: ['vector', 'vector_binary', 'vector_sparse'],
        sparseEnabled: true,
        providerConfig: { vector_mode: 'gpu' },
      })
    ).toEqual(['L2', 'IP']);
  });

  it('drops BM25 and keeps the rest for mixed dense and binary features without a selection', () => {
    expect(
      getMilvusMetricOptions({ ...base, featureTypes: ['vector', 'vector_binary'], sparseEnabled: true })
    ).toEqual(['L2', 'IP', 'COSINE', 'HAMMING', 'JACCARD']);
  });

  it('returns the dense metrics, not the full list, for dense features without a selection', () => {
    expect(getMilvusMetricOptions({ ...base, featureTypes: ['vector'] })).toEqual(['L2', 'IP', 'COSINE']);
  });

  it('returns the full list when no vector feature is known', () => {
    expect(getMilvusMetricOptions({ ...base, featureTypes: [] })).toEqual(ALL_METRICS);
  });

  it('drops metrics missing from valid_values', () => {
    expect(
      getMilvusMetricOptions({ ...base, indexType: 'HNSW', featureTypes: ['vector'], validValues: ['L2', 'IP'] })
    ).toEqual(['L2', 'IP']);
  });

  it('works without applicability using the static fallback', () => {
    expect(
      getMilvusMetricOptions({ providerConfig: {}, indexType: 'GPU_CAGRA', featureTypes: ['vector'], sparseEnabled: false, validValues: ALL_METRICS })
    ).toEqual(['L2', 'IP']);
  });
});

describe('getOpenSearchAlgorithmOptions', () => {
  const valid = ['hnsw', 'ivf'];

  it('offers hnsw and ivf for faiss', () => {
    expect(getOpenSearchAlgorithmOptions('faiss', applicability, valid)).toEqual(['hnsw', 'ivf']);
  });

  it.each(['lucene', 'nmslib', 'jvector'])('offers only hnsw for %s', (engine) => {
    expect(getOpenSearchAlgorithmOptions(engine, applicability, valid)).toEqual(['hnsw']);
  });

  it('falls back to valid_values for an engine missing from the map', () => {
    expect(getOpenSearchAlgorithmOptions('custom', applicability, valid)).toEqual(valid);
  });

  it('falls back to valid_values when metadata has no applicability', () => {
    expect(getOpenSearchAlgorithmOptions('lucene', undefined, valid)).toEqual(valid);
  });

  it('drops algorithms missing from valid_values', () => {
    expect(getOpenSearchAlgorithmOptions('faiss', applicability, ['hnsw'])).toEqual(['hnsw']);
  });
});
