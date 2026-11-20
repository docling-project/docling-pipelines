import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { PassThrough, Readable } from 'node:stream';
import axios, { AxiosError, type AxiosResponse } from 'axios';
import type { Request, Response, Router } from 'express';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { routes as documentClassRoutes } from '../../../server/controllers/document-class-controller';
import { routes as flowRoutes } from '../../../server/controllers/flow-controller';
import { routes as jobRunRoutes } from '../../../server/controllers/job-run-controller';
import { routes as operatorRoutes } from '../../../server/controllers/operator-controller';
import { routes as projectsRoutes } from '../../../server/controllers/projects-controller';
import { routes as validationRoutes } from '../../../server/controllers/validation-controller';

type Handler = (req: Request, res: Response) => Promise<void>;

interface FakeRequest {
  params?: Record<string, string>;
  query?: Record<string, unknown>;
  body?: unknown;
}

/** Registers a controller's routes on a recording router instead of a real Express app. */
const registerRoutes = (register: (router: Router) => void): Map<string, Handler> => {
  const handlers = new Map<string, Handler>();
  const record = (method: string) => (routePath: string, handler: Handler) => {
    handlers.set(`${method} ${routePath}`, handler);
  };
  const router = {
    get: record('GET'),
    post: record('POST'),
    put: record('PUT'),
    patch: record('PATCH'),
    delete: record('DELETE'),
  } as unknown as Router;
  register(router);
  return handlers;
};

const allHandlers = new Map<string, Handler>([
  ...registerRoutes(flowRoutes),
  ...registerRoutes(jobRunRoutes),
  ...registerRoutes(projectsRoutes),
  ...registerRoutes(operatorRoutes),
  ...registerRoutes(validationRoutes),
  ...registerRoutes(documentClassRoutes),
]);

/** A response double. It is a stream so `stream.pipe(res)` works for report downloads. */
const createRes = () => {
  const res = new PassThrough() as PassThrough & Record<string, unknown>;
  res.status = vi.fn(() => res);
  res.json = vi.fn(() => res);
  res.send = vi.fn(() => res);
  res.setHeader = vi.fn(() => res);
  return res as unknown as Response & {
    status: ReturnType<typeof vi.fn>;
    json: ReturnType<typeof vi.fn>;
    send: ReturnType<typeof vi.fn>;
    setHeader: ReturnType<typeof vi.fn>;
  };
};

const call = async (routeKey: string, request: FakeRequest = {}) => {
  const handler = allHandlers.get(routeKey);
  if (!handler) throw new Error(`Route not registered: ${routeKey}`);
  const res = createRes();
  await handler({ params: {}, query: {}, body: undefined, ...request } as unknown as Request, res);
  return res;
};

const backendUrl = (suffix: string) => `http://backend:8000${suffix}`;

const upstreamError = (status: number, data: unknown) =>
  new AxiosError('Request failed', 'ERR_BAD_REQUEST', undefined, undefined, { status, data } as AxiosResponse);

