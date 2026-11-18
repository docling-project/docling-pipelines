import { describe, it, expect, beforeEach } from 'vitest';
import { server } from '../../../../mocks/server';
import { http, HttpResponse } from 'msw';
import {
  createFlow,
  getFlow,
  getFlows,
  getFlowsByProjectId,
  updateFlow,
  patchFlow,
  deleteFlow,
  bulkDeleteFlows,
} from '@/services/api/actions/flow-actions';
import { paginatedFlowResponseFixture } from '../../../../mocks/fixtures/flow.fixture';

describe('flow-actions', () => {
  // ─── createFlow ─────────────────────────────────────────────────────────────
  describe('createFlow', () => {
    it('happy path: returns created flow', async () => {
      const res = await createFlow({ name: 'New Flow', container_id: 'p-1' });
      expect(res.status).toBe(201);
      expect(res.data.flow_id).toBeDefined();
    });

    it('throws on network error', async () => {
      server.use(
        http.post('/api/flows', () => HttpResponse.error())
      );
      await expect(createFlow({ name: 'X' })).rejects.toThrow();
    });

    it('throws on 4xx response', async () => {
      server.use(
        http.post('/api/flows', () =>
          HttpResponse.json({ detail: 'Bad Request' }, { status: 400 })
        )
      );
      await expect(createFlow({ name: 'X' })).rejects.toBeDefined();
    });

    it('throws on 500 server error', async () => {
      server.use(
        http.post('/api/flows', () =>
          HttpResponse.json({ detail: 'Internal Server Error' }, { status: 500 })
        )
      );
      await expect(createFlow({ name: 'X' })).rejects.toBeDefined();
    });

    it('returns response data matching sent payload', async () => {
      const payload = { name: 'My Special Flow', container_id: 'proj-abc' };
      const res = await createFlow(payload);
      expect(res.data.name).toBe('My Special Flow');
    });
  });

  // ─── getFlow ─────────────────────────────────────────────────────────────────
  describe('getFlow', () => {
    it('happy path: returns flow data', async () => {
      const res = await getFlow('flow-1');
      expect(res.data.flow_id).toBe('flow-1');
    });

    it('throws on 404', async () => {
      server.use(
        http.get('/api/flows/:id', () =>
          HttpResponse.json({ detail: 'Not Found' }, { status: 404 })
        )
      );
      await expect(getFlow('missing')).rejects.toBeDefined();
    });

    it('throws on network error', async () => {
      server.use(
        http.get('/api/flows/:id', () => HttpResponse.error())
      );
      await expect(getFlow('flow-x')).rejects.toThrow();
    });

    it('returns the correct flow_id from the URL param', async () => {
      const res = await getFlow('flow-99');
      expect(res.data.flow_id).toBe('flow-99');
    });
  });

  // ─── getFlows ─────────────────────────────────────────────────────────────────
  describe('getFlows', () => {
    it('happy path with no params: returns paginated flows', async () => {
      const res = await getFlows();
      expect(res.data.flows).toBeDefined();
      expect(Array.isArray(res.data.flows)).toBe(true);
    });

    it('passes limit query param', async () => {
      let capturedUrl = '';
      server.use(
        http.get('/api/flows', ({ request }) => {
          capturedUrl = request.url;
          return HttpResponse.json(paginatedFlowResponseFixture);
        })
      );
      await getFlows({ limit: 5 });
      expect(capturedUrl).toContain('limit=5');
    });

    it('passes offset query param', async () => {
      let capturedUrl = '';
      server.use(
        http.get('/api/flows', ({ request }) => {
          capturedUrl = request.url;
          return HttpResponse.json(paginatedFlowResponseFixture);
        })
      );
      await getFlows({ offset: 10 });
      expect(capturedUrl).toContain('offset=10');
    });

    it('passes name query param', async () => {
      let capturedUrl = '';
      server.use(
        http.get('/api/flows', ({ request }) => {
          capturedUrl = request.url;
          return HttpResponse.json(paginatedFlowResponseFixture);
        })
      );
      await getFlows({ name: 'search-term' });
      expect(capturedUrl).toContain('name=search-term');
    });

    it('passes tags query param', async () => {
      let capturedUrl = '';
      server.use(
        http.get('/api/flows', ({ request }) => {
          capturedUrl = request.url;
          return HttpResponse.json(paginatedFlowResponseFixture);
        })
      );
      await getFlows({ tags: 'ai' });
      expect(capturedUrl).toContain('tags=ai');
    });

    it('passes is_hidden query param', async () => {
      let capturedUrl = '';
      server.use(
        http.get('/api/flows', ({ request }) => {
          capturedUrl = request.url;
          return HttpResponse.json(paginatedFlowResponseFixture);
        })
      );
      await getFlows({ is_hidden: true });
      expect(capturedUrl).toContain('is_hidden=true');
    });

    it('throws on 500', async () => {
      server.use(
        http.get('/api/flows', () =>
          HttpResponse.json({ detail: 'Server Error' }, { status: 500 })
        )
      );
      await expect(getFlows()).rejects.toBeDefined();
    });
  });

  // ─── getFlowsByProjectId ───────────────────────────────────────────────────
  describe('getFlowsByProjectId', () => {
    it('happy path with no params: returns flows for project', async () => {
      const res = await getFlowsByProjectId('proj-1');
      expect(res.data.flows).toBeDefined();
    });

    it('passes limit query param', async () => {
      let capturedUrl = '';
      server.use(
        http.get('/api/projects/:id/flows', ({ request }) => {
          capturedUrl = request.url;
          return HttpResponse.json(paginatedFlowResponseFixture);
        })
      );
      await getFlowsByProjectId('proj-1', { limit: 3 });
      expect(capturedUrl).toContain('limit=3');
    });

    it('passes offset query param', async () => {
      let capturedUrl = '';
      server.use(
        http.get('/api/projects/:id/flows', ({ request }) => {
          capturedUrl = request.url;
          return HttpResponse.json(paginatedFlowResponseFixture);
        })
      );
      await getFlowsByProjectId('proj-1', { offset: 5 });
      expect(capturedUrl).toContain('offset=5');
    });

    it('passes name query param', async () => {
      let capturedUrl = '';
      server.use(
        http.get('/api/projects/:id/flows', ({ request }) => {
          capturedUrl = request.url;
          return HttpResponse.json(paginatedFlowResponseFixture);
        })
      );
      await getFlowsByProjectId('proj-1', { name: 'my-flow' });
      expect(capturedUrl).toContain('name=my-flow');
    });

    it('passes tags query params (multiple)', async () => {
      let capturedUrl = '';
      server.use(
        http.get('/api/projects/:id/flows', ({ request }) => {
          capturedUrl = request.url;
          return HttpResponse.json(paginatedFlowResponseFixture);
        })
      );
      await getFlowsByProjectId('proj-1', { tags: ['ai', 'nlp'] });
      expect(capturedUrl).toContain('tags=ai');
      expect(capturedUrl).toContain('tags=nlp');
    });

    it('builds URL without query string when no params given', async () => {
      let capturedUrl = '';
      server.use(
        http.get('/api/projects/:id/flows', ({ request }) => {
          capturedUrl = request.url;
          return HttpResponse.json(paginatedFlowResponseFixture);
        })
      );
      await getFlowsByProjectId('proj-abc');
      expect(capturedUrl).not.toContain('?');
    });

    it('throws on 404', async () => {
      server.use(
        http.get('/api/projects/:id/flows', () =>
          HttpResponse.json({ detail: 'Not Found' }, { status: 404 })
        )
      );
      await expect(getFlowsByProjectId('bad-proj')).rejects.toBeDefined();
    });

    it('throws on network error', async () => {
      server.use(
        http.get('/api/projects/:id/flows', () => HttpResponse.error())
      );
      await expect(getFlowsByProjectId('proj-1')).rejects.toThrow();
    });
  });

  // ─── updateFlow ───────────────────────────────────────────────────────────
  describe('updateFlow', () => {
    it('happy path: returns updated flow', async () => {
      const res = await updateFlow('flow-1', { name: 'Updated' });
      expect(res.data.flow_id).toBe('flow-1');
    });

    it('returns the updated name in response', async () => {
      const res = await updateFlow('flow-1', { name: 'New Name' });
      expect(res.data.name).toBe('New Name');
    });

    it('throws on 404', async () => {
      server.use(
        http.put('/api/flows/:id', () =>
          HttpResponse.json({ detail: 'Not Found' }, { status: 404 })
        )
      );
      await expect(updateFlow('missing', { name: 'X' })).rejects.toBeDefined();
    });

    it('throws on network error', async () => {
      server.use(
        http.put('/api/flows/:id', () => HttpResponse.error())
      );
      await expect(updateFlow('flow-1', {})).rejects.toThrow();
    });
  });

  // ─── patchFlow ────────────────────────────────────────────────────────────
  describe('patchFlow', () => {
    it('happy path: returns patched flow', async () => {
      const res = await patchFlow('flow-1', { name: 'Patched' });
      expect(res.data).toBeDefined();
    });

    it('returns the patched name in response', async () => {
      const res = await patchFlow('flow-1', { name: 'Patched Name' });
      expect(res.data.name).toBe('Patched Name');
    });

    it('throws on 400', async () => {
      server.use(
        http.patch('/api/flows/:id', () =>
          HttpResponse.json({ detail: 'Bad Request' }, { status: 400 })
        )
      );
      await expect(patchFlow('flow-1', { name: '' })).rejects.toBeDefined();
    });

    it('throws on network error', async () => {
      server.use(
        http.patch('/api/flows/:id', () => HttpResponse.error())
      );
      await expect(patchFlow('flow-1', {})).rejects.toThrow();
    });

    it('updates tags correctly', async () => {
      const res = await patchFlow('flow-1', { tags: ['a', 'b'] });
      expect(res.data).toBeDefined();
    });
  });

  // ─── deleteFlow ───────────────────────────────────────────────────────────
  describe('deleteFlow', () => {
    it('happy path: returns 204', async () => {
      const res = await deleteFlow('flow-1');
      expect(res.status).toBe(204);
    });

    it('throws on 404', async () => {
      server.use(
        http.delete('/api/flows/:id', () =>
          HttpResponse.json({ detail: 'Not Found' }, { status: 404 })
        )
      );
      await expect(deleteFlow('missing')).rejects.toBeDefined();
    });

    it('throws on network error', async () => {
      server.use(
        http.delete('/api/flows/:id', () => HttpResponse.error())
      );
      await expect(deleteFlow('flow-1')).rejects.toThrow();
    });

    it('throws on 403 forbidden', async () => {
      server.use(
        http.delete('/api/flows/:id', () =>
          HttpResponse.json({ detail: 'Forbidden' }, { status: 403 })
        )
      );
      await expect(deleteFlow('flow-1')).rejects.toBeDefined();
    });
  });

  // ─── bulkDeleteFlows ──────────────────────────────────────────────────────
  describe('bulkDeleteFlows', () => {
    beforeEach(() => {
      server.use(
        http.delete('/api/flows', () =>
          HttpResponse.json({ deleted_count: 2 }, { status: 200 })
        )
      );
    });

    it('happy path: returns deleted_count', async () => {
      const res = await bulkDeleteFlows(['flow-1', 'flow-2']);
      expect(res.data.deleted_count).toBe(2);
    });

    it('passes flow_ids as comma-separated query param', async () => {
      let capturedUrl = '';
      server.use(
        http.delete('/api/flows', ({ request }) => {
          capturedUrl = request.url;
          return HttpResponse.json({ deleted_count: 2 });
        })
      );
      await bulkDeleteFlows(['flow-1', 'flow-2']);
      expect(capturedUrl).toContain('flow_ids=flow-1%2Cflow-2');
    });

    it('throws on 500 server error', async () => {
      server.use(
        http.delete('/api/flows', () =>
          HttpResponse.json({ detail: 'Internal Server Error' }, { status: 500 })
        )
      );
      await expect(bulkDeleteFlows(['flow-1'])).rejects.toBeDefined();
    });

    it('throws on network error', async () => {
      server.use(
        http.delete('/api/flows', () => HttpResponse.error())
      );
      await expect(bulkDeleteFlows(['flow-1'])).rejects.toThrow();
    });
  });
});
