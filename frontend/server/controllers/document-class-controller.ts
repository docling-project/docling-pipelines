import type { Request, Response, Router } from 'express';
import { log4js } from '../../src/utils/logger';
import { handleProxyError, proxyRequest } from '../utils/proxy';

const logger = log4js.getLogger('document-class.controller');

/**
 * Fetch document classes from backend API
 * BFF controller that proxies requests to the Python FastAPI backend
 */
const fetchDocumentClasses = async (_req: Request, res: Response): Promise<void> => {
  try {
    const response = await proxyRequest({ method: 'GET', path: '/api/v1/document_classes' });

    res.json(response.data);
  } catch (err) {
    handleProxyError({ res, err, logger, fallbackMessage: 'Failed to fetch document classes' });
  }
};

/**
 * Export routes function that registers all document class endpoints
 */
export const routes = (router: Router): void => {
  router.get('/documentClasses', fetchDocumentClasses);
};
