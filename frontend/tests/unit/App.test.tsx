import { describe, it, expect, vi } from 'vitest';
import { screen, waitFor, render } from '@testing-library/react';
import React from 'react';
import { Provider } from 'react-redux';
import { IntlProvider } from 'react-intl';
import { ThemeProvider } from '@/contexts/ThemeProvider';
import { createTestStore } from '../mocks/fixtures/store.fixture';
import App from '@/App';

// Mock getAuthConfig to resolve with auth disabled
vi.mock('@/services/api/actions/auth-actions', () => ({
  getAuthConfig: vi.fn(() => Promise.resolve({ data: { auth_enabled: false } })),
  getMe: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
}));

describe('App Bootstrap Integration', () => {
  it('first render shows loading indicator and then resolves', async () => {
    const store = createTestStore();

    // Set JSDOM window path to match the router basename '/ui'
    window.history.pushState({}, '', '/ui/');

    render(
      <Provider store={store}>
        <IntlProvider locale="en" defaultLocale="en">
          <ThemeProvider>
            <App />
          </ThemeProvider>
        </IntlProvider>
      </Provider>
    );

    // Initial status is 'idle'/'loading', so ProtectedRoute displays the loader
    expect(screen.getByText('Checking authentication...')).toBeInTheDocument();

    // After bootstrapAuth completes, it resolves and the loader disappears
    await waitFor(() => {
      expect(screen.queryByText('Checking authentication...')).toBeNull();
    });
  });
});
