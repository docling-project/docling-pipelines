import type { Request, Response, Router } from 'express';
import { log4js } from '../../src/utils/logger';
import { handleProxyError, proxyRequest } from '../utils/proxy';
import { queryString, queryStringList } from '../utils/query';

const logger = log4js.getLogger('projects.controller');

/**
 * Create a new project
 * BFF controller that proxies project creation to Python FastAPI backend
 */
const createProject = async (req: Request, res: Response): Promise<void> => {
  try {
    const response = await proxyRequest({ method: 'POST', path: '/api/v1/projects', body: req.body });

    res.status(response.status).json(response.data);
  } catch (err) {
    handleProxyError({ res, err, logger, fallbackMessage: 'Failed to create project' });
  }
};

/**
 * List projects with pagination and filtering
 * BFF controller that proxies project listing to Python FastAPI backend
 */
const getProjects = async (req: Request, res: Response): Promise<void> => {
  try {
    const { limit, offset, name, tags } = req.query;

    const params = new URLSearchParams({
      limit: queryString(limit) ?? '100',
      offset: queryString(offset) ?? '0',
    });

    const projectName = queryString(name);
    if (projectName) params.append('name', projectName);
    queryStringList(tags).forEach((tag) => params.append('tags', tag));

    const response = await proxyRequest({ method: 'GET', path: `/api/v1/projects?${params.toString()}` });

    res.json(response.data);
  } catch (err) {
    handleProxyError({ res, err, logger, fallbackMessage: 'Failed to list projects' });
  }
};

/**
 * Get project by ID
 * BFF controller that proxies project retrieval to Python FastAPI backend
 */
const getProject = async (req: Request, res: Response): Promise<void> => {
  try {
    const { projectId } = req.params;

    const response = await proxyRequest({ method: 'GET', path: `/api/v1/projects/${projectId}` });

    res.json(response.data);
  } catch (err) {
    handleProxyError({ res, err, logger, fallbackMessage: 'Failed to fetch project' });
  }
};

/**
 * Replace project (full update)
 * BFF controller that proxies full project replacement to Python FastAPI backend
 */
const replaceProject = async (req: Request, res: Response): Promise<void> => {
  try {
    const { projectId } = req.params;

    const response = await proxyRequest({ method: 'PUT', path: `/api/v1/projects/${projectId}`, body: req.body });

    res.json(response.data);
  } catch (err) {
    handleProxyError({ res, err, logger, fallbackMessage: 'Failed to replace project' });
  }
};

/**
 * Patch project (partial update)
 * BFF controller that proxies partial project update to Python FastAPI backend
 */
const patchProject = async (req: Request, res: Response): Promise<void> => {
  try {
    const { projectId } = req.params;

    const response = await proxyRequest({ method: 'PATCH', path: `/api/v1/projects/${projectId}`, body: req.body });

    res.json(response.data);
  } catch (err) {
    handleProxyError({ res, err, logger, fallbackMessage: 'Failed to partially update project' });
  }
};

/**
 * Delete project by ID
 * BFF controller that proxies project deletion to Python FastAPI backend
 */
const deleteProject = async (req: Request, res: Response): Promise<void> => {
  try {
    const { projectId } = req.params;

    const response = await proxyRequest({ method: 'DELETE', path: `/api/v1/projects/${projectId}` });

    res.status(response.status).send();
  } catch (err) {
    handleProxyError({ res, err, logger, fallbackMessage: 'Failed to delete project' });
  }
};

/**
 * Export routes function that registers all project endpoints
 */
export const routes = (router: Router): void => {
  router.post('/projects', createProject);
  router.get('/projects', getProjects);
  router.get('/projects/:projectId', getProject);
  router.put('/projects/:projectId', replaceProject);
  router.patch('/projects/:projectId', patchProject);
  router.delete('/projects/:projectId', deleteProject);
};
