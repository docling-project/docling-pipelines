import { describe, it, expect } from 'vitest';
import { enhancePalette, getIconForOperator } from '@/utils/paletteEnhancer';
import type { PaletteData } from '@/types/palette';

const makePalette = (nodeTypes: Array<{ op: string; label?: string }>): PaletteData => ({
  categories: [
    {
      id: 'test-category',
      label: 'Test',
      node_types: nodeTypes.map((n) => ({
        op: n.op,
        label: n.label ?? n.op,
        id: `id-${n.op}`,
        type: 'execution_node',
        inputs: [],
        outputs: [],
        app_data: {
          ui_data: {},
        },
      })),
    },
  ],
} as unknown as PaletteData);

describe('paletteEnhancer', () => {
  describe('getIconForOperator', () => {
    it('returns a React element for a known operator', () => {
      const icon = getIconForOperator('chunker');
      expect(icon).toBeTruthy();
      expect(typeof icon).toBe('object');
    });

    it('unknown operator → does not throw; returns a fallback icon', () => {
      expect(() => getIconForOperator('totally_unknown_op')).not.toThrow();
      const icon = getIconForOperator('totally_unknown_op');
      expect(icon).toBeTruthy();
    });
  });

  describe('enhancePalette', () => {
    it('returns palette with same category count as input', () => {
      const palette = makePalette([{ op: 'chunker' }, { op: 'embeddings' }]);
      const enhanced = enhancePalette(palette);
      expect(enhanced.categories).toHaveLength(palette.categories.length);
    });

    it('returns palette with same node count as input', () => {
      const nodes = [{ op: 'chunker' }, { op: 'embeddings' }, { op: 'noop' }];
      const palette = makePalette(nodes);
      const enhanced = enhancePalette(palette);
      expect(enhanced.categories[0]?.node_types).toHaveLength(nodes.length);
    });

    it('adds react_nodes_data.color to each node type', () => {
      const palette = makePalette([{ op: 'chunker' }]);
      const enhanced = enhancePalette(palette);
      const nodeType = enhanced.categories[0]?.node_types[0];
      expect((nodeType?.app_data as Record<string, unknown>)['react_nodes_data']).toBeTruthy();
    });

    it('adds ui_data.image (icon) to each node type', () => {
      const palette = makePalette([{ op: 'vectordb' }]);
      const enhanced = enhancePalette(palette);
      const nodeType = enhanced.categories[0]?.node_types[0];
      const uiData = ((nodeType?.app_data as Record<string, unknown>)['ui_data']) as Record<string, unknown>;
      expect(uiData['image']).toBeTruthy();
    });

    it('unknown operator does not throw during enhance', () => {
      const palette = makePalette([{ op: 'unknown_op_xyz' }]);
      expect(() => enhancePalette(palette)).not.toThrow();
    });
  });
});
