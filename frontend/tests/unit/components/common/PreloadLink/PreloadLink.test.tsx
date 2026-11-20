import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { PreloadLink } from '@/components/common/PreloadLink';

// Mock useRoutePreload
const mockPreload = vi.fn();
vi.mock('@/hooks', () => ({
  useRoutePreload: () => ({ preload: mockPreload }),
}));

describe('PreloadLink', () => {
  it('renders an anchor with the correct href', () => {
    render(
      <MemoryRouter>
        <PreloadLink to="/projects">Go to Projects</PreloadLink>
      </MemoryRouter>
    );
    expect(screen.getByText('Go to Projects')).toBeInTheDocument();
  });

  it('calls preloadRoute on mouse enter', () => {
    render(
      <MemoryRouter>
        <PreloadLink to="/projects">Projects</PreloadLink>
      </MemoryRouter>
    );
    fireEvent.mouseEnter(screen.getByText('Projects'));
    expect(mockPreload).toHaveBeenCalledWith('/projects');
  });

  it('calls preloadRoute on focus', () => {
    render(
      <MemoryRouter>
        <PreloadLink to="/flows">Flows</PreloadLink>
      </MemoryRouter>
    );
    fireEvent.focus(screen.getByText('Flows'));
    expect(mockPreload).toHaveBeenCalledWith('/flows');
  });

  it('does not call preloadRoute when preload=false', () => {
    mockPreload.mockClear();
    render(
      <MemoryRouter>
        <PreloadLink to="/projects" preload={false}>No Preload</PreloadLink>
      </MemoryRouter>
    );
    fireEvent.mouseEnter(screen.getByText('No Preload'));
    expect(mockPreload).not.toHaveBeenCalled();
  });

  it('renders children correctly', () => {
    render(
      <MemoryRouter>
        <PreloadLink to="/home"><span data-testid="child">Child</span></PreloadLink>
      </MemoryRouter>
    );
    expect(screen.getByTestId('child')).toBeInTheDocument();
  });
});
