import type { Request, Response, Router } from 'express';
import { log4js } from '../../src/utils/logger';
import { handleProxyError, proxyRequest } from '../utils/proxy';
import { queryString, queryStringList } from '../utils/query';

const logger = log4js.getLogger('flow.controller');

/**
 * Create a new flow
 * BFF controller that proxies flow creation to Python FastAPI backend
 */
const createFlow = async (req: Request, res: Response): Promise<void> => {
  try {
    const response = await proxyRequest({ method: 'POST', path: '/api/v1/flows?is_elyra=true', body: req.body });

    res.status(response.status).json(response.data);
  } catch (err) {
    handleProxyError({ res, err, logger, fallbackMessage: 'Failed to create flow' });
  }
};

/**
 * Get flow by ID
 * BFF controller that proxies flow retrieval to Python FastAPI backend
 */
const getFlow = async (req: Request, res: Response): Promise<void> => {
  try {
    const { flowId } = req.params;

    const response = await proxyRequest({ method: 'GET', path: `/api/v1/flows/${flowId}` });

    res.json(response.data);
  } catch (err) {
    handleProxyError({ res, err, logger, fallbackMessage: 'Failed to fetch flow' });
  }
};

/**
 * List flows with pagination and filtering
 * BFF controller that proxies flow listing to Python FastAPI backend
 */
const getFlows = async (req: Request, res: Response): Promise<void> => {
  try {
    const { limit, offset, name, tags, is_hidden } = req.query;

    const params = new URLSearchParams({
      limit: queryString(limit) ?? '100',
      offset: queryString(offset) ?? '0',
      is_elyra: 'true',
    });

    const flowName = queryString(name);
    const flowTags = queryString(tags);
    const isHidden = queryString(is_hidden);
    if (flowName) params.append('name', flowName);
    if (flowTags) params.append('tags', flowTags);
    if (isHidden !== undefined) params.append('is_hidden', isHidden);

    const response = await proxyRequest({ method: 'GET', path: `/api/v1/flows?${params.toString()}` });

    res.json(response.data);
  } catch (err) {
    handleProxyError({ res, err, logger, fallbackMessage: 'Failed to list flows' });
  }
};

/**
 * Update flow (full replacement)
 * BFF controller that proxies flow update to Python FastAPI backend
 */
const updateFlow = async (req: Request, res: Response): Promise<void> => {
  try {
    const { flowId } = req.params;

    const response = await proxyRequest({ method: 'PUT', path: `/api/v1/flows/${flowId}?is_elyra=true`, body: req.body });

    res.json(response.data);
  } catch (err) {
    handleProxyError({ res, err, logger, fallbackMessage: 'Failed to update flow' });
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
const patchFlow = async (req: Request, res: Response): Promise<void> => {
  try {
    const { flowId } = req.params;
    const path = `/api/v1/flows/${flowId}?is_elyra=true`;

    let body = req.body;

    if (req.body.name) {
      const current = await proxyRequest({ method: 'GET', path });
      body = {
        ...req.body,
        definition: syncElyraDefinitionName(current.data.definition, req.body.name),
      };
    }

    const response = await proxyRequest({ method: 'PATCH', path, body });

    res.json(response.data);
  } catch (err) {
    handleProxyError({ res, err, logger, fallbackMessage: 'Failed to partially update flow' });
  }
};

/**
 * Delete flow by ID
 * BFF controller that proxies flow deletion to Python FastAPI backend
 */
const deleteFlow = async (req: Request, res: Response): Promise<void> => {
  try {
    const { flowId } = req.params;

    const response = await proxyRequest({ method: 'DELETE', path: `/api/v1/flows/${flowId}` });

    res.status(response.status).send();
  } catch (err) {
    handleProxyError({ res, err, logger, fallbackMessage: 'Failed to delete flow' });
  }
};

/**
 * Bulk delete flows
 * BFF controller that proxies bulk flow deletion to Python FastAPI backend
 */
const bulkDeleteFlows = async (req: Request, res: Response): Promise<void> => {
  try {
    const flowIds = queryString(req.query.flow_ids);

    if (!flowIds) {
      res.status(400).json({ error: 'flow_ids query parameter is required' });
      return;
    }

    const params = new URLSearchParams({ flow_ids: flowIds });

    const response = await proxyRequest({ method: 'DELETE', path: `/api/v1/flows?${params.toString()}` });

    res.json(response.data);
  } catch (err) {
    handleProxyError({ res, err, logger, fallbackMessage: 'Failed to bulk delete flows' });
  }
};

/**
 * List flows for a specific project
 * BFF controller that proxies to Python backend: GET /api/v1/projects/:projectId/flows
 */
const getFlowsByProject = async (req: Request, res: Response): Promise<void> => {
  try {
    const { projectId } = req.params;
    const { limit, offset, name, tags } = req.query;

    const params = new URLSearchParams({
      limit: queryString(limit) ?? '100',
      offset: queryString(offset) ?? '0',
      is_elyra: 'true',
    });

    const flowName = queryString(name);
    if (flowName) params.append('name', flowName);
    queryStringList(tags).forEach((tag) => params.append('tags', tag));

    const response = await proxyRequest({ method: 'GET', path: `/api/v1/projects/${projectId}/flows?${params.toString()}` });

    res.json(response.data);
  } catch (err) {
    handleProxyError({ res, err, logger, fallbackMessage: 'Failed to list flows for project' });
  }
};

/**
 * Export routes function that registers all flow endpoints
 */
export const routes = (router: Router): void => {
  router.post('/flows', createFlow);
  router.get('/flows/:flowId', getFlow);
  router.get('/flows', getFlows);
  router.get('/projects/:projectId/flows', getFlowsByProject);
  router.put('/flows/:flowId', updateFlow);
  router.patch('/flows/:flowId', patchFlow);
  router.delete('/flows/:flowId', deleteFlow);
  router.delete('/flows', bulkDeleteFlows);
};
