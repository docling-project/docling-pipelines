import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { Routes, Route } from 'react-router-dom';
import { renderWithProviders } from '../../../../utils/renderWithProviders';
import { ProtectedRoute } from '@/components/common/ProtectedRoute/ProtectedRoute';

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
});
