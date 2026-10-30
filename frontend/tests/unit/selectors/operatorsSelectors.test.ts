import { describe, it, expect } from 'vitest';
import {
  selectOperatorsMetadata,
  selectOperatorsLoading,
  selectOperatorsError,
  selectOperatorCount,
  selectOperatorsByCategory,
} from '@/selectors/operatorsSelectors';
import type { RootState } from '@/store';
import { buildPreloadedState } from '../../mocks/fixtures/store.fixture';

function makeState(overrides: Partial<RootState['operators']> = {}): RootState {
  return buildPreloadedState({
    operators: {
      metadata: {},
      loading: false,
      error: null,
      featureOptions: {},
      nodeFeatures: {},
      featuresLoading: false,
      ...overrides,
    },
  }) as RootState;
}

describe('operatorsSelectors', () => {
  it('selectOperatorsMetadata returns metadata dict', () => {
    const meta = { chunker: { short_name: 'chunker' } as never };
    expect(selectOperatorsMetadata(makeState({ metadata: meta }))).toEqual(meta);
  });

  it('selectOperatorsLoading returns loading flag', () => {
    expect(selectOperatorsLoading(makeState({ loading: true }))).toBe(true);
  });

  it('selectOperatorsError returns error string', () => {
    expect(selectOperatorsError(makeState({ error: 'oops' }))).toBe('oops');
  });

  it('selectOperatorCount counts metadata keys', () => {
    const meta = { a: {} as never, b: {} as never, c: {} as never };
    expect(selectOperatorCount(makeState({ metadata: meta }))).toBe(3);
  });

  it('selectOperatorsByCategory groups by category', () => {
    const meta = {
      chunker: { category: 'functional', short_name: 'chunker' } as never,
      embeddings: { category: 'functional', short_name: 'embeddings' } as never,
      extract: { category: 'extract', short_name: 'extract' } as never,
    };
    const grouped = selectOperatorsByCategory(makeState({ metadata: meta }));
    expect(grouped['functional']).toHaveLength(2);
    expect(grouped['extract']).toHaveLength(1);
  });
});
