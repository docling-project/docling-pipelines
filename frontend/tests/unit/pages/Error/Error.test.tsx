import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import { Error } from '@/pages/Error/Error';

describe('Error page', () => {
  it('renders "Something went wrong" heading by default (500)', () => {
    renderWithProviders(<Error />);
    // Carbon ErrorEmptyState injects a <title> as well — use getAllByText
    const headings = screen.getAllByText('Something went wrong');
    expect(headings.length).toBeGreaterThan(0);
  });

  it('renders "Go to Home" action button', () => {
    renderWithProviders(<Error />);
    expect(screen.getByText('Go to Home')).toBeDefined();
  });

  it('renders default error message as subtitle', () => {
    renderWithProviders(<Error />);
    expect(screen.getByText('An unexpected error occurred')).toBeDefined();
  });

  it('renders "Page not found" title when statusCode is 404', () => {
    renderWithProviders(<Error />, {
      initialEntries: [{ pathname: '/error', state: { statusCode: 404, message: 'Custom 404 message' } } as never],
    });
    const headings = screen.getAllByText('Page not found');
    expect(headings.length).toBeGreaterThan(0);
  });
});
