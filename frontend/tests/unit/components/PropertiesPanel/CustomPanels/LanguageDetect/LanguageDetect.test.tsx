import { describe, it, expect, vi } from 'vitest';
import { renderWithProviders } from '../../../../../utils/renderWithProviders';
import { screen, fireEvent } from '@testing-library/react';
import { LanguageDetectPanelBody } from '@/components/PropertiesPanel/CustomPanels/LanguageDetect/LanguageDetect';

function makeController(overrides: Record<string, unknown> = {}) {
  return {
    getAppData: vi.fn(() => ({ operatorMetadata: {} })),
    getPropertyValue: vi.fn(() => undefined),
    updatePropertyValue: vi.fn(),
    ...overrides,
  };
}

describe('LanguageDetectPanelBody', () => {
  it('renders a provider dropdown', () => {
    const controller = makeController();
    renderWithProviders(<LanguageDetectPanelBody controller={controller} />);
    // Carbon Dropdown renders a button with the selected label
    expect(document.getElementById('language_provider')).not.toBeNull();
  });

  it('defaults to fasttext provider', () => {
    const controller = makeController();
    renderWithProviders(<LanguageDetectPanelBody controller={controller} />);
    // The selected item "fasttext" is displayed as button text
    expect(screen.getByText('fasttext')).toBeInTheDocument();
  });

  it('renders filter_unknown_language toggle', () => {
    const controller = makeController();
    renderWithProviders(<LanguageDetectPanelBody controller={controller} />);
    expect(document.getElementById('filter_unknown_language')).not.toBeNull();
  });

  it('toggle defaults to off (false)', () => {
    const controller = makeController();
    renderWithProviders(<LanguageDetectPanelBody controller={controller} />);
    const toggle = document.getElementById('filter_unknown_language') as HTMLInputElement;
    expect(toggle.checked).toBeFalsy();
  });

  it('calls updatePropertyValue when toggle is clicked', () => {
    const update = vi.fn();
    const controller = makeController({ updatePropertyValue: update });
    renderWithProviders(<LanguageDetectPanelBody controller={controller} />);
    const toggle = document.getElementById('filter_unknown_language') as HTMLElement;
    fireEvent.click(toggle);
    expect(update).toHaveBeenCalledWith({ name: 'filter_unknown_language' }, true);
  });

  it('uses stored provider value', () => {
    const controller = makeController({
      getPropertyValue: vi.fn((prop: { name: string }) =>
        prop.name === 'language_provider' ? 'langdetect' : undefined
      ),
    });
    renderWithProviders(<LanguageDetectPanelBody controller={controller} />);
    expect(screen.getByText('langdetect')).toBeInTheDocument();
  });

  it('renders Language detection provider label', () => {
    const controller = makeController();
    renderWithProviders(<LanguageDetectPanelBody controller={controller} />);
    const labels = screen.getAllByText('Language detection provider');
    expect(labels.length).toBeGreaterThan(0);
  });
});
