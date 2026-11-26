import { describe, it, expect } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { Routes, Route } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { renderWithProviders } from '../../../../utils/renderWithProviders';
import { server } from '../../../../mocks/server';
import { ProtectedRoute } from '@/components/common/ProtectedRoute';

describe('ProtectedRoute', () => {
  it('authenticated → renders children', () => {
    renderWithProviders(
      <Routes>
        <Route path="/protected" element={
          <ProtectedRoute>
            <div data-testid="protected-content">Secret</div>
          </ProtectedRoute>
        } />
      </Routes>,
      {
        initialEntries: ['/protected'],
        preloadedState: {
          auth: {
            user: { username: 'testuser', email: '', full_name: 'Test', roles: ['admin'] },
            authEnabled: true,
            providers: [],
            credentialLogin: true,
            status: 'authenticated',
            error: null,
            errorStatus: null,
            retryAfter: null,
          },
        },
      }
    );
    expect(screen.getByTestId('protected-content')).toBeDefined();
  });

  it('unauthenticated → redirects to /login with return_to', () => {
    renderWithProviders(
      <Routes>
        <Route path="/protected" element={
          <ProtectedRoute>
            <div data-testid="protected-content">Secret</div>
          </ProtectedRoute>
        } />
        <Route path="/login" element={<div data-testid="login-page">Login Page</div>} />
      </Routes>,
      {
        initialEntries: ['/protected'],
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
      }
    );
    expect(screen.queryByTestId('protected-content')).toBeNull();
    expect(screen.getByTestId('login-page')).toBeDefined();
  });

  it('loading → renders loading spinner', () => {
    renderWithProviders(
      <Routes>
        <Route path="/protected" element={
          <ProtectedRoute>
            <div data-testid="protected-content">Secret</div>
          </ProtectedRoute>
        } />
      </Routes>,
      {
        initialEntries: ['/protected'],
        preloadedState: {
          auth: {
            user: null,
            authEnabled: true,
            providers: [],
            credentialLogin: true,
            status: 'loading',
            error: null,
            errorStatus: null,
            retryAfter: null,
          },
        },
      }
    );
    expect(screen.getByText('Checking authentication...')).toBeDefined();
    expect(screen.queryByTestId('protected-content')).toBeNull();
  });

  it('error → fails closed, renders service-unavailable error state, and retries bootstrapAuth', async () => {
    let configCalls = 0;
    server.use(
      http.get('/auth/config', () => {
        configCalls += 1;
        return HttpResponse.json({ auth_enabled: false, credential_login: false, providers: [] });
      })
    );

    renderWithProviders(
      <Routes>
        <Route path="/protected" element={
          <ProtectedRoute>
            <div data-testid="protected-content">Secret</div>
          </ProtectedRoute>
        } />
        <Route path="/login" element={<div data-testid="login-page">Login Page</div>} />
      </Routes>,
      {
        initialEntries: ['/protected'],
        preloadedState: {
          auth: {
            user: null,
            authEnabled: true,
            providers: [],
            credentialLogin: false,
            status: 'error',
            error: 'Service unavailable',
            errorStatus: 503,
            retryAfter: null,
          },
        },
      }
    );

    expect(screen.queryByTestId('protected-content')).toBeNull();
    expect(screen.queryByTestId('login-page')).toBeNull();
    expect(screen.getByRole('alert')).toBeDefined();
    expect(screen.getByText('Authentication service unavailable')).toBeDefined();

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() => {
      expect(configCalls).toBe(1);
      expect(screen.getByTestId('protected-content')).toBeDefined();
    });
  });
});
