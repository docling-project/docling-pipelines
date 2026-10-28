import { describe, it, expect, vi } from 'vitest';
import { renderWithProviders } from '../../../../../utils/renderWithProviders';
import { screen } from '@testing-library/react';
import React from 'react';
import { BranchingPanelBody } from '@/components/PropertiesPanel/CustomPanels/Branching/Branching';
import type { ElyraController } from '@/types';

function makeController(appDataOverrides: Record<string, unknown> = {}): ElyraController {
  return {
    getAppData: vi.fn().mockReturnValue({ nodeId: 'branch-1', pipelineFlow: null, ...appDataOverrides }),
    getPropertyValue: vi.fn(),
    updatePropertyValue: vi.fn(),
    setSaveButtonDisable: vi.fn(),
  } as unknown as ElyraController;
}

describe('BranchingPanelBody', () => {
  it('renders empty state message when no link conditions exist', () => {
    renderWithProviders(<BranchingPanelBody controller={makeController()} />);
    expect(screen.getByText(/Connect output links from this node/)).toBeDefined();
  });

  it('renders table with Target Node and Link Name headers when conditions exist', () => {
    const flow = {
      pipelines: [{
        nodes: [
          {
            id: 'branch-1',
            op: 'branching',
            parameters: {
              link_conditions: [
                { link_id: 'lc-1', link_name: 'Branch A', target_node_id: 'node-2' },
              ],
            },
          },
          {
            id: 'node-2',
            op: 'chunker',
            app_data: { ui_data: { label: 'Chunker' } },
          },
        ],
      }],
    };
    renderWithProviders(<BranchingPanelBody controller={makeController({ nodeId: 'branch-1', pipelineFlow: flow })} />);
    expect(screen.getByText('Target Node')).toBeDefined();
    expect(screen.getByText('Link Name')).toBeDefined();
    expect(screen.getByText('Branch A')).toBeDefined();
  });

  it('shows "Chunker" as target node label', () => {
    const flow = {
      pipelines: [{
        nodes: [
          {
            id: 'branch-1',
            op: 'branching',
            parameters: {
              link_conditions: [
                { link_id: 'lc-2', link_name: 'Route X', target_node_id: 'tgt-1' },
              ],
            },
          },
          {
            id: 'tgt-1',
            op: 'chunker',
            app_data: { ui_data: { label: 'My Chunker' } },
          },
        ],
      }],
    };
    renderWithProviders(<BranchingPanelBody controller={makeController({ nodeId: 'branch-1', pipelineFlow: flow })} />);
    expect(screen.getByText('My Chunker')).toBeDefined();
  });
});
