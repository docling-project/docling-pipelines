import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { NotificationHistory } from '@/components/common/NotificationHistory';
import { renderWithProviders } from '../../../../utils/renderWithProviders';

const emptyState = {
  notifications: {
    active: [],
    history: [],
    preferences: { autoDismiss: true, dismissDelay: 5000 },
    unreadCount: 0,
  },
};

describe('NotificationHistory', () => {
  it('returns null when open is false', () => {
    const { container } = renderWithProviders(
      <NotificationHistory open={false} onClose={vi.fn()} />,
      { preloadedState: emptyState }
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders the panel when open is true', () => {
    renderWithProviders(
      <NotificationHistory open onClose={vi.fn()} />,
      { preloadedState: emptyState }
    );
    expect(screen.getByRole('complementary', { name: 'Notification history' })).toBeInTheDocument();
  });

  it('shows empty message when no history', () => {
    renderWithProviders(
      <NotificationHistory open onClose={vi.fn()} />,
      { preloadedState: emptyState }
    );
    expect(screen.getByText('No notifications yet.')).toBeInTheDocument();
  });

  it('renders history items', () => {
    const preloadedState = {
      notifications: {
        active: [],
        history: [
          {
            id: 'h-1',
            kind: 'error' as const,
            title: 'Something failed',
            subtitle: 'Details here',
            caption: '',
            timestamp: new Date().toISOString(),
          },
        ],
        preferences: { autoDismiss: true, dismissDelay: 5000 },
        unreadCount: 0,
      },
    };
    renderWithProviders(
      <NotificationHistory open onClose={vi.fn()} />,
      { preloadedState }
    );
    expect(screen.getByText('Something failed')).toBeInTheDocument();
  });

  it('calls onClose when close button clicked', () => {
    const onClose = vi.fn();
    renderWithProviders(
      <NotificationHistory open onClose={onClose} />,
      { preloadedState: emptyState }
    );
    const closeBtn = screen.getByLabelText('Close notification history');
    fireEvent.click(closeBtn);
    expect(onClose).toHaveBeenCalled();
  });
});
