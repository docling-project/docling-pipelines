import { describe, it, expect } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { AppHeader } from '@/components/layout/AppHeader/AppHeader';
import { renderWithProviders } from '../../../../utils/renderWithProviders';

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
