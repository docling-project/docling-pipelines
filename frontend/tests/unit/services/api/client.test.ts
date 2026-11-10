import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { apiClient } from '@/services/api/client';
import { server } from '../../../mocks/server';
import { http, HttpResponse } from 'msw';
import { waitFor } from '@testing-library/react';

const mockAssign = vi.fn();
const originalLocation = window.location;

describe('apiClient', () => {
  it('has Content-Type: application/json header', () => {
    const headers = apiClient.defaults.headers as Record<string, unknown>;
    const common = headers['common'] as Record<string, unknown> | undefined;
    const contentType = common?.['Content-Type'] ?? headers['Content-Type'];
    expect(String(contentType)).toContain('application/json');
  });

  it('has a 10000ms timeout', () => {
    expect(apiClient.defaults.timeout).toBe(10000);
  });

  it('is an axios instance with get/post/put/delete methods', () => {
    expect(typeof apiClient.get).toBe('function');
    expect(typeof apiClient.post).toBe('function');
    expect(typeof apiClient.put).toBe('function');
    expect(typeof apiClient.delete).toBe('function');
  });
});

describe('apiClient additional requirements', () => {
  beforeEach(() => {
    mockAssign.mockClear();

    // Safely mock window.location in JSDOM
    delete (window as any).location;
    window.location = {
      ...originalLocation,
      assign: mockAssign,
    } as any;

    window.history.pushState({}, '', '/ui/flows?project_id=123');
  });

  afterEach(() => {
    (window as any).location = originalLocation;
  });

  it('sends credentials with every request (withCredentials: true)', () => {
    expect(apiClient.defaults.withCredentials).toBe(true);
  });

  it('attaches X-Requested-With: XMLHttpRequest to state-changing requests', async () => {
    let capturedHeader: string | null = null;
    server.use(
      http.post('http://localhost:3000/api/test-post', ({ request }) => {
        capturedHeader = request.headers.get('X-Requested-With');
        return HttpResponse.json({ ok: true });
      })
    );

    await apiClient.post('http://localhost:3000/api/test-post', {});
    expect(capturedHeader).toBe('XMLHttpRequest');
  });

  it('skips 401 redirect for login endpoint', async () => {
    server.use(
      http.post('http://localhost:3000/auth/login', () => {
        return new HttpResponse(null, { status: 401 });
      })
    );

    try {
      await apiClient.post('http://localhost:3000/auth/login', {});
    } catch {
      // expected
    }

    expect(mockAssign).not.toHaveBeenCalled();
  });

  it('handles 403 response by pushing error toast and keeping session', async () => {
    const { store } = await import('@/store');

    server.use(
      http.delete('http://localhost:3000/api/flows/123', () => {
        return new HttpResponse(null, { status: 403 });
      })
    );

    try {
      await apiClient.delete('http://localhost:3000/api/flows/123');
    } catch {
      // expected
    }

    const notifications = store.getState().notifications.active;
    const permissionDeniedNotification = notifications.find((n) => n.subtitle === 'You do not have permission to perform this action');
    expect(permissionDeniedNotification).toBeDefined();
  });

  it('concurrent 401s on other endpoints clear auth state and trigger single redirect', async () => {
    const { store } = await import('@/store');

    server.use(
      http.get('http://localhost:3000/api/flows', () => {
        return new HttpResponse(null, { status: 401 });
      })
    );

    // Call concurrent 401s
    await Promise.allSettled([
      apiClient.get('http://localhost:3000/api/flows'),
      apiClient.get('http://localhost:3000/api/flows'),
      apiClient.get('http://localhost:3000/api/flows'),
    ]);

    // Latch should trigger navigate EXACTLY once
    expect(mockAssign).toHaveBeenCalledTimes(1);
    expect(mockAssign).toHaveBeenCalledWith('/ui/login?return_to=%2Fflows%3Fproject_id%3D123');

    // Wait for the async logout thunk to finish clearing the state
    await waitFor(() => {
      expect(store.getState().auth.status).toBe('unauthenticated');
    });
  });
});
