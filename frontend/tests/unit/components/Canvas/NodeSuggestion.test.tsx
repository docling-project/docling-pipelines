import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import NodeSuggestion from '@/components/Canvas/NodeSuggestion/NodeSuggestion';
import type { NodeSuggestionProps } from '@/components/Canvas/NodeSuggestion/NodeSuggestion';
import type { PaletteData } from '@/types/palette';

const SAMPLE_PALETTE: PaletteData = {
  categories: [
    {
      id: 'functional',
      label: 'Functional',
      node_types: [
        {
          id: 'chunker-node',
          op: 'chunker',
          app_data: { ui_data: { label: 'Chunker', description: 'Split documents' } },
        } as any,
        {
          id: 'embeddings-node',
          op: 'embeddings',
          app_data: { ui_data: { label: 'Embeddings', description: 'Generate embeddings' } },
        } as any,
      ],
    },
  ],
};

function renderSuggestion(props: Partial<NodeSuggestionProps> = {}) {
  const defaults: NodeSuggestionProps = {
    onClose: vi.fn(),
    onSelectNode: vi.fn(),
    position: { x: 100, y: 100 },
    paletteData: SAMPLE_PALETTE,
    ...props,
  };
  return { ...renderWithProviders(<NodeSuggestion {...defaults} />), ...defaults };
}

describe('NodeSuggestion', () => {
  it('renders the panel title', () => {
    renderSuggestion();
    expect(screen.getByText('Recommended next nodes')).toBeDefined();
  });

  it('renders operator names from palette', () => {
    renderSuggestion();
    expect(screen.getByText('Chunker')).toBeDefined();
    expect(screen.getByText('Embeddings')).toBeDefined();
  });

  it('clicking close button calls onClose', () => {
    const { onClose } = renderSuggestion();
    fireEvent.click(screen.getByRole('button', { name: /close/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('clicking a node calls onSelectNode with op code', () => {
    const { onSelectNode } = renderSuggestion();
    fireEvent.click(screen.getByText('Chunker'));
    expect(onSelectNode).toHaveBeenCalledWith('chunker');
  });

  it('search filters nodes', () => {
    renderSuggestion();
    const search = screen.getByPlaceholderText('Find nodes');
    fireEvent.change(search, { target: { value: 'embed' } });
    expect(screen.getByText('Embeddings')).toBeDefined();
    expect(screen.queryByText('Chunker')).toBeNull();
  });

  it('shows "No matching nodes" when search matches nothing', () => {
    renderSuggestion();
    const search = screen.getByPlaceholderText('Find nodes');
    fireEvent.change(search, { target: { value: 'zzznonexistent' } });
    expect(screen.getByText('No matching nodes')).toBeDefined();
  });

  it('renders empty state when palette has no categories', () => {
    renderSuggestion({ paletteData: { categories: [] } });
    expect(screen.getByText('No suggestions available')).toBeDefined();
  });

  it('renders connector when lineStart and lineEnd are provided', () => {
    renderSuggestion({ lineStart: { x: 50, y: 50 }, lineEnd: { x: 100, y: 50 } });
    // Connector renders an SVG and an img — just confirm no crash
    const svgs = document.querySelectorAll('svg');
    expect(svgs.length).toBeGreaterThan(0);
  });
});
