import axios from 'axios';
import type { Request, Response, Router } from 'express';
import { log4js, logUtil } from '../../src/utils/logger';
import { BODY_HEADERS, buildForwardHeaders } from './http-headers';

const logger = log4js.getLogger('validation.controller');

/**
 * Validate a flow definition (without persisting it)
 * BFF controller that proxies flow validation to Python FastAPI backend
 */
const validateFlow = async (req: Request, res: Response) => {
  try {
    const { is_elyra = true } = req.query;
    const requestUrl = `${process.env.BACKEND_API_URL}/api/v1/validation/validate_flow?is_elyra=${is_elyra}`;
    logUtil.debug({ logger, message: 'Request URL', data: requestUrl });

    const response = await axios.post(requestUrl, req.body, { headers: buildForwardHeaders(req, BODY_HEADERS) });

    res.json(response.data);

  } catch (error) {
    logUtil.error({ logger, message: 'Error validating flow', data: error.message });

    const status = error.response?.status ?? 500;
    const errorData = error.response?.data ?? { error: 'Failed to validate flow' };

    res.status(status).json(errorData);
  }
};

/**
 * Export routes function that registers all validation endpoints
 */
export const routes = (router: Router) => {
  router.post('/validation/validate', validateFlow);
};
