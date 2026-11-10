import axios from 'axios';
import type { Request, Response, Router } from 'express';
import { log4js, logUtil } from '../../src/utils/logger';
import { BODY_HEADERS, NO_BODY_HEADERS, buildForwardHeaders } from './http-headers';

const logger = log4js.getLogger('projects.controller');

/**
 * Create a new project
 * BFF controller that proxies project creation to Python FastAPI backend
 */
const createProject = async (req: Request, res: Response) => {
  try {
    const requestUrl = `${process.env.BACKEND_API_URL}/api/v1/projects`;

    const response = await axios.post(requestUrl, req.body, { headers: buildForwardHeaders(req, BODY_HEADERS) });

    res.status(response.status).json(response.data);

  } catch (error) {
    logUtil.error({ logger, message: 'Error creating project', data: error.message });

    const status = error.response?.status ?? 500;
    const errorData = error.response?.data ?? { error: 'Failed to create project' };

    res.status(status).json(errorData);
  }
};

/**
 * List projects with pagination and filtering
 * BFF controller that proxies project listing to Python FastAPI backend
 */
const getProjects = async (req: Request, res: Response) => {
  try {
    const { limit = 100, offset = 0, name, tags } = req.query;

    const params = new URLSearchParams({
      limit: limit.toString(),
      offset: offset.toString(),
    });

    if (name) params.append('name', name as string);
    if (tags) {
      const tagList = Array.isArray(tags) ? tags : [tags];
      tagList.forEach((tag) => params.append('tags', tag as string));
    }

    const requestUrl = `${process.env.BACKEND_API_URL}/api/v1/projects?${params.toString()}`;
    logUtil.debug({ logger, message: 'Request URL', data: requestUrl });

    const response = await axios.get(requestUrl, { headers: buildForwardHeaders(req, NO_BODY_HEADERS) });

    res.json(response.data);

  } catch (error) {
    logUtil.error({ logger, message: 'Error listing projects', data: error.message });

    const status = error.response?.status ?? 500;
    const errorData = error.response?.data ?? { error: 'Failed to list projects' };

    res.status(status).json(errorData);
  }
};

/**
 * Get project by ID
 * BFF controller that proxies project retrieval to Python FastAPI backend
 */
const getProject = async (req: Request, res: Response) => {
  try {
    const { projectId } = req.params;
    const requestUrl = `${process.env.BACKEND_API_URL}/api/v1/projects/${projectId}`;

    const response = await axios.get(requestUrl, { headers: buildForwardHeaders(req, NO_BODY_HEADERS) });

    res.json(response.data);

  } catch (error) {
    logUtil.error({ logger, message: 'Error fetching project', data: error.message });

    const status = error.response?.status ?? 500;
    const errorData = error.response?.data ?? { error: 'Failed to fetch project' };

    res.status(status).json(errorData);
  }
};

/**
 * Replace project (full update)
 * BFF controller that proxies full project replacement to Python FastAPI backend
 */
const replaceProject = async (req: Request, res: Response) => {
  try {
    const { projectId } = req.params;
    const requestUrl = `${process.env.BACKEND_API_URL}/api/v1/projects/${projectId}`;

    const response = await axios.put(requestUrl, req.body, { headers: buildForwardHeaders(req, BODY_HEADERS) });

    res.json(response.data);

  } catch (error) {
    logUtil.error({ logger, message: 'Error replacing project', data: error.message });

    const status = error.response?.status ?? 500;
    const errorData = error.response?.data ?? { error: 'Failed to replace project' };

    res.status(status).json(errorData);
  }
};

/**
 * Patch project (partial update)
 * BFF controller that proxies partial project update to Python FastAPI backend
 */
const patchProject = async (req: Request, res: Response) => {
  try {
    const { projectId } = req.params;
    const requestUrl = `${process.env.BACKEND_API_URL}/api/v1/projects/${projectId}`;

    const response = await axios.patch(requestUrl, req.body, { headers: buildForwardHeaders(req, BODY_HEADERS) });

    res.json(response.data);

  } catch (error) {
    logUtil.error({ logger, message: 'Error partially updating project', data: error.message });

    const status = error.response?.status ?? 500;
    const errorData = error.response?.data ?? { error: 'Failed to partially update project' };

    res.status(status).json(errorData);
  }
};

/**
 * Delete project by ID
 * BFF controller that proxies project deletion to Python FastAPI backend
 */
const deleteProject = async (req: Request, res: Response) => {
  try {
    const { projectId } = req.params;
    const requestUrl = `${process.env.BACKEND_API_URL}/api/v1/projects/${projectId}`;

    const response = await axios.delete(requestUrl, { headers: buildForwardHeaders(req, NO_BODY_HEADERS) });

    res.status(response.status).send();

  } catch (error) {
    logUtil.error({ logger, message: 'Error deleting project', data: error.message });

    const status = error.response?.status ?? 500;
    const errorData = error.response?.data ?? { error: 'Failed to delete project' };

    res.status(status).json(errorData);
  }
};

/**
 * Export routes function that registers all project endpoints
 */
export const routes = (router: Router) => {
  router.post('/projects', createProject);
  router.get('/projects', getProjects);
  router.get('/projects/:projectId', getProject);
  router.put('/projects/:projectId', replaceProject);
  router.patch('/projects/:projectId', patchProject);
  router.delete('/projects/:projectId', deleteProject);
};
