import { describe, it, expect, vi } from 'vitest';
import { renderWithProviders } from '../../../../../utils/renderWithProviders';
import { screen, fireEvent } from '@testing-library/react';
import { MlEnrichmentPanelBody } from '@/components/PropertiesPanel/CustomPanels/MlEnrichment/MlEnrichment';

function makeController(overrides: Record<string, unknown> = {}) {
  return {
    getAppData: vi.fn(() => ({ operatorMetadata: {} })),
    getPropertyValue: vi.fn(() => undefined),
    updatePropertyValue: vi.fn(),
    ...overrides,
  };
}

describe('MlEnrichmentPanelBody', () => {
  it('renders output_column_prefix input', () => {
    renderWithProviders(<MlEnrichmentPanelBody controller={makeController()} />);
    expect(document.getElementById('output_column_prefix')).not.toBeNull();
  });

  it('defaults to empty string when no stored value', () => {
    renderWithProviders(<MlEnrichmentPanelBody controller={makeController()} />);
    const input = document.getElementById('output_column_prefix') as HTMLInputElement;
    expect(input.value).toBe('');
  });

  it('uses stored value', () => {
    const controller = makeController({
      getPropertyValue: vi.fn((p: { name: string }) =>
        p.name === 'output_column_prefix' ? 'ml_' : undefined
      ),
    });
    renderWithProviders(<MlEnrichmentPanelBody controller={controller} />);
    const input = document.getElementById('output_column_prefix') as HTMLInputElement;
    expect(input.value).toBe('ml_');
  });

  it('calls updatePropertyValue on change', () => {
    const update = vi.fn();
    renderWithProviders(<MlEnrichmentPanelBody controller={makeController({ updatePropertyValue: update })} />);
    const input = document.getElementById('output_column_prefix') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'prefix_' } });
    expect(update).toHaveBeenCalledWith({ name: 'output_column_prefix' }, 'prefix_');
  });

  it('renders Output column prefix label', () => {
    renderWithProviders(<MlEnrichmentPanelBody controller={makeController()} />);
    expect(screen.getAllByText('Output column prefix').length).toBeGreaterThan(0);
  });
});
