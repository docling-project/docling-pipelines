import axios from 'axios';
import type { Request, Response, Router } from 'express';
import { log4js, logUtil } from '../../src/utils/logger';
import { BODY_HEADERS, NO_BODY_HEADERS, buildForwardHeaders } from './http-headers';

const logger = log4js.getLogger('job-run.controller');

/**
 * Create a new job run
 * BFF controller that proxies job run creation to Python FastAPI backend
 */
const createJobRun = async (req: Request, res: Response) => {
  try {
    const requestUrl = `${process.env.BACKEND_API_URL}/api/v1/job_runs`;

    const response = await axios.post(requestUrl, req.body, { headers: buildForwardHeaders(req, BODY_HEADERS) });

    res.status(response.status).json(response.data);

  } catch (error) {
    logUtil.error({ logger, message: 'Error creating job run', data: error.message });

    const status = error.response?.status ?? 500;
    const errorData = error.response?.data ?? { error: 'Failed to create job run' };

    res.status(status).json(errorData);
  }
};

/**
 * List job runs
 * BFF controller that proxies job run listing to Python FastAPI backend
 */
const getJobRuns = async (req: Request, res: Response) => {
  try {
    const { job_id, status, limit = 100 } = req.query;

    const params = new URLSearchParams({ limit: limit.toString() });

    if (job_id) params.append('job_id', job_id);
    if (status) params.append('status', status);

    const requestUrl = `${process.env.BACKEND_API_URL}/api/v1/job_runs?${params.toString()}`;
    logUtil.debug({ logger, message: 'Request URL', data: requestUrl });

    const response = await axios.get(requestUrl, { headers: buildForwardHeaders(req, NO_BODY_HEADERS) });

    res.json(response.data);

  } catch (error) {
    logUtil.error({ logger, message: 'Error listing job runs', data: error.message });

    const status = error.response?.status ?? 500;
    const errorData = error.response?.data ?? { error: 'Failed to list job runs' };

    res.status(status).json(errorData);
  }
};

/**
 * Get job run status
 * BFF controller that proxies job run retrieval to Python FastAPI backend
 */
const getJobRun = async (req: Request, res: Response) => {
  try {
    const { jobRunId } = req.params;
    const { include_logs = false } = req.query;

    const params = new URLSearchParams({ include_logs: include_logs.toString() });
    const requestUrl = `${process.env.BACKEND_API_URL}/api/v1/job_runs/${jobRunId}?${params.toString()}`;

    const response = await axios.get(requestUrl, { headers: buildForwardHeaders(req, NO_BODY_HEADERS) });

    res.json(response.data);

  } catch (error) {
    logUtil.error({ logger, message: 'Error fetching job run', data: error.message });

    const status = error.response?.status ?? 500;
    const errorData = error.response?.data ?? { error: 'Failed to fetch job run' };

    res.status(status).json(errorData);
  }
};

/**
 * Cancel a job run
 * BFF controller that proxies job run cancellation to Python FastAPI backend
 */
const cancelJobRun = async (req: Request, res: Response) => {
  try {
    const { jobRunId } = req.params;
    const requestUrl = `${process.env.BACKEND_API_URL}/api/v1/job_runs/${jobRunId}/cancel`;

    const response = await axios.post(requestUrl, {}, { headers: buildForwardHeaders(req, BODY_HEADERS) });

    res.status(response.status).json(response.data);

  } catch (error) {
    logUtil.error({ logger, message: 'Error cancelling job run', data: error.message });

    const status = error.response?.status ?? 500;
    const errorData = error.response?.data ?? { error: 'Failed to cancel job run' };

    res.status(status).json(errorData);
  }
};

/**
 * Delete a job run
 * BFF controller that proxies job run deletion to Python FastAPI backend
 */
const deleteJobRun = async (req: Request, res: Response) => {
  try {
    const { jobRunId } = req.params;
    const requestUrl = `${process.env.BACKEND_API_URL}/api/v1/job_runs/${jobRunId}`;

    const response = await axios.delete(requestUrl, { headers: buildForwardHeaders(req, NO_BODY_HEADERS) });

    res.status(response.status).send();

  } catch (error) {
    logUtil.error({ logger, message: 'Error deleting job run', data: error.message });

    const status = error.response?.status ?? 500;
    const errorData = error.response?.data ?? { error: 'Failed to delete job run' };

    res.status(status).json(errorData);
  }
};

const isReadableStream = (value: unknown): boolean =>
  typeof value === 'object' && value !== null && typeof (value as { pipe?: unknown }).pipe === 'function';

/**
 * Download job run report
 * BFF controller that proxies job run report download to Python FastAPI backend
 */
const downloadJobRunReport = async (req: Request, res: Response) => {
  try {
    const { jobRunId } = req.params;
    const requestUrl = `${process.env.BACKEND_API_URL}/api/v1/job_runs/${jobRunId}/report`;

    const response = await axios.get(requestUrl, {
      headers: buildForwardHeaders(req, { Accept: 'text/csv' }),
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

  } catch (error) {
    logUtil.error({ logger, message: 'Error downloading job run report', data: error.message });

    const status = error.response?.status ?? 500;
    // With responseType 'stream' the upstream error body is a stream, which
    // cannot be serialised as JSON, so fall back to a generic message.
    const upstreamBody = error.response?.data;
    const errorData = isReadableStream(upstreamBody) || upstreamBody === undefined || upstreamBody === null
      ? { error: 'Failed to download job run report' }
      : upstreamBody;

    res.status(status).json(errorData);
  }
};

/**
 * Get flow definition snapshot for a job run
 * BFF controller that proxies flow definition retrieval to Python FastAPI backend
 */
const getJobRunFlowDefinition = async (req: Request, res: Response) => {
  try {
    const { jobRunId } = req.params;
    const requestUrl = `${process.env.BACKEND_API_URL}/api/v1/job_runs/${jobRunId}/flow_definition`;

    const response = await axios.get(requestUrl, { headers: buildForwardHeaders(req, NO_BODY_HEADERS) });

    res.json(response.data);

  } catch (error) {
    logUtil.error({ logger, message: 'Error fetching flow definition snapshot', data: error.message });

    const status = error.response?.status ?? 500;
    const errorData = error.response?.data ?? { error: 'Failed to fetch flow definition snapshot' };

    res.status(status).json(errorData);
  }
};

/**
 * Export routes function that registers all job run endpoints
 */
export const routes = (router: Router) => {
  router.post('/job_runs', createJobRun);
  router.get('/job_runs', getJobRuns);
  router.get('/job_runs/:jobRunId', getJobRun);
  router.post('/job_runs/:jobRunId/cancel', cancelJobRun);
  router.delete('/job_runs/:jobRunId', deleteJobRun);
  router.get('/job_runs/:jobRunId/report', downloadJobRunReport);
  router.get('/job_runs/:jobRunId/flow_definition', getJobRunFlowDefinition);
};
