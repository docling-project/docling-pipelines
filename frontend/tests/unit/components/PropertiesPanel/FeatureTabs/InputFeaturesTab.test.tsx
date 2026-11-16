import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';

// SharedDataTable uses ResizeObserver + Carbon internals that are slow in jsdom
// under full-suite parallel load — raise timeout for this file.
vi.setConfig({ testTimeout: 15000 });

import { renderWithProviders } from '../../../../utils/renderWithProviders';
import { InputFeaturesTab } from '@/components/PropertiesPanel/FeatureTabs/InputFeaturesTab';
import type { FeatureAttributes } from '@/types';

const SAMPLE_FEATURES: Record<string, FeatureAttributes> = {
  content: { name: 'content', type: 'string', description: 'Document content', node_id: 'node-1', tags: [], available_for_filter: false, available_for_vector_db: false, mandatory_for_vector_db: false },
  doc_id:  { name: 'doc_id',  type: 'string', description: 'Document ID',      node_id: 'node-1', tags: [], available_for_filter: false, available_for_vector_db: false, mandatory_for_vector_db: false },
};

const SAMPLE_NODES = [
  { id: 'node-1', app_data: { ui_data: { label: 'Ingest' } } },
];

describe('InputFeaturesTab', () => {
  it('renders the tab description text', () => {
    renderWithProviders(
      <InputFeaturesTab
        nodeId="node-2"
        inputFeatures={SAMPLE_FEATURES}
        pipelineNodes={SAMPLE_NODES}
        isLoading={false}
      />
    );
    expect(screen.getAllByText(/upstream nodes/i).length).toBeGreaterThan(0);
  });

  it('renders feature names', () => {
    renderWithProviders(
      <InputFeaturesTab
        nodeId="node-2"
        inputFeatures={SAMPLE_FEATURES}
        pipelineNodes={SAMPLE_NODES}
        isLoading={false}
      />
    );
    expect(screen.getAllByText('content').length).toBeGreaterThan(0);
    expect(screen.getAllByText('doc_id').length).toBeGreaterThan(0);
  });

  it('shows empty state when no input features', () => {
    renderWithProviders(
      <InputFeaturesTab
        nodeId="node-1"
        inputFeatures={{}}
        pipelineNodes={SAMPLE_NODES}
        isLoading={false}
      />
    );
    expect(screen.getAllByText(/no input features/i).length).toBeGreaterThan(0);
  });

  it('renders without crashing while loading', () => {
    const { container } = renderWithProviders(
      <InputFeaturesTab
        nodeId="node-1"
        inputFeatures={{}}
        pipelineNodes={[]}
        isLoading={true}
      />
    );
    expect(container).toBeTruthy();
  });
});
