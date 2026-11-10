import { describe, it, expect, vi, beforeEach } from 'vitest';
import axios from 'axios';
import { EventEmitter } from 'events';
import { PassThrough } from 'stream';
import { routes as flowRoutes } from '../../../server/controllers/flow-controller';
import { routes as jobRunRoutes } from '../../../server/controllers/job-run-controller';
import { routes as projectsRoutes } from '../../../server/controllers/projects-controller';
import { routes as validationRoutes } from '../../../server/controllers/validation-controller';
import { routes as operatorRoutes } from '../../../server/controllers/operator-controller';
import { routes as documentClassRoutes } from '../../../server/controllers/document-class-controller';

vi.mock('axios');

type Handler = (req: unknown, res: unknown) => Promise<unknown> | unknown;
type Verb = 'get' | 'post' | 'put' | 'patch' | 'delete';

const collectHandlers = (register: (router: never) => void): Map<string, Handler> => {
  const handlers = new Map<string, Handler>();
  const router = {} as Record<Verb, (path: string, handler: Handler) => void>;
  (['get', 'post', 'put', 'patch', 'delete'] as Verb[]).forEach((verb) => {
    router[verb] = (path, handler) => {
      handlers.set(`${verb.toUpperCase()} ${path}`, handler);
    };
  });
  register(router as never);
  return handlers;
};

const makeRes = () => {
  const res = {
    statusCode: 200,
    body: undefined as unknown,
    headers: {} as Record<string, string>,
    status: vi.fn((code: number) => {
      res.statusCode = code;
      return res;
    }),
    json: vi.fn((body: unknown) => {
      res.body = body;
      return res;
    }),
    send: vi.fn(() => res),
    setHeader: vi.fn((name: string, value: string) => {
      res.headers[name] = value;
    }),
    destroy: vi.fn(),
  };
  return res;
};

const BROWSER_HEADERS = {
  cookie: 'docpipe_access_token=abc',
  authorization: 'Bearer token',
  'x-requested-with': 'XMLHttpRequest',
  'x-transaction-id': 'tx-1',
  'x-forwarded-for': '203.0.113.9',
  'x-forwarded-proto': 'https',
};

const makeReq = (overrides: Record<string, unknown> = {}) => ({
  headers: BROWSER_HEADERS,
  params: { flowId: 'f1', projectId: 'p1', jobRunId: 'r1', provider: 'ollama' },
  query: { flow_ids: 'f1,f2', name: 'x' },
  body: { name: 'new-name' },
  ...overrides,
});

const expectForwarded = (headers: Record<string, string>) => {
  expect(headers.Cookie).toBe('docpipe_access_token=abc');
  expect(headers.Authorization).toBe('Bearer token');
  expect(headers['X-Requested-With']).toBe('XMLHttpRequest');
  expect(headers['X-Transaction-ID']).toBe('tx-1');
  expect(headers).not.toHaveProperty('X-Forwarded-For');
  expect(headers).not.toHaveProperty('x-forwarded-for');
  expect(headers).not.toHaveProperty('X-Forwarded-Proto');
  expect(headers).not.toHaveProperty('x-forwarded-proto');
};

// Pull the headers option out of whichever axios call a handler made.
const upstreamHeaders = (mock: ReturnType<typeof vi.fn>): Record<string, string> => {
  const call = mock.mock.calls[0] ?? [];
  const options = call.find((arg: unknown, index: number) => index > 0 && arg && typeof arg === 'object' && 'headers' in (arg as object));
  return (options as { headers: Record<string, string> }).headers;
};

const okResponse = { status: 200, data: { definition: { pipelines: [] } } };

const CASES: Array<{ name: string; register: (router: never) => void; key: string; method: Verb }> = [
  { name: 'flows create', register: flowRoutes, key: 'POST /flows', method: 'post' },
  { name: 'flows get', register: flowRoutes, key: 'GET /flows/:flowId', method: 'get' },
  { name: 'flows list', register: flowRoutes, key: 'GET /flows', method: 'get' },
  { name: 'flows by project', register: flowRoutes, key: 'GET /projects/:projectId/flows', method: 'get' },
  { name: 'flows put', register: flowRoutes, key: 'PUT /flows/:flowId', method: 'put' },
  { name: 'flows delete', register: flowRoutes, key: 'DELETE /flows/:flowId', method: 'delete' },
  { name: 'flows bulk delete', register: flowRoutes, key: 'DELETE /flows', method: 'delete' },
  { name: 'job runs create', register: jobRunRoutes, key: 'POST /job_runs', method: 'post' },
  { name: 'job runs list', register: jobRunRoutes, key: 'GET /job_runs', method: 'get' },
  { name: 'job runs get', register: jobRunRoutes, key: 'GET /job_runs/:jobRunId', method: 'get' },
  { name: 'job runs cancel', register: jobRunRoutes, key: 'POST /job_runs/:jobRunId/cancel', method: 'post' },
  { name: 'job runs delete', register: jobRunRoutes, key: 'DELETE /job_runs/:jobRunId', method: 'delete' },
  { name: 'job runs flow definition', register: jobRunRoutes, key: 'GET /job_runs/:jobRunId/flow_definition', method: 'get' },
  { name: 'projects create', register: projectsRoutes, key: 'POST /projects', method: 'post' },
  { name: 'projects list', register: projectsRoutes, key: 'GET /projects', method: 'get' },
  { name: 'projects get', register: projectsRoutes, key: 'GET /projects/:projectId', method: 'get' },
  { name: 'projects put', register: projectsRoutes, key: 'PUT /projects/:projectId', method: 'put' },
  { name: 'projects patch', register: projectsRoutes, key: 'PATCH /projects/:projectId', method: 'patch' },
  { name: 'projects delete', register: projectsRoutes, key: 'DELETE /projects/:projectId', method: 'delete' },
  { name: 'validation', register: validationRoutes, key: 'POST /validation/validate', method: 'post' },
  { name: 'operator metadata', register: operatorRoutes, key: 'GET /fetchOperatorMetadata', method: 'get' },
  { name: 'operator enrich', register: operatorRoutes, key: 'POST /enrichFlowFeatures', method: 'post' },
  { name: 'provider models (inline Accept)', register: operatorRoutes, key: 'GET /providers/:provider/models', method: 'get' },
  { name: 'document classes (inline Accept)', register: documentClassRoutes, key: 'GET /documentClasses', method: 'get' },
];

