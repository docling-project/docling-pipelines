import axios from 'axios';
import type { Request, Response, Router } from 'express';
import { log4js, logUtil } from '../../src/utils/logger';
import { NO_BODY_HEADERS, buildForwardHeaders } from './http-headers';

const logger = log4js.getLogger('document-class.controller');

/**
 * Fetch document classes from backend API
 * BFF controller that proxies requests to the Python FastAPI backend
 */
const fetchDocumentClasses = async (req: Request, res: Response) => {
  try {
    const requestUrl = `${process.env.BACKEND_API_URL}/api/v1/document_classes`;
    logUtil.debug({ logger, message: 'Request URL', data: requestUrl });

    const response = await axios.get(requestUrl, {
      headers: buildForwardHeaders(req, NO_BODY_HEADERS),
    });

    res.json(response.data);

  } catch (error) {
    logUtil.error({ logger, message: 'Error fetching document classes', data: error.message });

    const status = error.response?.status ?? 500;
    const errorData = error.response?.data ?? { error: 'Failed to fetch document classes' };

    res.status(status).json(errorData);
  }
};

/**
 * Export routes function that registers all document class endpoints
 */
export const routes = (router: Router) => {
  router.get('/documentClasses', fetchDocumentClasses);
};
