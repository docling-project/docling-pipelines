import { describe, it, expect, vi } from 'vitest';
import { renderWithProviders } from '../../../../../utils/renderWithProviders';
import { screen, fireEvent } from '@testing-library/react';
import { RedactionPanelBody } from '@/components/PropertiesPanel/CustomPanels/Redaction/Redaction';

function makeController(overrides: Record<string, unknown> = {}) {
  return {
    getAppData: vi.fn(() => ({ operatorMetadata: {} })),
    getPropertyValue: vi.fn(() => undefined),
    updatePropertyValue: vi.fn(),
    ...overrides,
  };
}

describe('RedactionPanelBody', () => {
  it('renders redaction_regex input', () => {
    const controller = makeController();
    renderWithProviders(<RedactionPanelBody controller={controller} />);
    expect(document.getElementById('redaction_regex')).not.toBeNull();
  });

  it('renders redaction_masking_character input', () => {
    const controller = makeController();
    renderWithProviders(<RedactionPanelBody controller={controller} />);
    expect(document.getElementById('redaction_masking_character')).not.toBeNull();
  });

  it('defaults masking character to *', () => {
    const controller = makeController();
    renderWithProviders(<RedactionPanelBody controller={controller} />);
    const input = document.getElementById('redaction_masking_character') as HTMLInputElement;
    expect(input.value).toBe('*');
  });

  it('defaults redaction_regex to empty string', () => {
    const controller = makeController();
    renderWithProviders(<RedactionPanelBody controller={controller} />);
    const input = document.getElementById('redaction_regex') as HTMLInputElement;
    expect(input.value).toBe('');
  });

  it('uses stored redaction_regex value', () => {
    const controller = makeController({
      getPropertyValue: vi.fn((prop: { name: string }) =>
        prop.name === 'redaction_regex' ? '\\bSSN\\b' : undefined
      ),
    });
    renderWithProviders(<RedactionPanelBody controller={controller} />);
    const input = document.getElementById('redaction_regex') as HTMLInputElement;
    expect(input.value).toBe('\\bSSN\\b');
  });

  it('calls updatePropertyValue for redaction_regex change', () => {
    const update = vi.fn();
    const controller = makeController({ updatePropertyValue: update });
    renderWithProviders(<RedactionPanelBody controller={controller} />);
    const input = document.getElementById('redaction_regex') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'secret' } });
    expect(update).toHaveBeenCalledWith({ name: 'redaction_regex' }, 'secret');
  });

  it('calls updatePropertyValue for masking_character change', () => {
    const update = vi.fn();
    const controller = makeController({ updatePropertyValue: update });
    renderWithProviders(<RedactionPanelBody controller={controller} />);
    const input = document.getElementById('redaction_masking_character') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '#' } });
    expect(update).toHaveBeenCalledWith({ name: 'redaction_masking_character' }, '#');
  });

  it('masking character input has maxLength of 1', () => {
    const controller = makeController();
    renderWithProviders(<RedactionPanelBody controller={controller} />);
    const input = document.getElementById('redaction_masking_character') as HTMLInputElement;
    expect(input.maxLength).toBe(1);
  });
});
