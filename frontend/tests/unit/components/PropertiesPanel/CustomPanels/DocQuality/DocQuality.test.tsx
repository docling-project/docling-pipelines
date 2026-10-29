import { describe, it, expect } from 'vitest';
import { renderWithProviders } from '../../../../../utils/renderWithProviders';
import { screen } from '@testing-library/react';
import { DocQualityPanelBody } from '@/components/PropertiesPanel/CustomPanels/DocQuality/DocQuality';

function makeController() {
  return {
    getAppData: () => ({ operatorMetadata: {} }),
    getPropertyValue: () => undefined,
    updatePropertyValue: () => undefined,
  };
}

describe('DocQualityPanelBody', () => {
  it('renders without crashing', () => {
    const { container } = renderWithProviders(<DocQualityPanelBody controller={makeController()} />);
    expect(container).toBeInTheDocument();
  });

  it('renders the "No configuration required" inline notification', () => {
    renderWithProviders(<DocQualityPanelBody controller={makeController()} />);
    expect(screen.getByText(/No configuration required/i)).toBeInTheDocument();
  });

  it('renders the notification subtitle', () => {
    renderWithProviders(<DocQualityPanelBody controller={makeController()} />);
    expect(
      screen.getByText(/automatically computes document quality metrics/i)
    ).toBeInTheDocument();
  });

  it('renders with null controller', () => {
    const { container } = renderWithProviders(<DocQualityPanelBody controller={null} />);
    expect(container).toBeInTheDocument();
  });

  it('does not render a text_lang input', () => {
    renderWithProviders(<DocQualityPanelBody controller={makeController()} />);
    expect(document.getElementById('text_lang')).toBeNull();
  });
});