describe('BFF controllers', () => {
  let requestSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    process.env.BACKEND_API_URL = 'http://backend:8000';
    requestSpy = vi.spyOn(axios, 'request').mockResolvedValue({ status: 200, data: { ok: true } } as AxiosResponse);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  const lastCall = () => requestSpy.mock.calls.at(-1)?.[0] as { method: string; url: string; data?: unknown };

  describe('route registration', () => {
    it('registers every public BFF route', () => {
      expect([...allHandlers.keys()].sort()).toEqual(
        [
          'DELETE /flows',
          'DELETE /flows/:flowId',
          'DELETE /job_runs/:jobRunId',
          'DELETE /projects/:projectId',
          'GET /documentClasses',
          'GET /fetchOperatorMetadata',
          'GET /flows',
          'GET /flows/:flowId',
          'GET /job_runs',
          'GET /job_runs/:jobRunId',
          'GET /job_runs/:jobRunId/flow_definition',
          'GET /job_runs/:jobRunId/report',
          'GET /projects',
          'GET /projects/:projectId',
          'GET /projects/:projectId/flows',
          'GET /providers/:provider/models',
          'PATCH /flows/:flowId',
          'PATCH /projects/:projectId',
          'POST /enrichFlowFeatures',
          'POST /flows',
          'POST /job_runs',
          'POST /job_runs/:jobRunId/cancel',
          'POST /projects',
          'POST /validation/validate',
          'PUT /flows/:flowId',
          'PUT /projects/:projectId',
        ].sort(),
      );
    });
  });

  describe('forwarding to the backend', () => {
    it.each([
      ['GET /flows/:flowId', { params: { flowId: 'f1' } }, 'GET', '/api/v1/flows/f1'],
      ['DELETE /flows/:flowId', { params: { flowId: 'f1' } }, 'DELETE', '/api/v1/flows/f1'],
      ['PUT /flows/:flowId', { params: { flowId: 'f1' }, body: { a: 1 } }, 'PUT', '/api/v1/flows/f1?is_elyra=true'],
      ['POST /flows', { body: { a: 1 } }, 'POST', '/api/v1/flows?is_elyra=true'],
      ['GET /job_runs/:jobRunId', { params: { jobRunId: 'r1' } }, 'GET', '/api/v1/job_runs/r1?include_logs=false'],
      ['POST /job_runs', { body: { a: 1 } }, 'POST', '/api/v1/job_runs'],
      ['POST /job_runs/:jobRunId/cancel', { params: { jobRunId: 'r1' } }, 'POST', '/api/v1/job_runs/r1/cancel'],
      ['DELETE /job_runs/:jobRunId', { params: { jobRunId: 'r1' } }, 'DELETE', '/api/v1/job_runs/r1'],
      ['GET /job_runs/:jobRunId/flow_definition', { params: { jobRunId: 'r1' } }, 'GET', '/api/v1/job_runs/r1/flow_definition'],
      ['GET /projects/:projectId', { params: { projectId: 'p1' } }, 'GET', '/api/v1/projects/p1'],
      ['PUT /projects/:projectId', { params: { projectId: 'p1' }, body: { a: 1 } }, 'PUT', '/api/v1/projects/p1'],
      ['PATCH /projects/:projectId', { params: { projectId: 'p1' }, body: { a: 1 } }, 'PATCH', '/api/v1/projects/p1'],
      ['DELETE /projects/:projectId', { params: { projectId: 'p1' } }, 'DELETE', '/api/v1/projects/p1'],
      ['POST /projects', { body: { a: 1 } }, 'POST', '/api/v1/projects'],
      ['GET /fetchOperatorMetadata', {}, 'GET', '/api/v1/operators/metadata'],
      ['POST /enrichFlowFeatures', { body: { a: 1 } }, 'POST', '/api/v1/validation/enrich_flow_features'],
      ['GET /documentClasses', {}, 'GET', '/api/v1/document_classes'],
    ] as const)('%s calls %s %s', async (routeKey, request, method, urlSuffix) => {
      await call(routeKey, request as FakeRequest);

      expect(requestSpy).toHaveBeenCalledTimes(1);
      expect(lastCall()).toMatchObject({ method, url: backendUrl(urlSuffix) });
    });

    it('sends the request body to the backend unchanged', async () => {
      await call('POST /flows', { body: { name: 'a', definition: { x: 1 } } });

      expect(lastCall().data).toEqual({ name: 'a', definition: { x: 1 } });
    });

    it('relays the backend payload to the client', async () => {
      const res = await call('GET /projects/:projectId', { params: { projectId: 'p1' } });

      expect(res.json).toHaveBeenCalledWith({ ok: true });
    });

    it('keeps the backend status for creates and replies without a body for deletes', async () => {
      requestSpy.mockResolvedValue({ status: 201, data: { id: 'new' } } as AxiosResponse);
      const created = await call('POST /flows', { body: {} });
      expect(created.status).toHaveBeenCalledWith(201);
      expect(created.json).toHaveBeenCalledWith({ id: 'new' });

      requestSpy.mockResolvedValue({ status: 204, data: '' } as AxiosResponse);
      const deleted = await call('DELETE /flows/:flowId', { params: { flowId: 'f1' } });
      expect(deleted.status).toHaveBeenCalledWith(204);
      expect(deleted.send).toHaveBeenCalledWith();
    });
  });

  describe('query parameters', () => {
    it('applies list defaults and sends tags as repeated keys', async () => {
      await call('GET /flows', { query: { tags: ['x', 'y'], name: 'my flow', is_hidden: 'false' } });

      expect(lastCall().url).toBe(
        backendUrl('/api/v1/flows?limit=100&offset=0&is_elyra=true&name=my+flow&tags=x&tags=y&is_hidden=false'),
      );
    });

    it('omits empty optional filters', async () => {
      await call('GET /flows', { query: { name: '' } });

      expect(lastCall().url).toBe(backendUrl('/api/v1/flows?limit=100&offset=0&is_elyra=true'));
    });

    it('lists flows for a project with the project in the path', async () => {
      await call('GET /projects/:projectId/flows', { params: { projectId: 'p1' }, query: { limit: '5' } });

      expect(lastCall().url).toBe(backendUrl('/api/v1/projects/p1/flows?limit=5&offset=0&is_elyra=true'));
    });

    it('passes job run filters through', async () => {
      await call('GET /job_runs', { query: { job_id: 'j1', status: 'RUNNING' } });

      expect(lastCall().url).toBe(backendUrl('/api/v1/job_runs?limit=100&job_id=j1&status=RUNNING'));
    });

    it('encodes a malicious is_elyra value instead of adding a parameter', async () => {
      await call('POST /validation/validate', { query: { is_elyra: 'true&admin=1' }, body: {} });

      expect(lastCall().url).toBe(backendUrl('/api/v1/validation/validate_flow?is_elyra=true%26admin%3D1'));
    });

    it('defaults is_elyra to true for flow validation', async () => {
      await call('POST /validation/validate', { body: {} });

      expect(lastCall().url).toBe(backendUrl('/api/v1/validation/validate_flow?is_elyra=true'));
    });
  });

  describe('untrusted route parameters', () => {
    it('cannot inject a query parameter through a route parameter', async () => {
      await call('GET /flows/:flowId', { params: { flowId: 'abc?is_elyra=true' } });

      expect(lastCall().url).toBe(backendUrl('/api/v1/flows/abc%3Fis_elyra%3Dtrue'));
    });

    it('cannot climb out of the resource path with encoded slashes', async () => {
      await call('GET /flows/:flowId', { params: { flowId: '../../operators/metadata' } });

      expect(lastCall().url).toBe(backendUrl('/api/v1/flows/..%2F..%2Foperators%2Fmetadata'));
    });

    it.each(['..', '.'])('answers 400 and never calls the backend for the segment "%s"', async (flowId) => {
      const res = await call('GET /flows/:flowId', { params: { flowId } });

      expect(requestSpy).not.toHaveBeenCalled();
      expect(res.status).toHaveBeenCalledWith(400);
      expect(res.json).toHaveBeenCalledWith({ error: 'Invalid request path' });
    });
  });

  describe('flow patch', () => {
    it('syncs the Elyra pipeline name before patching when a name is sent', async () => {
      requestSpy
        .mockResolvedValueOnce({
          status: 200,
          data: { definition: { pipelines: [{ app_data: { ds_flow: { name: 'old' } } }] } },
        } as AxiosResponse)
        .mockResolvedValueOnce({ status: 200, data: { ok: true } } as AxiosResponse);

      await call('PATCH /flows/:flowId', { params: { flowId: 'f1' }, body: { name: 'new' } });

      expect(requestSpy).toHaveBeenCalledTimes(2);
      const [first, second] = requestSpy.mock.calls.map((args: unknown[]) => args[0] as { method: string; url: string; data?: unknown });
      expect(first).toMatchObject({ method: 'GET', url: backendUrl('/api/v1/flows/f1?is_elyra=true') });
      expect(second).toMatchObject({ method: 'PATCH', url: backendUrl('/api/v1/flows/f1?is_elyra=true') });
      expect(second.data).toEqual({
        name: 'new',
        definition: { pipelines: [{ app_data: { ds_flow: { name: 'new' } } }] },
      });
    });

    it('patches directly, without a preliminary read, when no name is sent', async () => {
      await call('PATCH /flows/:flowId', { params: { flowId: 'f1' }, body: { description: 'd' } });

      expect(requestSpy).toHaveBeenCalledTimes(1);
      expect(lastCall()).toMatchObject({ method: 'PATCH', data: { description: 'd' } });
    });
  });

  describe('input checks that do not reach the backend', () => {
    it('requires flow_ids for bulk delete', async () => {
      const res = await call('DELETE /flows');

      expect(requestSpy).not.toHaveBeenCalled();
      expect(res.status).toHaveBeenCalledWith(400);
      expect(res.json).toHaveBeenCalledWith({ error: 'flow_ids query parameter is required' });
    });

    it('forwards flow_ids for bulk delete', async () => {
      await call('DELETE /flows', { query: { flow_ids: 'a,b' } });

      expect(lastCall()).toMatchObject({ method: 'DELETE', url: backendUrl('/api/v1/flows?flow_ids=a%2Cb') });
    });

    it('rejects providers outside the allow list', async () => {
      const res = await call('GET /providers/:provider/models', { params: { provider: 'evil' } });

      expect(requestSpy).not.toHaveBeenCalled();
      expect(res.status).toHaveBeenCalledWith(400);
    });

    it('forwards api_base, encoded, for an allowed provider', async () => {
      await call('GET /providers/:provider/models', {
        params: { provider: 'ollama' },
        query: { api_base: 'http://host:11434/?x=1' },
      });

      expect(lastCall().url).toBe(backendUrl('/api/v1/providers/ollama/models?api_base=http%3A%2F%2Fhost%3A11434%2F%3Fx%3D1'));
    });
  });

  describe('error handling', () => {
    it('relays a backend error status and body', async () => {
      requestSpy.mockRejectedValue(upstreamError(404, { detail: 'Project not found' }));

      const res = await call('GET /projects/:projectId', { params: { projectId: 'missing' } });

      expect(res.status).toHaveBeenCalledWith(404);
      expect(res.json).toHaveBeenCalledWith({ detail: 'Project not found' });
    });

    it('answers 500 with a fixed message when the backend is unreachable', async () => {
      requestSpy.mockRejectedValue(new AxiosError('connect ECONNREFUSED 10.0.0.5:8000'));

      const res = await call('GET /documentClasses');

      expect(res.status).toHaveBeenCalledWith(500);
      expect(res.json).toHaveBeenCalledWith({ error: 'Failed to fetch document classes' });
    });

    it('does not leak the network error message to the client', async () => {
      requestSpy.mockRejectedValue(new AxiosError('connect ECONNREFUSED 10.0.0.5:8000'));

      const res = await call('GET /fetchOperatorMetadata');

      expect(JSON.stringify(res.json.mock.calls)).not.toContain('10.0.0.5');
    });

    it('uses a message specific to the failing operation', async () => {
      requestSpy.mockRejectedValue(new Error('boom'));

      const res = await call('DELETE /projects/:projectId', { params: { projectId: 'p1' } });

      expect(res.json).toHaveBeenCalledWith({ error: 'Failed to delete project' });
    });

    it('stops after the first backend failure when patching a flow name', async () => {
      requestSpy.mockRejectedValueOnce(upstreamError(404, { detail: 'Flow not found' }));

      const res = await call('PATCH /flows/:flowId', { params: { flowId: 'f1' }, body: { name: 'n' } });

      expect(requestSpy).toHaveBeenCalledTimes(1);
      expect(res.status).toHaveBeenCalledWith(404);
    });
  });

  describe('job run report download', () => {
    it('requests a CSV stream and pipes it to the client', async () => {
      const csv = Readable.from([Buffer.from('a,b\n1,2\n')]);
      requestSpy.mockResolvedValue({ status: 200, data: csv } as AxiosResponse);
      const res = createRes();
      const chunks: Buffer[] = [];
      res.on('data', (chunk: Buffer) => chunks.push(chunk));

      await allHandlers.get('GET /job_runs/:jobRunId/report')!(
        { params: { jobRunId: 'r1' }, query: {} } as unknown as Request,
        res,
      );
      await new Promise((resolve) => res.on('end', resolve));

      expect(requestSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          url: backendUrl('/api/v1/job_runs/r1/report'),
          responseType: 'stream',
          headers: { Accept: 'text/csv' },
        }),
      );
      expect(res.setHeader).toHaveBeenCalledWith('Content-Type', 'text/csv');
      expect(res.setHeader).toHaveBeenCalledWith('Content-Disposition', 'attachment; filename="job-run-r1-report.csv"');
      expect(Buffer.concat(chunks).toString()).toBe('a,b\n1,2\n');
    });

    it('answers with the backend error when the report does not exist, instead of crashing', async () => {
      requestSpy.mockRejectedValue(
        new AxiosError('Request failed', 'ERR_BAD_REQUEST', undefined, undefined, {
          status: 404,
          data: Readable.from([Buffer.from('{"detail":"Job run not found"}')]),
        } as AxiosResponse),
      );

      const res = await call('GET /job_runs/:jobRunId/report', { params: { jobRunId: 'missing' } });

      expect(res.status).toHaveBeenCalledWith(404);
      expect(res.json).toHaveBeenCalledWith({ detail: 'Job run not found' });
    });
  });
});

