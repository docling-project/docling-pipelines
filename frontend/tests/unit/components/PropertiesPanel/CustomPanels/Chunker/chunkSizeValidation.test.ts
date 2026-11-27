import { describe, it, expect } from 'vitest';
import {
  getChunkSizeRange,
  hasInvalidChunkSize,
  isChunkSizeOutOfRange,
} from '@/components/PropertiesPanel/CustomPanels/Chunker/chunkSizeValidation';

describe('getChunkSizeRange', () => {
  it('returns 500-5000 for simple', () => {
    expect(getChunkSizeRange('simple')).toMatchObject({ min: 500, max: 5000 });
  });

  it('returns 100-2048 for hybrid', () => {
    expect(getChunkSizeRange('hybrid')).toMatchObject({ min: 100, max: 2048 });
  });

  it('returns undefined for semantic', () => {
    expect(getChunkSizeRange('semantic')).toBeUndefined();
  });
});

describe('isChunkSizeOutOfRange', () => {
  it.each([
    ['simple', 499, true],
    ['simple', 500, false],
    ['simple', 5000, false],
    ['simple', 5001, true],
    ['simple', 0, true],
    ['simple', -10, true],
    ['hybrid', 99, true],
    ['hybrid', 100, false],
    ['hybrid', 2048, false],
    ['hybrid', 2049, true],
  ] as const)('%s chunk_size %i -> out of range: %s', (chunkType, size, expected) => {
    expect(isChunkSizeOutOfRange(chunkType, size)).toBe(expected);
  });

  it('is always false for semantic', () => {
    expect(isChunkSizeOutOfRange('semantic', 1)).toBe(false);
    expect(isChunkSizeOutOfRange('semantic', 99999)).toBe(false);
  });

  it('is false when chunk size is not set', () => {
    expect(isChunkSizeOutOfRange('simple', undefined)).toBe(false);
    expect(isChunkSizeOutOfRange('simple', null)).toBe(false);
    expect(isChunkSizeOutOfRange('simple', '')).toBe(false);
  });
});

describe('hasInvalidChunkSize', () => {
  it('uses the simple range when chunk_type is absent', () => {
    expect(hasInvalidChunkSize({ chunk_size: 300 })).toBe(true);
    expect(hasInvalidChunkSize({ chunk_size: 1000 })).toBe(false);
  });

  it('re-evaluates the same size for a different chunk type', () => {
    expect(hasInvalidChunkSize({ chunk_type: 'simple', chunk_size: 3000 })).toBe(false);
    expect(hasInvalidChunkSize({ chunk_type: 'hybrid', chunk_size: 3000 })).toBe(true);
    expect(hasInvalidChunkSize({ chunk_type: 'hybrid', chunk_size: 300 })).toBe(false);
    expect(hasInvalidChunkSize({ chunk_type: 'simple', chunk_size: 300 })).toBe(true);
  });

  it('ignores chunk size for semantic', () => {
    expect(hasInvalidChunkSize({ chunk_type: 'semantic', chunk_size: 10 })).toBe(false);
  });
});
