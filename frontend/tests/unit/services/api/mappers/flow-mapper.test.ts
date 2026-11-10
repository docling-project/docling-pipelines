import { describe, it, expect } from 'vitest';
import { fromResponse, toCreateRequest, toPatchRequest, flowResponseToRow } from '@/services/api/mappers/flow-mapper';
import type { Flow } from '@/types';

const fullFlow: Flow = {
  flow_id: 'flow-1',
  container_id: 'project-1',
  container_kind: 'project',
  name: 'Test Flow',
  description: 'A test flow',
  tags: ['test'],
  created_on: '2024-01-15T10:00:00Z',
  modified_on: '2024-01-16T10:00:00Z',
  job_run_summary: {
    total_runs: 5,
    last_run_id: 'run-5',
    last_run_status: 'Failed',
    last_run_start_time: 1705329000,
    status_counts: { Completed: 3, Failed: 2 },
  },
};

describe('fromResponse', () => {
  it('maps all fields correctly', () => {
    const row = fromResponse(fullFlow);
    expect(row.flow_id).toBe('flow-1');
    expect(row.project_id).toBe('project-1');
    expect(row.name).toBe('Test Flow');
    expect(row.description).toBe('A test flow');
    expect(row.tags).toEqual(['test']);
    expect(row.created_on).toBe('2024-01-15T10:00:00Z');
    expect(row.modified_on).toBe('2024-01-16T10:00:00Z');
  });

  it('preserves created_by as the flow owner', () => {
    expect(fromResponse({ ...fullFlow, created_by: 'alice' }).created_by).toBe('alice');
  });

  it('maps a missing created_by to null (ownerless flow)', () => {
    expect(fromResponse(fullFlow).created_by).toBeNull();
  });

  it('run_count from job_run_summary.total_runs', () => {
    const row = fromResponse(fullFlow);
    expect(row.run_count).toBe(5);
  });

  it('run_status has errors when Failed status present', () => {
    const row = fromResponse(fullFlow);
    expect(row.run_status?.errors).toBe(2);
  });

  it('run_status is null when no job_run_summary', () => {
    const row = fromResponse({ ...fullFlow, job_run_summary: null });
    expect(row.run_status).toBeNull();
    expect(row.run_count).toBeNull();
  });

  it('run_status has running > 0 for Running status', () => {
    const flow = {
      ...fullFlow,
      job_run_summary: {
        total_runs: 1,
        last_run_id: 'r-1',
        last_run_status: 'Running',
        last_run_start_time: null,
        status_counts: { Running: 1 },
      },
    };
    const row = fromResponse(flow);
    expect(row.run_status?.running).toBe(1);
  });

  it('defaults empty strings for missing fields', () => {
    const row = fromResponse({});
    expect(row.flow_id).toBe('');
    expect(row.name).toBe('');
  });
});

describe('toCreateRequest', () => {
  it('output matches expected POST shape', () => {
    const result = toCreateRequest(
      { name: 'New Flow', description: 'A new flow', tags: ['tag1'] },
      'project-1',
      { doc_type: 'pipeline', version: '3.0' }
    );
    expect(result.container_id).toBe('project-1');
    expect(result.container_kind).toBe('project');
    expect(result.name).toBe('New Flow');
    expect(result.tags).toEqual(['tag1']);
    expect(result.definition).toBeDefined();
  });

  it('empty description → description field is undefined', () => {
    const result = toCreateRequest(
      { name: 'Flow', description: '', tags: [] },
      'p-1',
      {}
    );
    expect(result.description).toBeUndefined();
  });
});

describe('toPatchRequest', () => {
  it('output contains name, description, and tags', () => {
    const result = toPatchRequest({ name: 'Updated', description: 'New desc', tags: ['a'] });
    expect(result.name).toBe('Updated');
    expect(result.description).toBe('New desc');
    expect(result.tags).toEqual(['a']);
  });

  it('empty description → description is undefined', () => {
    const result = toPatchRequest({ name: 'Flow', description: '', tags: [] });
    expect(result.description).toBeUndefined();
  });
});

describe('flowResponseToRow (alias)', () => {
  it('is the same function as fromResponse', () => {
    const row1 = fromResponse(fullFlow);
    const row2 = flowResponseToRow(fullFlow);
    expect(row1).toEqual(row2);
  });
});
