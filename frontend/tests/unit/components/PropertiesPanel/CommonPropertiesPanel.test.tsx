import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import { CommonPropertiesPanel } from '@/components/PropertiesPanel/CommonPropertiesPanel';

function makeController(overrides: Record<string, unknown> = {}) {
  return {
    getAppData: vi.fn(() => ({
      nodeId: 'node-1',
      pipelineFlow: {
        pipelines: [{ nodes: [{ id: 'node-1', op: 'chunker', app_data: { ui_data: { label: 'Chunker' } } }] }],
      },
      nodeFeatureMap: {},
      featuresLoading: false,
      operatorMetadata: {},
      ...overrides,
    })),
    getPropertyValue: vi.fn(() => undefined),
    getPropertyValues: vi.fn(() => ({})),
    updatePropertyValue: vi.fn(),
    setSaveButtonDisable: vi.fn(),
    ...overrides,
  };
}

describe('CommonPropertiesPanel', () => {
  it('renders without crashing with a valid controller', () => {
    const controller = makeController();
    const { container } = renderWithProviders(
      <CommonPropertiesPanel controller={controller} />
    );
    expect(container).toBeTruthy();
  });

  it('renders the Configuration tab', () => {
    const controller = makeController();
    renderWithProviders(<CommonPropertiesPanel controller={controller} />);
    expect(screen.getByText('Configuration')).toBeDefined();
  });

  it('renders the Input tab', () => {
    const controller = makeController();
    renderWithProviders(<CommonPropertiesPanel controller={controller} />);
    expect(screen.getByText('Input')).toBeDefined();
  });

  it('renders the Output tab', () => {
    const controller = makeController();
    renderWithProviders(<CommonPropertiesPanel controller={controller} />);
    expect(screen.getByText('Output')).toBeDefined();
  });

  it('renders without crashing when controller is undefined', () => {
    const { container } = renderWithProviders(
      <CommonPropertiesPanel controller={undefined} />
    );
    expect(container).toBeTruthy();
  });
});
