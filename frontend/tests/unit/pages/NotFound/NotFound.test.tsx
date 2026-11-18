import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import { NotFound } from '@/pages/NotFound/NotFound';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

describe('NotFound page', () => {
  it('renders "Page not found" heading', () => {
    renderWithProviders(<NotFound />);
    // Carbon NotFoundEmptyState injects a <title> as well — use getAllByText
    const headings = screen.getAllByText('Page not found');
    expect(headings.length).toBeGreaterThan(0);
  });

  it('renders "Go to Home" action button', () => {
    renderWithProviders(<NotFound />);
    expect(screen.getByText('Go to Home')).toBeDefined();
  });

  it('renders subtitle about page not existing', () => {
    renderWithProviders(<NotFound />);
    expect(
      screen.getByText('The page you are looking for does not exist or has been moved.')
    ).toBeDefined();
  });

  it('navigates to home when "Go to Home" action is clicked', () => {
    mockNavigate.mockClear();
    renderWithProviders(<NotFound />);
    const btn = Array.from(document.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === 'Go to Home'
    );
    if (btn) { fireEvent.click(btn); }
    expect(mockNavigate).toHaveBeenCalledWith('/home');
  });
});
