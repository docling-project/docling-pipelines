/**
 * Job Run Actions
 *
 * HTTP calls to BFF endpoints (not backend API directly).
 * These call the BFF server which proxies to the Python backend.
 */

import axios, { type AxiosResponse } from 'axios';
import { log4js, logUtil } from '@/utils/logger';
import type {
  JobRunCreateResponse,
  JobRunStatusResponse,
  JobRunListResponse,
  JobRunCancelResponse,
} from '@/types';
import { apiClient } from '../client';

const logger = log4js.getLogger('job-run.actions');

const BFF_HEADERS = {
  'Accept': 'application/json',
  'X-Requested-With': 'XMLHttpRequest',
  // Prevent browser caching of poll responses — ensures 10-second poll always
  // gets fresh data rather than a 304 Not Modified from a stale ETag.
  'Cache-Control': 'no-cache',
};

/**
 * Create a new job run via BFF
 *
 * Calls BFF endpoint: /api/job_runs
 * BFF proxies to Python backend: /api/v1/job_runs
 */
export const createJobRun = async (
  body: Record<string, unknown>
): Promise<AxiosResponse<JobRunCreateResponse>> => {
  const url = '/api/job_runs';

  try {
    const response = await apiClient.post<JobRunCreateResponse>(url, body, { headers: BFF_HEADERS });

    logUtil.info({
      logger,
      message: 'Successfully created job run',
      data: { jobRunId: response.data.job_run_id, status: response.data.status },
    });

    return response;

  } catch (error) {
    logUtil.error({
      logger,
      message: 'Failed to create job run',
      data: error,
    });
    throw error;
  }
};

/**
 * List job runs via BFF
 *
 * Calls BFF endpoint: /api/job_runs
 * BFF proxies to Python backend: /api/v1/job_runs
 */
export const getJobRuns = async (params?: {
  job_id?: string;
  status?: string;
  limit?: number;
}, signal?: AbortSignal): Promise<AxiosResponse<JobRunListResponse>> => {
  const queryParams = new URLSearchParams();

  if (params?.job_id) { queryParams.append('job_id', params.job_id); }
  if (params?.status) { queryParams.append('status', params.status); }
  if (params?.limit !== undefined) { queryParams.append('limit', params.limit.toString()); }

  const url = `/api/job_runs${queryParams.toString() ? `?${queryParams.toString()}` : ''}`;

  try {
    const response = await apiClient.get<JobRunListResponse>(url, { headers: BFF_HEADERS, signal });

    logUtil.info({
      logger,
      message: 'Successfully listed job runs',
      data: { count: response.data.count, total: response.data.total },
    });

    return response;

  } catch (error) {
    // An aborted request is expected (e.g. polling cleanup), not a failure.
    if (!axios.isCancel(error)) {
      logUtil.error({
        logger,
        message: 'Failed to list job runs',
        data: error,
      });
    }
    throw error;
  }
};

/**
 * Get job run status via BFF
 *
 * Calls BFF endpoint: /api/job_runs/:jobRunId
 * BFF proxies to Python backend: /api/v1/job_runs/:jobRunId
 */
export const getJobRun = async (
  jobRunId: string,
  includeLogs = false,
  signal?: AbortSignal
): Promise<AxiosResponse<JobRunStatusResponse>> => {
  const params = new URLSearchParams({ include_logs: includeLogs.toString() });
  const url = `/api/job_runs/${jobRunId}?${params.toString()}`;

  try {
    const response = await apiClient.get<JobRunStatusResponse>(url, { headers: BFF_HEADERS, signal });

    logUtil.info({
      logger,
      message: 'Successfully fetched job run',
      data: { jobRunId },
    });

    return response;

  } catch (error) {
    logUtil.error({
      logger,
      message: 'Failed to fetch job run',
      data: { jobRunId, error },
    });
    throw error;
  }
};

/**
 * Cancel a job run via BFF
 *
 * Calls BFF endpoint: /api/job_runs/:jobRunId/cancel
 * BFF proxies to Python backend: /api/v1/job_runs/:jobRunId/cancel
 */
export const cancelJobRun = async (
  jobRunId: string
): Promise<AxiosResponse<JobRunCancelResponse>> => {
  const url = `/api/job_runs/${jobRunId}/cancel`;

  try {
    const response = await apiClient.post<JobRunCancelResponse>(url, {}, { headers: BFF_HEADERS });

    logUtil.info({
      logger,
      message: 'Successfully requested job run cancellation',
      data: { jobRunId, status: response.data.status },
    });

    return response;

  } catch (error) {
    logUtil.error({
      logger,
      message: 'Failed to cancel job run',
      data: { jobRunId, error },
    });
    throw error;
  }
};

/**
 * Delete a job run via BFF
 *
 * Calls BFF endpoint: /api/job_runs/:jobRunId
 * BFF proxies to Python backend: /api/v1/job_runs/:jobRunId
 */
export const deleteJobRun = async (jobRunId: string): Promise<AxiosResponse<void>> => {
  const url = `/api/job_runs/${jobRunId}`;

  try {
    const response = await apiClient.delete<void>(url, { headers: BFF_HEADERS });

    logUtil.info({
      logger,
      message: 'Successfully deleted job run',
      data: { jobRunId },
    });

    return response;

  } catch (error) {
    logUtil.error({
      logger,
      message: 'Failed to delete job run',
      data: { jobRunId, error },
    });
    throw error;
  }
};

/**
 * Download job run report via BFF
 *
 * Calls BFF endpoint: /api/job_runs/:jobRunId/report
 * BFF proxies to Python backend: /api/v1/job_runs/:jobRunId/report
 */
export const downloadJobRunReport = async (jobRunId: string): Promise<AxiosResponse<Blob>> => {
  const url = `/api/job_runs/${jobRunId}/report`;

  try {
    const response = await apiClient.get<Blob>(url, {
      headers: { ...BFF_HEADERS, 'Accept': 'text/csv' },
      responseType: 'blob',
    });

    logUtil.info({
      logger,
      message: 'Successfully downloaded job run report',
      data: { jobRunId },
    });

    return response;

  } catch (error) {
    logUtil.error({
      logger,
      message: 'Failed to download job run report',
      data: { jobRunId, error },
    });
    throw error;
  }
};

/**
 * Get flow definition snapshot for a job run via BFF
 *
 * Calls BFF endpoint: /api/job_runs/:jobRunId/flow_definition
 * BFF proxies to Python backend: /api/v1/job_runs/:jobRunId/flow_definition
 */
export const getJobRunFlowDefinition = async (
  jobRunId: string
): Promise<AxiosResponse<Record<string, unknown>>> => {
  const url = `/api/job_runs/${jobRunId}/flow_definition`;

  try {
    const response = await apiClient.get<Record<string, unknown>>(url, { headers: BFF_HEADERS });

    logUtil.info({
      logger,
      message: 'Successfully fetched flow definition snapshot',
      data: { jobRunId },
    });

    return response;

  } catch (error) {
    logUtil.error({
      logger,
      message: 'Failed to fetch flow definition snapshot',
      data: { jobRunId, error },
    });
    throw error;
  }
};
