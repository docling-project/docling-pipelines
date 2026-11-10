import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import { Home } from '@/pages/Home/Home';
import { authStateFixture } from '../../../mocks/fixtures/store.fixture';

// AnimatedHeader does not render its tiles under jsdom: render the selected group's tile content directly.
vi.mock('@carbon-labs/react-animated-header', () => ({
  AnimatedHeader: ({ selectedTileGroup }: { selectedTileGroup?: { tiles: { tileId: string; customContent: React.ReactNode }[] } }) => (
    <div>
      {selectedTileGroup?.tiles.map((tile) => <div key={tile.tileId}>{tile.customContent}</div>)}
    </div>
  ),
  watsonXAnimatedLight: {},
  watsonXStaticLight: '',
  watsonXAnimatedDark: {},
  watsonXStaticDark: '',
}));

describe('Home page permission gating', () => {
  it('disables the sample project button for a viewer and explains why', () => {
    renderWithProviders(<Home />, { preloadedState: { auth: authStateFixture({ role: 'viewer' }) } });
    expect(screen.getByRole('button', { name: 'Start' })).toBeDisabled();
    expect(
      screen.getAllByText('You need the editor role to do this', { selector: '[role="tooltip"] *' }).length
    ).toBeGreaterThan(0);
  });

  it.each(['editor', 'admin'] as const)('enables the sample project button for %s', (role) => {
    renderWithProviders(<Home />, { preloadedState: { auth: authStateFixture({ role }) } });
    expect(screen.getByRole('button', { name: 'Start' })).not.toBeDisabled();
  });

  it('keeps the documentation tile enabled for a viewer', () => {
    renderWithProviders(<Home />, { preloadedState: { auth: authStateFixture({ role: 'viewer' }) } });
    expect(screen.getByText('Learn more', { selector: 'a' })).toHaveAttribute('href');
  });

  it('disables the ProjectsCard create actions for a viewer', async () => {
    renderWithProviders(<Home />, { preloadedState: { auth: authStateFixture({ role: 'viewer' }) } });
    const header = document.querySelector('[class*="cardHeaderAction"] .cds--btn--icon-only') as HTMLElement;
    expect(header).toBeDisabled();
  });
});
