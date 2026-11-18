/**
 * Flow Actions
 *
 * HTTP calls to BFF endpoints (not backend API directly).
 * These call the BFF server which proxies to the Python backend.
 * is_elyra is hard-coded as true in the BFF controller for all flow endpoints — never passed from here.
 */

import { type AxiosResponse } from 'axios';
import { log4js, logUtil } from '@/utils/logger';
import type { Flow, PaginatedFlowResponse } from '@/types';
import { apiClient } from '../client';

const logger = log4js.getLogger('flow.actions');

const BFF_HEADERS = {
  'Accept': 'application/json',
  'X-Requested-With': 'XMLHttpRequest',
};

/**
 * Create a new flow via BFF
 *
 * Calls BFF endpoint: /api/flows
 * BFF proxies to Python backend: /api/v1/flows?is_elyra=true
 */
export const createFlow = async (
  flowData: Partial<Flow>
): Promise<AxiosResponse<Flow>> => {
  const url = '/api/flows';

  try {
    const response = await apiClient.post<Flow>(url, flowData, { headers: BFF_HEADERS });

    logUtil.info({
      logger,
      message: 'Successfully created flow',
      data: { flowId: response.data.flow_id, name: response.data.name },
    });

    return response;

  } catch (error) {
    logUtil.error({
      logger,
      message: 'Failed to create flow',
      data: error,
    });
    throw error;
  }
};

/**
 * Get flow by ID via BFF
 */
export const getFlow = async (flowId: string): Promise<AxiosResponse<Flow>> => {
  const url = `/api/flows/${flowId}`;

  try {
    const response = await apiClient.get<Flow>(url, { headers: BFF_HEADERS });

    logUtil.info({
      logger,
      message: 'Successfully fetched flow',
      data: { flowId: response.data.flow_id, name: response.data.name },
    });

    return response;

  } catch (error) {
    logUtil.error({
      logger,
      message: 'Failed to fetch flow',
      data: { flowId, error },
    });
    throw error;
  }
};

/**
 * List flows for a specific project via BFF.
 *
 * Calls BFF endpoint: GET /api/projects/:projectId/flows
 * BFF proxies to Python backend: GET /api/v1/projects/:projectId/flows?is_elyra=true
 */
export const getFlowsByProjectId = async (
  projectId: string,
  params?: {
    limit?: number;
    offset?: number;
    name?: string;
    tags?: string[];
  }
): Promise<AxiosResponse<PaginatedFlowResponse>> => {
  const queryParams = new URLSearchParams();

  if (params?.limit !== undefined) { queryParams.append('limit', params.limit.toString()); }
  if (params?.offset !== undefined) { queryParams.append('offset', params.offset.toString()); }
  if (params?.name) { queryParams.append('name', params.name); }
  if (params?.tags) { params.tags.forEach((tag) => { queryParams.append('tags', tag); }); }

  const qs = queryParams.toString();
  const url = qs
    ? `/api/projects/${projectId}/flows?${qs}`
    : `/api/projects/${projectId}/flows`;

  try {
    const response = await apiClient.get<PaginatedFlowResponse>(url, { headers: BFF_HEADERS });

    logUtil.info({
      logger,
      message: 'Successfully listed flows for project',
      data: { projectId, count: response.data.flows.length, total: response.data.total_count },
    });

    return response;

  } catch (error) {
    logUtil.error({
      logger,
      message: 'Failed to list flows for project',
      data: { projectId, error },
    });
    throw error;
  }
};

/**
 * List flows with pagination and filtering via BFF.
 *
 * Calls BFF endpoint: `GET /api/flows`
 * BFF hard-codes `is_elyra=true` before proxying to the Python backend — do not pass it here.
 *
 * @param params.limit     - Maximum number of flows to return.
 * @param params.offset    - Pagination offset.
 * @param params.name      - Filter by flow name (substring match).
 * @param params.tags      - Filter by tag value.
 * @param params.is_hidden - When true, include hidden flows only.
 */
