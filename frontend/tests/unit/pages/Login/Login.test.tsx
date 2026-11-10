import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import { Login } from '@/pages/Login/Login';

// Mock window.location.assign
const mockAssign = vi.fn();
Object.defineProperty(window, 'location', {
  value: { assign: mockAssign },
  writable: true,
});

describe('Login page', () => {
  beforeEach(() => {
    mockAssign.mockClear();
  });

  it('renders correctly when credential login is available', () => {
    renderWithProviders(<Login />, {
      preloadedState: {
        auth: {
          user: null,
          authEnabled: true,
          providers: [],
          credentialLogin: true,
          status: 'unauthenticated',
          error: null,
          errorStatus: null,
          retryAfter: null,
        },
      },
    });

    expect(screen.getByText('Docling Pipelines')).toBeDefined();
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeDefined();
    expect(screen.getByLabelText('Username')).toBeDefined();
    expect(screen.getByLabelText('Password')).toBeDefined();
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeDefined();
  });

  it('shows error if submitted with empty fields', async () => {
    renderWithProviders(<Login />, {
      preloadedState: {
        auth: {
          user: null,
          authEnabled: true,
          providers: [],
          credentialLogin: true,
          status: 'unauthenticated',
          error: null,
          errorStatus: null,
          retryAfter: null,
        },
      },
    });

    const submitBtn = screen.getByRole('button', { name: 'Sign in' });
    fireEvent.click(submitBtn);

    expect(screen.getAllByText('This field is required')).toHaveLength(2);
  });

  it('shows server error when 401 occurs', () => {
    renderWithProviders(<Login />, {
      preloadedState: {
        auth: {
          user: null,
          authEnabled: true,
          providers: [],
          credentialLogin: true,
          status: 'unauthenticated',
          error: 'Invalid credentials',
          errorStatus: 401,
          retryAfter: null,
        },
      },
    });

    expect(screen.getByText('Invalid credentials')).toBeDefined();
  });

  it('shows retry later message on 429 error', () => {
    renderWithProviders(<Login />, {
      preloadedState: {
        auth: {
          user: null,
          authEnabled: true,
          providers: [],
          credentialLogin: true,
          status: 'unauthenticated',
          error: 'Too many requests',
          errorStatus: 429,
          retryAfter: 60,
        },
      },
    });

    expect(screen.getByText('Too many failed attempts. Please retry later.')).toBeDefined();
  });

  it('shows no sign-in method configured warning when neither is available', () => {
    renderWithProviders(<Login />, {
      preloadedState: {
        auth: {
          user: null,
          authEnabled: true,
          providers: [],
          credentialLogin: false,
          status: 'unauthenticated',
          error: null,
          errorStatus: null,
          retryAfter: null,
        },
      },
    });

    expect(screen.getByText('No sign-in method is currently configured.')).toBeDefined();
  });

  it('hides form and shows provider buttons when OIDC is configured and credentials disabled', () => {
    renderWithProviders(<Login />, {
      preloadedState: {
        auth: {
          user: null,
          authEnabled: true,
          providers: [{ name: 'google', display_name: 'Google', authorize_url: '/auth/oauth2/authorize?provider=google' }],
          credentialLogin: false,
          status: 'unauthenticated',
          error: null,
          errorStatus: null,
          retryAfter: null,
        },
      },
    });

    expect(screen.queryByLabelText('Username')).toBeNull();
    expect(screen.getByText('Sign in with Google')).toBeDefined();
  });

  it('navigates to authorize URL with return_to parameter when provider is selected', () => {
    renderWithProviders(<Login />, {
      initialEntries: ['/login?return_to=%2Fflows%2F123'],
      preloadedState: {
        auth: {
          user: null,
          authEnabled: true,
          providers: [{ name: 'google', display_name: 'Google', authorize_url: '/auth/oauth2/authorize?provider=google' }],
          credentialLogin: false,
          status: 'unauthenticated',
          error: null,
          errorStatus: null,
          retryAfter: null,
        },
      },
    });

    const btn = screen.getByRole('button', { name: 'Sign in with Google' });
    fireEvent.click(btn);

    expect(mockAssign).toHaveBeenCalledWith('/auth/oauth2/authorize?provider=google&return_to=%2Fflows%2F123');
  });

  it('has error notification with alert role for accessibility', () => {
    renderWithProviders(<Login />, {
      preloadedState: {
        auth: {
          user: null,
          authEnabled: true,
          providers: [],
          credentialLogin: true,
          status: 'unauthenticated',
          error: 'Invalid username/password',
          errorStatus: 401,
          retryAfter: null,
        },
      },
    });

    const alerts = screen.getAllByRole('alert');
    const notificationAlert = alerts.find((el) => el.textContent?.includes('Invalid username/password'));
    expect(notificationAlert).toBeDefined();
  });
});