describe('controller rules', () => {
  const controllersDir = path.resolve(__dirname, '../../../server/controllers');
  const files = readdirSync(controllersDir).filter((file) => file.endsWith('.ts'));
  const source = (file: string) => readFileSync(path.join(controllersDir, file), 'utf8');

  it('finds the controllers to check', () => {
    expect(files).toHaveLength(6);
  });

  it.each(files)('%s does not import axios', (file) => {
    expect(source(file)).not.toMatch(/from ['"]axios['"]/);
  });

  it.each(files)('%s does not import the header constants', (file) => {
    expect(source(file)).not.toMatch(/BODY_HEADERS|http-headers/);
  });

  it.each(files)('%s does not read error.response in catch blocks', (file) => {
    expect(source(file)).not.toMatch(/\.response\??\.(status|data)/);
  });

  it.each(files)('%s types every handler as (req: Request, res: Response) => Promise<void>', (file) => {
    const handlers = source(file).match(/^const \w+ = async \(/gm) ?? [];
    const typed = source(file).match(/^const \w+ = async \(_?req: Request, res: Response\): Promise<void> =>/gm) ?? [];
    expect(handlers.length).toBeGreaterThan(0);
    expect(typed).toHaveLength(handlers.length);
  });

  it.each(files)('%s types its routes function with Router and void', (file) => {
    expect(source(file)).toMatch(/export const routes = \(router: Router\): void =>/);
  });
});
