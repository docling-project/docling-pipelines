import axios from 'axios';
import type { Request, Response, Router } from 'express';
import { log4js, logUtil } from '../../src/utils/logger';
import { BODY_HEADERS, NO_BODY_HEADERS, buildForwardHeaders } from './http-headers';

const logger = log4js.getLogger('flow.controller');

/**
 * Create a new flow
 * BFF controller that proxies flow creation to Python FastAPI backend
 */
const createFlow = async (req: Request, res: Response) => {
  try {
    const requestUrl = `${process.env.BACKEND_API_URL}/api/v1/flows?is_elyra=true`;

    const response = await axios.post(requestUrl, req.body, { headers: buildForwardHeaders(req, BODY_HEADERS) });

    res.status(response.status).json(response.data);

  } catch (error) {
    logUtil.error({ logger, message: 'Error creating flow', data: error.message });

    const status = error.response?.status ?? 500;
    const errorData = error.response?.data ?? { error: 'Failed to create flow' };

    res.status(status).json(errorData);
  }
};

/**
 * Get flow by ID
 * BFF controller that proxies flow retrieval to Python FastAPI backend
 */
const getFlow = async (req: Request, res: Response) => {
  try {
    const { flowId } = req.params;
    const requestUrl = `${process.env.BACKEND_API_URL}/api/v1/flows/${flowId}`;

    const response = await axios.get(requestUrl, { headers: buildForwardHeaders(req, NO_BODY_HEADERS) });

    res.json(response.data);

  } catch (error) {
    logUtil.error({ logger, message: 'Error fetching flow', data: error.message });

    const status = error.response?.status ?? 500;
    const errorData = error.response?.data ?? { error: 'Failed to fetch flow' };

    res.status(status).json(errorData);
  }
};

/**
 * List flows with pagination and filtering
 * BFF controller that proxies flow listing to Python FastAPI backend
 */
const getFlows = async (req: Request, res: Response) => {
  try {
    const { limit = 100, offset = 0, name, tags, is_hidden } = req.query;

    const params = new URLSearchParams({
      limit: limit.toString(),
      offset: offset.toString(),
      is_elyra: 'true',
    });

    if (name) params.append('name', name);
    if (tags) params.append('tags', tags);
    if (is_hidden !== undefined) params.append('is_hidden', is_hidden);

    const requestUrl = `${process.env.BACKEND_API_URL}/api/v1/flows?${params.toString()}`;
    logUtil.debug({ logger, message: 'Request URL', data: requestUrl });

    const response = await axios.get(requestUrl, { headers: buildForwardHeaders(req, NO_BODY_HEADERS) });

    res.json(response.data);

  } catch (error) {
    logUtil.error({ logger, message: 'Error listing flows', data: error.message });

    const status = error.response?.status ?? 500;
    const errorData = error.response?.data ?? { error: 'Failed to list flows' };

    res.status(status).json(errorData);
  }
};

/**
 * Update flow (full replacement)
 * BFF controller that proxies flow update to Python FastAPI backend
 */
const updateFlow = async (req: Request, res: Response) => {
  try {
    const { flowId } = req.params;
    const requestUrl = `${process.env.BACKEND_API_URL}/api/v1/flows/${flowId}?is_elyra=true`;

    const response = await axios.put(requestUrl, req.body, { headers: buildForwardHeaders(req, BODY_HEADERS) });

    res.json(response.data);

  } catch (error) {
    logUtil.error({ logger, message: 'Error updating flow', data: error.message });

    const status = error.response?.status ?? 500;
    const errorData = error.response?.data ?? { error: 'Failed to update flow' };

    res.status(status).json(errorData);
  }
};

/**
 * Sync app_data.ds_flow.name inside an Elyra pipeline definition.
 * Returns a new definition object — the original is not mutated.
 */
const syncElyraDefinitionName = (definition: Record<string, unknown>, newName: string): Record<string, unknown> => {
  const pipelines = definition['pipelines'];
  if (!Array.isArray(pipelines) || pipelines.length === 0) return definition;

  const pipeline = JSON.parse(JSON.stringify(pipelines[0])) as Record<string, unknown>;
  const appData = pipeline['app_data'];
  if (appData && typeof appData === 'object') {
    const dsFlow = (appData as Record<string, unknown>)['ds_flow'];
    if (dsFlow && typeof dsFlow === 'object') {
      (dsFlow as Record<string, unknown>)['name'] = newName;
    }
  }

  return { ...definition, pipelines: [pipeline, ...pipelines.slice(1)] };
};

