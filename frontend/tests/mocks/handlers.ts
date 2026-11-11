import { http, HttpResponse } from 'msw';
import {
  flowFixture,
  paginatedFlowResponseFixture,
} from './fixtures/flow.fixture';
import {
  projectFixture,
  paginatedProjectResponseFixture,
} from './fixtures/project.fixture';
import { jobRunFixture, jobRunStatusResponseFixture } from './fixtures/jobRun.fixture';
import { operatorsFixture } from './fixtures/operator.fixture';

export const handlers = [
  // Flows
  http.get('/api/flows', () =>
    HttpResponse.json(paginatedFlowResponseFixture)
  ),
  http.get('/api/flows/:id', ({ params }) =>
    HttpResponse.json({ ...flowFixture, flow_id: params['id'] as string })
  ),
  http.post('/api/flows', async ({ request }) => {
    const body = await request.json() as Record<string, unknown>;
    return HttpResponse.json({ ...flowFixture, ...body, flow_id: 'new-flow-id' }, { status: 201 });
  }),
  http.put('/api/flows/:id', async ({ params, request }) => {
    const body = await request.json() as Record<string, unknown>;
    return HttpResponse.json({ ...flowFixture, ...body, flow_id: params['id'] as string });
  }),
  http.patch('/api/flows/:id', async ({ params, request }) => {
    const body = await request.json() as Record<string, unknown>;
    return HttpResponse.json({ ...flowFixture, ...body, flow_id: params['id'] as string });
  }),
  http.delete('/api/flows/:id', () => new HttpResponse(null, { status: 204 })),

  // Flow run
  http.post('/api/flows/:id/run', ({ params }) =>
    HttpResponse.json({ ...jobRunFixture, jobId: params['id'] as string }, { status: 201 })
  ),

  // Flow enrichment
  http.post('/api/flows/enrich', () =>
    HttpResponse.json({ nodes: {} })
  ),

  // Projects
  http.get('/api/projects', () =>
    HttpResponse.json(paginatedProjectResponseFixture)
  ),
  http.get('/api/projects/:id', ({ params }) =>
    HttpResponse.json({ ...projectFixture, project_id: params['id'] as string })
  ),
  http.post('/api/projects', async ({ request }) => {
    const body = await request.json() as Record<string, unknown>;
    return HttpResponse.json(
      { ...projectFixture, ...body, project_id: 'new-project-id' },
      { status: 201 }
    );
  }),
  http.patch('/api/projects/:id', async ({ params, request }) => {
    const body = await request.json() as Record<string, unknown>;
    return HttpResponse.json({ ...projectFixture, ...body, project_id: params['id'] as string });
  }),
  http.delete('/api/projects/:id', () => new HttpResponse(null, { status: 204 })),

  // Project flows
  http.get('/api/projects/:id/flows', () =>
    HttpResponse.json(paginatedFlowResponseFixture)
  ),

  // Operators
  http.get('/api/operators', () => HttpResponse.json(operatorsFixture)),

  // Job runs
  http.get('/api/job-runs', () =>
    HttpResponse.json({ list: [], count: 0, total: 0 })
  ),
  // BFF job_runs list (underscore, query param job_id — used by FlowDetail + FlowRunHistory)
  http.get('/api/job_runs', ({ request }) => {
    const url = new URL(request.url);
    const jobId = url.searchParams.get('job_id');
    return HttpResponse.json({
      list: jobId ? [{ job_run_id: 'run-1', job_id: jobId, status: 'Completed', start_time: 1705329000, end_time: 1705329300, duration: 300 }] : [],
      count: jobId ? 1 : 0,
      total: jobId ? 1 : 0,
    });
  }),
  http.get('/api/job-runs/:id', ({ params }) =>
    HttpResponse.json({ ...jobRunStatusResponseFixture, job_run_id: params['id'] as string })
  ),

  // BFF job_runs (underscore — used by job-run-actions.ts)
  http.get('/api/job_runs/:id/flow_definition', () =>
    HttpResponse.json({
      doc_type: 'pipeline',
      version: '3.0',
      pipelines: [{ id: 'pipeline-1', nodes: [] }],
    })
  ),

  // Document classes
  http.get('/api/document-classes', () => HttpResponse.json([])),

  // Provider models (used by Embeddings panel)
  http.get('/api/providers/:provider/models', () =>
    HttpResponse.json({ provider: 'ollama', models: [] })
  ),

  // BFF-specific operator endpoints
  http.get('/api/fetchOperatorMetadata', () =>
    HttpResponse.json(operatorsFixture)
  ),
  http.post('/api/enrichFlowFeatures', () =>
    HttpResponse.json({ nodes: {} })
  ),

  // BFF-specific job_runs
  http.post('/api/job_runs', () =>
    HttpResponse.json({ job_run_id: 'run-new', status: 'Queued', message: 'Queued' }, { status: 201 })
  ),
  http.get('/api/job_runs/:id', ({ params }) =>
    HttpResponse.json({ ...jobRunStatusResponseFixture, job_run_id: params['id'] as string })
  ),
  http.delete('/api/job_runs/:id', () => new HttpResponse(null, { status: 204 })),

  // Flow validation (used by Canvas save + run)
  http.post('/api/validate-flow', () =>
    HttpResponse.json({ status: 'succeeded', errors: [], warnings: [], message: null })
  ),
];
