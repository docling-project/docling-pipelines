import { describe, it, expect } from 'vitest';
import { renderWithProviders } from '../../../../utils/renderWithProviders';
import { Breadcrumb } from '@/components/common/Breadcrumb/Breadcrumb';

describe('Breadcrumb', () => {
  it('renders null on top-level /projects route with no actions', () => {
    const { container } = renderWithProviders(<Breadcrumb />, {
      initialEntries: ['/projects'],
    });
    expect(container.firstChild).toBeNull();
  });

  it('renders null on /home route', () => {
    const { container } = renderWithProviders(<Breadcrumb />, {
      initialEntries: ['/home'],
    });
    expect(container.firstChild).toBeNull();
  });

  it('renders without crashing on /projects/:id route', () => {
    // /projects/abc-123 has only one crumb (the project itself), which is the
    // current page and gets sliced off — component returns null. Just ensure no crash.
    const { container } = renderWithProviders(<Breadcrumb />, {
      initialEntries: ['/projects/abc-123'],
    });
    expect(container).toBeTruthy();
  });

  it('renders null on unknown route when no parent crumbs resolve', () => {
    const { container } = renderWithProviders(<Breadcrumb />, {
      initialEntries: ['/unknown-route-xyz'],
    });
    expect(container.firstChild).toBeNull();
  });
});