/**
 * Patch flow
 * BFF controller that proxies partial flow update to Python FastAPI backend.
 * When name is present in the patch body, fetches the current definition and
 * syncs app_data.ds_flow.name before forwarding — that nested field is Elyra
 * UI state the backend does not manage. Skipped when name is not being patched
 * to avoid setting ds_flow.name to undefined.
 */
const patchFlow = async (req: Request, res: Response) => {
  try {
    const { flowId } = req.params;
    const requestUrl = `${process.env.BACKEND_API_URL}/api/v1/flows/${flowId}?is_elyra=true`;

    let body = req.body;

    if (req.body.name) {
      const current = await axios.get(requestUrl, { headers: buildForwardHeaders(req, NO_BODY_HEADERS) });
      body = {
        ...req.body,
        definition: syncElyraDefinitionName(current.data.definition, req.body.name),
      };
    }

    const response = await axios.patch(requestUrl, body, { headers: buildForwardHeaders(req, BODY_HEADERS) });

    res.json(response.data);

  } catch (error) {
    logUtil.error({ logger, message: 'Error partially updating flow', data: error.message });

    const status = error.response?.status ?? 500;
    const errorData = error.response?.data ?? { error: 'Failed to partially update flow' };

    res.status(status).json(errorData);
  }
};

/**
 * Delete flow by ID
 * BFF controller that proxies flow deletion to Python FastAPI backend
 */
const deleteFlow = async (req: Request, res: Response) => {
  try {
    const { flowId } = req.params;
    const requestUrl = `${process.env.BACKEND_API_URL}/api/v1/flows/${flowId}`;

    const response = await axios.delete(requestUrl, { headers: buildForwardHeaders(req, NO_BODY_HEADERS) });

    res.status(response.status).send();

  } catch (error) {
    logUtil.error({ logger, message: 'Error deleting flow', data: error.message });

    const status = error.response?.status ?? 500;
    const errorData = error.response?.data ?? { error: 'Failed to delete flow' };

    res.status(status).json(errorData);
  }
};

/**
 * Bulk delete flows
 * BFF controller that proxies bulk flow deletion to Python FastAPI backend
 */
const bulkDeleteFlows = async (req: Request, res: Response) => {
  try {
    const { flow_ids } = req.query;

    if (!flow_ids) {
      return res.status(400).json({ error: 'flow_ids query parameter is required' });
    }

    const params = new URLSearchParams({ flow_ids });
    const requestUrl = `${process.env.BACKEND_API_URL}/api/v1/flows?${params.toString()}`;

    const response = await axios.delete(requestUrl, { headers: buildForwardHeaders(req, NO_BODY_HEADERS) });

    res.json(response.data);

  } catch (error) {
    logUtil.error({ logger, message: 'Error bulk deleting flows', data: error.message });

    const status = error.response?.status ?? 500;
    const errorData = error.response?.data ?? { error: 'Failed to bulk delete flows' };

    res.status(status).json(errorData);
  }
};

/**
 * List flows for a specific project
 * BFF controller that proxies to Python backend: GET /api/v1/projects/:projectId/flows
 */
const getFlowsByProject = async (req: Request, res: Response) => {
  try {
    const { projectId } = req.params;
    const { limit = 100, offset = 0, name, tags } = req.query;

    const params = new URLSearchParams({
      limit: limit.toString(),
      offset: offset.toString(),
      is_elyra: 'true',
    });

    if (name) params.append('name', name as string);
    if (tags) {
      const tagList = Array.isArray(tags) ? tags : [tags];
      tagList.forEach((tag) => params.append('tags', tag as string));
    }

    const requestUrl = `${process.env.BACKEND_API_URL}/api/v1/projects/${projectId}/flows?${params.toString()}`;
    logUtil.debug({ logger, message: 'Request URL', data: requestUrl });

    const response = await axios.get(requestUrl, { headers: buildForwardHeaders(req, NO_BODY_HEADERS) });

    res.json(response.data);

  } catch (error) {
    logUtil.error({ logger, message: 'Error listing flows for project', data: error.message });

    const status = error.response?.status ?? 500;
    const errorData = error.response?.data ?? { error: 'Failed to list flows for project' };

    res.status(status).json(errorData);
  }
};

/**
 * Export routes function that registers all flow endpoints
 */
export const routes = (router: Router) => {
  router.post('/flows', createFlow);
  router.get('/flows/:flowId', getFlow);
  router.get('/flows', getFlows);
  router.get('/projects/:projectId/flows', getFlowsByProject);
  router.put('/flows/:flowId', updateFlow);
  router.patch('/flows/:flowId', patchFlow);
  router.delete('/flows/:flowId', deleteFlow);
  router.delete('/flows', bulkDeleteFlows);
};
