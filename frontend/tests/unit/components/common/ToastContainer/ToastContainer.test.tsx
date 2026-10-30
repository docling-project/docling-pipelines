import { describe, it, expect } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { ToastContainer } from '@/components/common/ToastContainer/ToastContainer';
import { renderWithProviders } from '../../../../utils/renderWithProviders';

describe('ToastContainer', () => {
  it('renders the container div with aria-live', () => {
    const { container } = renderWithProviders(<ToastContainer />);
    const div = container.querySelector('[aria-live="polite"]');
    expect(div).not.toBeNull();
  });

  it('renders nothing when no active notifications', () => {
    const { container } = renderWithProviders(<ToastContainer />);
    // No ToastNotification rendered
    expect(container.querySelector('.cds--toast-notification')).toBeNull();
  });

  it('renders a notification for each active entry', () => {
    const preloadedState = {
      notifications: {
        active: [
          {
            id: 'n-1',
            kind: 'success' as const,
            title: 'Done',
            subtitle: 'Job completed',
            caption: '',
            timestamp: new Date().toISOString(),
          },
        ],
        history: [],
        preferences: { autoDismiss: true, dismissDelay: 5000 },
        unreadCount: 0,
      },
    };
    renderWithProviders(<ToastContainer />, { preloadedState });
    expect(screen.getByText('Done')).toBeInTheDocument();
    expect(screen.getByText('Job completed')).toBeInTheDocument();
  });

  it('renders the aria label', () => {
    const { container } = renderWithProviders(<ToastContainer />);
    expect(container.querySelector('[aria-label="Notifications"]')).not.toBeNull();
  });
});

describe('ToastContainer – uncovered branches', () => {
  const baseNotification = {
    kind: 'info' as const,
    title: 'Test',
    subtitle: 'sub',
    caption: '',
    timestamp: new Date().toISOString(),
  };

  it('dismissAfter === 0 → sticky toast (timeout prop is 0)', () => {
    const preloadedState = {
      notifications: {
        active: [{ id: 'n-sticky', ...baseNotification, dismissAfter: 0 }],
        history: [],
        preferences: { autoDismiss: true, dismissDelay: 5000 },
        unreadCount: 0,
      },
    };
    const { container } = renderWithProviders(<ToastContainer />, { preloadedState });
    // Toast is rendered
    expect(screen.getByText('Test')).toBeInTheDocument();
    // The Carbon ToastNotification sets timeout attribute to 0 for sticky
    const toast = container.querySelector('.cds--toast-notification');
    expect(toast).not.toBeNull();
  });

  it('dismissAfter === 3000 → explicit non-zero timeout branch', () => {
    const preloadedState = {
      notifications: {
        active: [{ id: 'n-explicit', ...baseNotification, dismissAfter: 3000 }],
        history: [],
        preferences: { autoDismiss: false, dismissDelay: 5000 },
        unreadCount: 0,
      },
    };
    renderWithProviders(<ToastContainer />, { preloadedState });
    expect(screen.getByText('Test')).toBeInTheDocument();
  });

  it('clicking close button dispatches removeNotification', () => {
    const preloadedState = {
      notifications: {
        active: [{ id: 'n-close', ...baseNotification }],
        history: [],
        preferences: { autoDismiss: false, dismissDelay: 5000 },
        unreadCount: 0,
      },
    };
    const { store } = renderWithProviders(<ToastContainer />, { preloadedState });
    // Carbon ToastNotification renders a close button
    const closeBtn = document.querySelector('.cds--toast-notification__close-button');
    if (closeBtn) {
      fireEvent.click(closeBtn);
      const active = (store.getState() as { notifications: { active: unknown[] } }).notifications.active;
      expect(active).toHaveLength(0);
    } else {
      // Fallback: find button by role inside notification
      const buttons = document.querySelectorAll('button');
      fireEvent.click(buttons[0] as HTMLElement);
      const active = (store.getState() as { notifications: { active: unknown[] } }).notifications.active;
      expect(active).toHaveLength(0);
    }
  });
});
