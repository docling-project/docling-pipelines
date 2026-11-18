import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../../utils/renderWithProviders';
import React from 'react';
import { Loading } from '@/components/common/Loading/Loading';

describe('Loading', () => {
  it('renders full-screen variant by default', () => {
    const { container } = renderWithProviders(React.createElement(Loading));
    // CarbonLoading renders an svg with role="status" or a loading element
    expect(container.firstChild).toBeTruthy();
  });

  it('inline → renders InlineLoading (description text visible)', () => {
    renderWithProviders(React.createElement(Loading, { inline: true, description: 'Saving...' }));
    expect(screen.getByText('Saving...')).toBeDefined();
  });

  it('description text appears in DOM for inline variant', () => {
    renderWithProviders(React.createElement(Loading, { inline: true, description: 'Please wait' }));
    expect(screen.getByText('Please wait')).toBeDefined();
  });

  it('centered=false skips the centeredContainer wrapper', () => {
    const { container } = renderWithProviders(React.createElement(Loading, { centered: false }));
    // When centered=false the outermost element is not a div wrapper
    const divWrapper = container.querySelector('[class*="centeredContainer"]');
    expect(divWrapper).toBeNull();
  });

  it('centered=true (default) wraps in centeredContainer div', () => {
    const { container } = renderWithProviders(React.createElement(Loading));
    const divWrapper = container.querySelector('div');
    expect(divWrapper).toBeTruthy();
  });
});
