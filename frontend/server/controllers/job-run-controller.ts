import type { Request, Response, Router } from 'express';
import { log4js, logUtil } from '../../src/utils/logger';
import { handleProxyError, proxyRequest } from '../utils/proxy';
import { queryString, routeParam } from '../utils/query';

const logger = log4js.getLogger('job-run.controller');

/**
 * Create a new job run
 * BFF controller that proxies job run creation to Python FastAPI backend
 */
const createJobRun = async (req: Request, res: Response): Promise<void> => {
  try {
    const response = await proxyRequest({ method: 'POST', path: ['api', 'v1', 'job_runs'], body: req.body });

    res.status(response.status).json(response.data);
  } catch (err) {
    await handleProxyError({ res, err, logger, fallbackMessage: 'Failed to create job run' });
  }
};

/**
 * List job runs
 * BFF controller that proxies job run listing to Python FastAPI backend
 */
const getJobRuns = async (req: Request, res: Response): Promise<void> => {
  try {
    const { job_id, status, limit } = req.query;

    const response = await proxyRequest({
      method: 'GET',
      path: ['api', 'v1', 'job_runs'],
      query: {
        limit: queryString(limit) ?? '100',
        job_id: queryString(job_id) || undefined,
        status: queryString(status) || undefined,
      },
    });

    res.json(response.data);
  } catch (err) {
    await handleProxyError({ res, err, logger, fallbackMessage: 'Failed to list job runs' });
  }
};

/**
 * Get job run status
 * BFF controller that proxies job run retrieval to Python FastAPI backend
 */
const getJobRun = async (req: Request, res: Response): Promise<void> => {
  try {
    const jobRunId = routeParam(req.params.jobRunId);
    const response = await proxyRequest({
      method: 'GET',
      path: ['api', 'v1', 'job_runs', jobRunId],
      query: { include_logs: queryString(req.query.include_logs) ?? 'false' },
    });

    res.json(response.data);
  } catch (err) {
    await handleProxyError({ res, err, logger, fallbackMessage: 'Failed to fetch job run' });
  }
};

/**
 * Cancel a job run
 * BFF controller that proxies job run cancellation to Python FastAPI backend
 */
const cancelJobRun = async (req: Request, res: Response): Promise<void> => {
  try {
    const jobRunId = routeParam(req.params.jobRunId);

    const response = await proxyRequest({ method: 'POST', path: ['api', 'v1', 'job_runs', jobRunId, 'cancel'], body: {} });

    res.status(response.status).json(response.data);
  } catch (err) {
    await handleProxyError({ res, err, logger, fallbackMessage: 'Failed to cancel job run' });
  }
};

/**
 * Delete a job run
 * BFF controller that proxies job run deletion to Python FastAPI backend
 */
const deleteJobRun = async (req: Request, res: Response): Promise<void> => {
  try {
    const jobRunId = routeParam(req.params.jobRunId);

    const response = await proxyRequest({ method: 'DELETE', path: ['api', 'v1', 'job_runs', jobRunId] });

    res.status(response.status).send();
  } catch (err) {
    await handleProxyError({ res, err, logger, fallbackMessage: 'Failed to delete job run' });
  }
};

/**
 * Download job run report
 * BFF controller that proxies job run report download to Python FastAPI backend
 */
const downloadJobRunReport = async (req: Request, res: Response): Promise<void> => {
  try {
    const jobRunId = routeParam(req.params.jobRunId);

    const response = await proxyRequest({
      method: 'GET',
      path: ['api', 'v1', 'job_runs', jobRunId, 'report'],
      accept: 'text/csv',
      responseType: 'stream',
    });

    res.setHeader('Content-Type', 'text/csv');
    res.setHeader('Content-Disposition', `attachment; filename="job-run-${jobRunId}-report.csv"`);
    res.status(response.status);

    response.data.on('error', (streamError: Error) => {
      logUtil.error({ logger, message: 'Stream error downloading job run report', data: streamError.message });
      res.destroy();
    });

    response.data.pipe(res);
  } catch (err) {
    await handleProxyError({ res, err, logger, fallbackMessage: 'Failed to download job run report' });
  }
};

/**
 * Get flow definition snapshot for a job run
 * BFF controller that proxies flow definition retrieval to Python FastAPI backend
 */
const getJobRunFlowDefinition = async (req: Request, res: Response): Promise<void> => {
  try {
    const jobRunId = routeParam(req.params.jobRunId);

    const response = await proxyRequest({ method: 'GET', path: ['api', 'v1', 'job_runs', jobRunId, 'flow_definition'] });

    res.json(response.data);
  } catch (err) {
    await handleProxyError({ res, err, logger, fallbackMessage: 'Failed to fetch flow definition snapshot' });
  }
};

/**
 * Export routes function that registers all job run endpoints
 */
export const routes = (router: Router): void => {
  router.post('/job_runs', createJobRun);
  router.get('/job_runs', getJobRuns);
  router.get('/job_runs/:jobRunId', getJobRun);
  router.post('/job_runs/:jobRunId/cancel', cancelJobRun);
  router.delete('/job_runs/:jobRunId', deleteJobRun);
  router.get('/job_runs/:jobRunId/report', downloadJobRunReport);
  router.get('/job_runs/:jobRunId/flow_definition', getJobRunFlowDefinition);
};