export const getFlows = async (params?: {
  limit?: number;
  offset?: number;
  name?: string;
  tags?: string;
  is_hidden?: boolean;
}): Promise<AxiosResponse<PaginatedFlowResponse>> => {
  const queryParams = new URLSearchParams();

  if (params?.limit !== undefined) { queryParams.append('limit', params.limit.toString()); }
  if (params?.offset !== undefined) { queryParams.append('offset', params.offset.toString()); }
  if (params?.name) { queryParams.append('name', params.name); }
  if (params?.tags) { queryParams.append('tags', params.tags); }
  if (params?.is_hidden !== undefined) { queryParams.append('is_hidden', params.is_hidden.toString()); }

  const qs = queryParams.toString();
  const url = qs ? `/api/flows?${qs}` : '/api/flows';

  try {
    const response = await apiClient.get<PaginatedFlowResponse>(url, { headers: BFF_HEADERS });

    logUtil.info({
      logger,
      message: 'Successfully listed flows',
      data: { count: response.data.flows.length, total: response.data.total_count },
    });

    return response;

  } catch (error) {
    logUtil.error({
      logger,
      message: 'Failed to list flows',
      data: error,
    });
    throw error;
  }
};

/**
 * Update flow (full replacement) via BFF
 */
export const updateFlow = async (
  flowId: string,
  flowData: Partial<Flow>
): Promise<AxiosResponse<Flow>> => {
  const url = `/api/flows/${flowId}`;

  try {
    const response = await apiClient.put<Flow>(url, flowData, { headers: BFF_HEADERS });

    logUtil.info({
      logger,
      message: 'Successfully updated flow',
      data: { flowId: response.data.flow_id, name: response.data.name },
    });

    return response;

  } catch (error) {
    logUtil.error({
      logger,
      message: 'Failed to update flow',
      data: { flowId, error },
    });
    throw error;
  }
};

/**
 * Patch flow via BFF
 */
export const patchFlow = async (
  flowId: string,
  updates: Partial<Flow>
): Promise<AxiosResponse<Flow>> => {
  const url = `/api/flows/${flowId}`;

  try {
    const response = await apiClient.patch<Flow>(url, updates, { headers: BFF_HEADERS });

    logUtil.info({
      logger,
      message: 'Successfully partially updated flow',
      data: { flowId: response.data.flow_id, name: response.data.name },
    });

    return response;

  } catch (error) {
    logUtil.error({
      logger,
      message: 'Failed to partially update flow',
      data: { flowId, error },
    });
    throw error;
  }
};

/**
 * Delete flow by ID via BFF
 */
export const deleteFlow = async (flowId: string): Promise<AxiosResponse<void>> => {
  const url = `/api/flows/${flowId}`;

  try {
    const response = await apiClient.delete<void>(url, { headers: BFF_HEADERS });

    logUtil.info({
      logger,
      message: 'Successfully deleted flow',
      data: { flowId },
    });

    return response;

  } catch (error) {
    logUtil.error({
      logger,
      message: 'Failed to delete flow',
      data: { flowId, error },
    });
    throw error;
  }
};

/**
 * Bulk delete flows via BFF
 */
export const bulkDeleteFlows = async (flowIds: string[]): Promise<AxiosResponse<{ deleted_count: number }>> => {
  const params = new URLSearchParams({ flow_ids: flowIds.join(',') });
  const url = `/api/flows?${params.toString()}`;

  try {
    const response = await apiClient.delete<{ deleted_count: number }>(url, { headers: BFF_HEADERS });

    logUtil.info({
      logger,
      message: 'Successfully bulk deleted flows',
      data: { count: response.data.deleted_count },
    });

    return response;

  } catch (error) {
    logUtil.error({
      logger,
      message: 'Failed to bulk delete flows',
      data: { flowIds, error },
    });
    throw error;
  }
};
