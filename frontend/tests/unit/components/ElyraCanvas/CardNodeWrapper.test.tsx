import { describe, it, expect } from 'vitest';
import { screen, render } from '@testing-library/react';
import { CardNodeWrapper } from '@/components/ElyraCanvas/CardNodeWrapper';

const SAMPLE_NODE = {
  op: 'chunker',
  label: 'Chunker',
  parameters: { display_label: 'My Chunker' },
  app_data: {
    react_nodes_data: {
      color: '#0f62fe',
      cardDescription: 'Splits documents into chunks',
    },
  },
};

describe('CardNodeWrapper', () => {
  it('renders the display label from parameters', () => {
    render(<CardNodeWrapper nodeData={SAMPLE_NODE} />);
    expect(screen.getByText('My Chunker')).toBeDefined();
  });

  it('renders the card description', () => {
    render(<CardNodeWrapper nodeData={SAMPLE_NODE} />);
    expect(screen.getByText('Splits documents into chunks')).toBeDefined();
  });

  it('falls back to node label when display_label is absent', () => {
    const node = { ...SAMPLE_NODE, parameters: {} };
    render(<CardNodeWrapper nodeData={node} />);
    expect(screen.getByText('Chunker')).toBeDefined();
  });

  it('renders the card-node wrapper div', () => {
    const { container } = render(<CardNodeWrapper nodeData={SAMPLE_NODE} />);
    expect(container.querySelector('.card-node')).toBeTruthy();
  });
});
