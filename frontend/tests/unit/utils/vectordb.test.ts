import { describe, it, expect } from 'vitest';
import { isMilvusGpuMode } from '@/utils/vectordb';

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
