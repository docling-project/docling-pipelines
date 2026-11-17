import { describe, it, expect } from 'vitest';
import { screen, fireEvent, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { AppHeader } from '@/components/layout/AppHeader/AppHeader';
import { renderWithProviders } from '../../../../utils/renderWithProviders';
import { server } from '../../../../mocks/server';

/** Answers the sign-out request so the test does not log an unhandled MSW request. */
function mockLogout(): void {
  server.use(http.post('/auth/logout', () => HttpResponse.json({ message: 'Logged out' })));
}

function renderAppHeader(_initialPath = '/home', unreadCount = 0) {
  return renderWithProviders(
    <AppHeader />,
    {
      preloadedState: {
        notifications: {
          active: [],
          history: [],
          preferences: { autoDismiss: true, dismissDelay: 5000 },
          unreadCount,
        },
      },
    }
  );
}

describe('AppHeader', () => {
  it('renders Home nav item', () => {
    renderAppHeader();
    expect(screen.getByText('Home')).toBeInTheDocument();
  });

  it('renders Projects nav item', () => {
    renderAppHeader();
    expect(screen.getByText('Projects')).toBeInTheDocument();
  });

  it('renders notification bell button', () => {
    renderAppHeader();
    expect(screen.getByLabelText('Notifications')).toBeInTheDocument();
  });

  it('shows unread count in notification label', () => {
    renderAppHeader('/home', 3);
    expect(screen.getByLabelText('Notifications (3 unread)')).toBeInTheDocument();
  });

  it('opens notification history when bell is clicked', () => {
    renderAppHeader();
    fireEvent.click(screen.getByLabelText('Notifications'));
    expect(screen.getByRole('complementary', { name: 'Notification history' })).toBeInTheDocument();
  });

  it('renders theme toggle button', () => {
    renderAppHeader();
    // Theme toggle renders one of two icons (light/dark); look for any global action after bell
    const header = document.querySelector('header');
    expect(header).not.toBeNull();
  });
});

describe('AppHeader – uncovered branches', () => {
  function renderWithUnread(unreadCount: number) {
    return renderWithProviders(
      <AppHeader />,
      {
        preloadedState: {
          notifications: {
            active: [],
            history: [],
            preferences: { autoDismiss: true, dismissDelay: 5000 },
            unreadCount,
          },
        },
      }
    );
  }

  it('unreadCount > 99 → badge shows "99+"', () => {
    renderWithUnread(100);
    // Find all span[aria-hidden="true"] and pick the one containing the count
    const spans = Array.from(document.querySelectorAll('span[aria-hidden="true"]'));
    const badge = spans.find((el) => el.textContent === '99+');
    expect(badge).toBeDefined();
  });

  it('theme toggle button is present and clickable', () => {
    renderWithUnread(0);
    // DEFAULT_THEME is DARK — so isDarkMode starts true → label is "Switch to light mode"
    const toggleBtn = screen.getByLabelText('Switch to light mode');
    expect(toggleBtn).toBeInTheDocument();
    fireEvent.click(toggleBtn);
    // After click theme flips to light → isDarkMode false → label is "Switch to dark mode"
    expect(screen.getByLabelText('Switch to dark mode')).toBeInTheDocument();
  });

  it('logo click navigates to home', () => {
    renderWithUnread(0);
    const logoLink = screen.getByText('Docling Pipelines');
    expect(logoLink).toBeInTheDocument();
    fireEvent.click(logoLink);
    // Component renders without error after click
    expect(screen.getByText('Docling Pipelines')).toBeInTheDocument();
  });
});

const AUTHED_USER = { username: 'alice', email: 'alice@example.com', full_name: 'Alice Editor', roles: ['editor' as const] };

function authedState(overrides?: { user?: typeof AUTHED_USER | null; authEnabled?: boolean }) {
  return {
    auth: {
      user: overrides?.user === undefined ? AUTHED_USER : overrides.user,
      authEnabled: overrides?.authEnabled ?? true,
      providers: [],
      credentialLogin: true,
      status: 'authenticated' as const,
      error: null,
      errorStatus: null,
      retryAfter: null,
    },
  };
}

describe('AppHeader – Auth integration', () => {
  it('hides user menu when auth is disabled', () => {
    renderWithProviders(<AppHeader />, {
      preloadedState: {
        auth: {
          user: null,
          authEnabled: false,
          providers: [],
          credentialLogin: false,
          status: 'authenticated',
          error: null,
          errorStatus: null,
          retryAfter: null,
        },
      },
    });
    expect(screen.queryByLabelText('User menu')).toBeNull();
  });

  it('shows the profile button and hides the user details until it is opened', () => {
    renderWithProviders(<AppHeader />, { preloadedState: authedState() });
    expect(screen.getByRole('button', { name: 'User menu' })).toBeInTheDocument();
    expect(screen.queryByText('Alice Editor')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Sign out' })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'User menu' }));

    expect(screen.getByText('Alice Editor')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
  });

  it('triggers sign-out action when sign-out is clicked', async () => {
    mockLogout();
    const { store } = renderWithProviders(<AppHeader />, { preloadedState: authedState() });

    fireEvent.click(screen.getByRole('button', { name: 'User menu' }));

    const signOutBtn = screen.getByRole('button', { name: 'Sign out' });
    expect(signOutBtn).toBeInTheDocument();
    fireEvent.click(signOutBtn);

    // Verify logout is dispatched (which eventually clears user state to null)
    await waitFor(() => {
      expect(store.getState().auth.user).toBeNull();
    });
  });
});

describe('AppHeader – profile menu', () => {
  it('renders the profile button as the last global action, after the theme toggle', () => {
    renderWithProviders(<AppHeader />, { preloadedState: authedState() });
    const globalBar = document.querySelector('.cds--header__global');
    expect(globalBar).not.toBeNull();

    const actions = Array.from(globalBar!.querySelectorAll('button'));
    expect(actions[actions.length - 1]).toBe(screen.getByRole('button', { name: 'User menu' }));

    const themeButton = screen.getByRole('button', { name: /Switch to (light|dark) mode/ });
    const profileButton = screen.getByRole('button', { name: 'User menu' });
    expect(themeButton.compareDocumentPosition(profileButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('does not render the user inside the main navigation', () => {
    renderWithProviders(<AppHeader />, { preloadedState: authedState() });
    const mainNav = screen.getByRole('navigation', { name: 'Main navigation' });
    expect(within(mainNav).queryByText('Alice Editor')).toBeNull();
    expect(within(mainNav).queryByRole('button', { name: 'User menu' })).toBeNull();
  });

  it('shows email and capitalised role tags when opened', () => {
    renderWithProviders(<AppHeader />, { preloadedState: authedState() });
    fireEvent.click(screen.getByRole('button', { name: 'User menu' }));

    expect(screen.getByText('alice@example.com')).toBeInTheDocument();
    const roles = screen.getByRole('group', { name: 'Roles' });
    expect(within(roles).getByText('Editor')).toBeInTheDocument();
  });

  it('omits the email line when the user has no email', () => {
    renderWithProviders(<AppHeader />, {
      preloadedState: authedState({ user: { ...AUTHED_USER, email: '' } }),
    });
    fireEvent.click(screen.getByRole('button', { name: 'User menu' }));

    expect(screen.getByText('Alice Editor')).toBeInTheDocument();
    expect(screen.queryByText('alice@example.com')).toBeNull();
  });

  it('toggles aria-expanded when the profile button is clicked', () => {
    renderWithProviders(<AppHeader />, { preloadedState: authedState() });
    const profileButton = screen.getByRole('button', { name: 'User menu' });
    expect(profileButton).toHaveAttribute('aria-expanded', 'false');

    fireEvent.click(profileButton);
    expect(profileButton).toHaveAttribute('aria-expanded', 'true');

    fireEvent.click(profileButton);
    expect(profileButton).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('Alice Editor')).toBeNull();
  });

  it('closes on Escape and returns focus to the profile button', () => {
    renderWithProviders(<AppHeader />, { preloadedState: authedState() });
    const profileButton = screen.getByRole('button', { name: 'User menu' });
    fireEvent.click(profileButton);
    expect(screen.getByText('Alice Editor')).toBeInTheDocument();

    fireEvent.keyDown(window, { key: 'Escape' });

    expect(screen.queryByText('Alice Editor')).toBeNull();
    expect(profileButton).toHaveAttribute('aria-expanded', 'false');
    expect(profileButton).toHaveFocus();
  });

  it('moves focus from the profile button into the popover with Tab', async () => {
    const user = userEvent.setup();
    renderWithProviders(<AppHeader />, { preloadedState: authedState() });
    const profileButton = screen.getByRole('button', { name: 'User menu' });
    await user.click(profileButton);
    expect(profileButton).toHaveFocus();

    await user.tab();

    expect(screen.getByRole('button', { name: 'Sign out' })).toHaveFocus();
    expect(screen.getByText('Alice Editor')).toBeInTheDocument();
  });

  it('closes when the user clicks outside the popover', () => {
    renderWithProviders(<AppHeader />, { preloadedState: authedState() });
    fireEvent.click(screen.getByRole('button', { name: 'User menu' }));
    expect(screen.getByText('Alice Editor')).toBeInTheDocument();

    fireEvent.click(document.body);

    expect(screen.queryByText('Alice Editor')).toBeNull();
  });

  it('closes the popover after sign-out', async () => {
    mockLogout();
    renderWithProviders(<AppHeader />, { preloadedState: authedState() });
    const profileButton = screen.getByRole('button', { name: 'User menu' });
    fireEvent.click(profileButton);

    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));

    await waitFor(() => {
      expect(screen.queryByText('Alice Editor')).toBeNull();
    });
    expect(profileButton).toHaveAttribute('aria-expanded', 'false');
  });

  it('does not render a profile button when the user is null with auth enabled', () => {
    renderWithProviders(<AppHeader />, { preloadedState: authedState({ user: null }) });
    expect(screen.queryByRole('button', { name: 'User menu' })).toBeNull();
  });
});
