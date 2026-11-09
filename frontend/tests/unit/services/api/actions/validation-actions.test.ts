import { describe, it, expect } from 'vitest';
import { server } from '../../../../mocks/server';
import { http, HttpResponse } from 'msw';
import { validateFlow } from '@/services/api/actions/validation-actions';

describe('validation-actions', () => {

  describe('validateFlow', () => {
    it('calls POST /api/validation/validate and returns data', async () => {
      server.use(
        http.post('/api/validation/validate', () =>
          HttpResponse.json({ status: 'valid', message: null, errors: [], warnings: [] })
        )
      );
      const res = await validateFlow({ pipelines: [] });
      expect(res.data.status).toBe('valid');
      expect(res.data.errors).toHaveLength(0);
    });

    it('returns errors array when validation fails', async () => {
      server.use(
        http.post('/api/validation/validate', () =>
          HttpResponse.json({
            status: 'invalid',
            message: 'Validation failed',
            errors: [{ code: 'E001', message: 'Missing node', message_code: null, node_id: null, node_name: null, operator: null }],
            warnings: [],
          })
        )
      );
      const res = await validateFlow({ pipelines: [] });
      expect(res.data.errors).toHaveLength(1);
      expect(res.data.errors[0]?.code).toBe('E001');
    });

    it('throws when server returns 500', async () => {
      server.use(
        http.post('/api/validation/validate', () => HttpResponse.json({ error: 'fail' }, { status: 500 }))
      );
      await expect(validateFlow({})).rejects.toBeDefined();
    });

    it('wraps definition in ElyraFlowCreateRequest shape when isElyra=true', async () => {
      let capturedBody: unknown;
      server.use(
        http.post('/api/validation/validate', async ({ request }) => {
          capturedBody = await request.json();
          return HttpResponse.json({ status: 'valid', message: null, errors: [], warnings: [] });
        })
      );
      await validateFlow({ pipelines: [] }, true);
      expect((capturedBody as { name: string }).name).toBe('validate');
      expect((capturedBody as { definition: unknown }).definition).toBeDefined();
    });
  });
});
