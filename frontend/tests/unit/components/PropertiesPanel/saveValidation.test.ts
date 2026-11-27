import { describe, it, expect } from 'vitest';
import { shouldDisableSave } from '@/components/PropertiesPanel/saveValidation';
import type { OperatorFeature } from '@/types';

const requiredAttrs = { chunk_type: { required: true } } as unknown as Record<string, OperatorFeature>;

describe('shouldDisableSave', () => {
  it('disables Save when a required param is missing', () => {
    expect(shouldDisableSave('chunker', requiredAttrs, {})).toBe(true);
  });

  it('disables Save for an out-of-range chunker chunk_size', () => {
    expect(shouldDisableSave('chunker', {}, { chunk_type: 'simple', chunk_size: 100 })).toBe(true);
  });

  it('enables Save for a valid chunker chunk_size', () => {
    expect(shouldDisableSave('chunker', requiredAttrs, { chunk_type: 'simple', chunk_size: 500 })).toBe(false);
  });

  it('follows chunk_type changes for the same chunk_size', () => {
    expect(shouldDisableSave('chunker', {}, { chunk_type: 'simple', chunk_size: 3000 })).toBe(false);
    expect(shouldDisableSave('chunker', {}, { chunk_type: 'hybrid', chunk_size: 3000 })).toBe(true);
  });

  it('does not apply chunker validation to other operators', () => {
    expect(shouldDisableSave('embeddings', {}, { chunk_type: 'simple', chunk_size: 1 })).toBe(false);
  });
});
