import { describe, it, expect } from 'vitest';
import { AUTH_ENDPOINTS } from '@/services/api/endpoints';

describe('services/api/endpoints', () => {
  it('auth endpoints live under /auth, not /api/v1', () => {
    expect(AUTH_ENDPOINTS).toEqual({
      CONFIG: '/auth/config',
      ME: '/auth/me',
      LOGIN: '/auth/login',
      LOGOUT: '/auth/logout',
    });
  });
});
