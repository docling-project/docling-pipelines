import { describe, it, expect, vi } from 'vitest';
import { renderWithProviders } from '../../../../../utils/renderWithProviders';
import { screen, fireEvent } from '@testing-library/react';
import { EntityCurationPanelBody } from '@/components/PropertiesPanel/CustomPanels/EntityCuration/EntityCuration';

function makeController(overrides: Record<string, unknown> = {}) {
  return {
    getAppData: vi.fn(() => ({ operatorMetadata: {} })),
    getPropertyValue: vi.fn(() => undefined),
    updatePropertyValue: vi.fn(),
    ...overrides,
  };
}

describe('EntityCurationPanelBody', () => {
  it('renders entities_column input', () => {
    renderWithProviders(<EntityCurationPanelBody controller={makeController()} />);
    expect(document.getElementById('entities_column')).not.toBeNull();
  });

  it('renders document_type_column input', () => {
    renderWithProviders(<EntityCurationPanelBody controller={makeController()} />);
    expect(document.getElementById('document_type_column')).not.toBeNull();
  });

  it('renders Entities column label', () => {
    renderWithProviders(<EntityCurationPanelBody controller={makeController()} />);
    expect(screen.getAllByText('Entities column').length).toBeGreaterThan(0);
  });

  it('renders Document type column label', () => {
    renderWithProviders(<EntityCurationPanelBody controller={makeController()} />);
    expect(screen.getAllByText('Document type column').length).toBeGreaterThan(0);
  });

  it('uses stored entities_column value', () => {
    const controller = makeController({
      getPropertyValue: vi.fn((p: { name: string }) =>
        p.name === 'entities_column' ? 'my_entities' : undefined
      ),
    });
    renderWithProviders(<EntityCurationPanelBody controller={controller} />);
    const input = document.getElementById('entities_column') as HTMLInputElement;
    expect(input.value).toBe('my_entities');
  });

  it('calls updatePropertyValue on entities_column change', () => {
    const update = vi.fn();
    renderWithProviders(<EntityCurationPanelBody controller={makeController({ updatePropertyValue: update })} />);
    const input = document.getElementById('entities_column') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'ents' } });
    expect(update).toHaveBeenCalledWith({ name: 'entities_column' }, 'ents');
  });

  it('calls updatePropertyValue on document_type_column change', () => {
    const update = vi.fn();
    renderWithProviders(<EntityCurationPanelBody controller={makeController({ updatePropertyValue: update })} />);
    const input = document.getElementById('document_type_column') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'doc_type' } });
    expect(update).toHaveBeenCalledWith({ name: 'document_type_column' }, 'doc_type');
  });
});