describe('BFF header forwarding', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    process.env.BACKEND_API_URL = 'http://backend.test';
    (['get', 'post', 'put', 'patch', 'delete'] as Verb[]).forEach((verb) => {
      vi.mocked(axios[verb] as ReturnType<typeof vi.fn>).mockResolvedValue(okResponse);
    });
  });

  it.each(CASES)('forwards the four headers and not X-Forwarded-For: $name', async ({ register, key, method }) => {
    const handler = collectHandlers(register).get(key);
    expect(handler, key).toBeDefined();

    await handler!(makeReq(), makeRes());

    const mock = axios[method] as unknown as ReturnType<typeof vi.fn>;
    expect(mock).toHaveBeenCalled();
    expectForwarded(upstreamHeaders(mock));
  });

  it('forwards the headers on the GET that precedes a flow patch rename', async () => {
    const handler = collectHandlers(flowRoutes).get('PATCH /flows/:flowId')!;

    await handler(makeReq(), makeRes());

    expectForwarded(upstreamHeaders(axios.get as unknown as ReturnType<typeof vi.fn>));
    expectForwarded(upstreamHeaders(axios.patch as unknown as ReturnType<typeof vi.fn>));
  });

  it('keeps Accept: text/csv and forwards the headers on the report download', async () => {
    const stream = new PassThrough();
    vi.mocked(axios.get).mockResolvedValue({ status: 200, data: stream });
    const handler = collectHandlers(jobRunRoutes).get('GET /job_runs/:jobRunId/report')!;
    const res = Object.assign(new PassThrough(), makeRes());

    await handler(makeReq(), res);

    const headers = upstreamHeaders(axios.get as unknown as ReturnType<typeof vi.fn>);
    expect(headers.Accept).toBe('text/csv');
    expectForwarded(headers);
  });

  it('keeps the inline Accept header on provider models and document classes', async () => {
    await collectHandlers(operatorRoutes).get('GET /providers/:provider/models')!(makeReq(), makeRes());
    expect(upstreamHeaders(axios.get as unknown as ReturnType<typeof vi.fn>).Accept).toBe('application/json');

    vi.mocked(axios.get).mockClear();
    await collectHandlers(documentClassRoutes).get('GET /documentClasses')!(makeReq(), makeRes());
    expect(upstreamHeaders(axios.get as unknown as ReturnType<typeof vi.fn>).Accept).toBe('application/json');
  });
});

describe('downloadJobRunReport upstream errors', () => {
  const handlerFor = () => collectHandlers(jobRunRoutes).get('GET /job_runs/:jobRunId/report')!;

  beforeEach(() => {
    vi.resetAllMocks();
    process.env.BACKEND_API_URL = 'http://backend.test';
  });

  it.each([401, 403])('answers upstream %i with the same status and a JSON body for a stream response', async (status) => {
    const stream = new PassThrough();
    vi.mocked(axios.get).mockRejectedValue({ message: 'denied', response: { status, data: stream } });
    const res = makeRes();

    await handlerFor()(makeReq(), res);

    expect(res.status).toHaveBeenCalledWith(status);
    expect(res.json).toHaveBeenCalledWith({ error: 'Failed to download job run report' });
  });

  it('relays a JSON upstream body unchanged', async () => {
    vi.mocked(axios.get).mockRejectedValue({ message: 'denied', response: { status: 403, data: { detail: 'Forbidden' } } });
    const res = makeRes();

    await handlerFor()(makeReq(), res);

    expect(res.status).toHaveBeenCalledWith(403);
    expect(res.json).toHaveBeenCalledWith({ detail: 'Forbidden' });
  });

  it('answers 500 with the generic error when there is no upstream response', async () => {
    vi.mocked(axios.get).mockRejectedValue(new Error('ECONNREFUSED'));
    const res = makeRes();

    await handlerFor()(makeReq(), res);

    expect(res.status).toHaveBeenCalledWith(500);
    expect(res.json).toHaveBeenCalledWith({ error: 'Failed to download job run report' });
  });

  it('pipes a successful report and destroys the response on a stream error', async () => {
    const stream = new EventEmitter() as EventEmitter & { pipe: ReturnType<typeof vi.fn> };
    stream.pipe = vi.fn();
    vi.mocked(axios.get).mockResolvedValue({ status: 200, data: stream });
    const res = makeRes();

    await handlerFor()(makeReq(), res);

    expect(res.headers['Content-Type']).toBe('text/csv');
    expect(stream.pipe).toHaveBeenCalledWith(res);
    stream.emit('error', new Error('boom'));
    expect(res.destroy).toHaveBeenCalled();
  });
});
