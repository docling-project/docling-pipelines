import { describe, it, expect, vi } from 'vitest';
import { server } from '../../../../mocks/server';
import { http, HttpResponse } from 'msw';
import {
  createJobRun,
  getJobRun,
  getJobRuns,
  cancelJobRun,
  deleteJobRun,
} from '@/services/api/actions/job-run-actions';

describe('job-run-actions', () => {

  describe('createJobRun', () => {
    it('calls POST /api/job_runs and returns data', async () => {
      server.use(
        http.post('/api/job_runs', () =>
          HttpResponse.json({ job_run_id: 'jr-1', status: 'pending' })
        )
      );
      const res = await createJobRun({ flow_id: 'f-1' });
      expect(res.data.job_run_id).toBe('jr-1');
      expect(res.data.status).toBe('pending');
    });

    it('throws on server error', async () => {
      server.use(
        http.post('/api/job_runs', () => HttpResponse.json({ error: 'fail' }, { status: 500 }))
      );
      await expect(createJobRun({})).rejects.toBeDefined();
    });
  });

  describe('getJobRun', () => {
    it('calls GET /api/job_runs/:id and returns data', async () => {
      server.use(
        http.get('/api/job_runs/jr-42', () =>
          HttpResponse.json({ job_run_id: 'jr-42', status: 'completed' })
        )
      );
      const res = await getJobRun('jr-42');
      expect(res.data.job_run_id).toBe('jr-42');
    });
  });

  describe('getJobRuns', () => {
    it('calls GET /api/job_runs and returns list', async () => {
      server.use(
        http.get('/api/job_runs', () =>
          HttpResponse.json({ items: [], count: 0, total: 0 })
        )
      );
      const res = await getJobRuns();
      expect(res.data.count).toBe(0);
    });

    it('rejects without logging an error when the request is aborted', async () => {
      server.use(
        http.get('/api/job_runs', async () => {
          await new Promise((resolve) => setTimeout(resolve, 200));
          return HttpResponse.json({ list: [], count: 0, total: 0 });
        })
      );
      const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
      const ac = new AbortController();

      const pending = getJobRuns({ job_id: 'f-1' }, ac.signal);
      ac.abort();

      await expect(pending).rejects.toBeDefined();
      expect(errorSpy).not.toHaveBeenCalled();
      errorSpy.mockRestore();
    });

    it('still logs an error when the request fails', async () => {
      server.use(
        http.get('/api/job_runs', () => HttpResponse.json({ error: 'fail' }, { status: 500 }))
      );
      const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);

      await expect(getJobRuns({ job_id: 'f-1' })).rejects.toBeDefined();
      expect(errorSpy).toHaveBeenCalled();
      errorSpy.mockRestore();
    });
  });

  describe('cancelJobRun', () => {
    it('calls POST /api/job_runs/:id/cancel', async () => {
      server.use(
        http.post('/api/job_runs/jr-1/cancel', () =>
          HttpResponse.json({ job_run_id: 'jr-1', status: 'cancelled' })
        )
      );
      const res = await cancelJobRun('jr-1');
      expect(res.data.status).toBe('cancelled');
    });
  });

  describe('deleteJobRun', () => {
    it('calls DELETE /api/job_runs/:id', async () => {
      server.use(
        http.delete('/api/job_runs/jr-1', () => new HttpResponse(null, { status: 204 }))
      );
      const res = await deleteJobRun('jr-1');
      expect(res.status).toBe(204);
    });
  });
});
