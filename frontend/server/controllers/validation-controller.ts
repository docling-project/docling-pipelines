import type { Request, Response, Router } from 'express';
import { log4js } from '../../src/utils/logger';
import { handleProxyError, proxyRequest } from '../utils/proxy';
import { queryString } from '../utils/query';

const logger = log4js.getLogger('validation.controller');

/**
 * Validate a flow definition (without persisting it)
 * BFF controller that proxies flow validation to Python FastAPI backend
 */
const validateFlow = async (req: Request, res: Response): Promise<void> => {
  try {
    const { is_elyra = 'true' } = req.query;
    const response = await proxyRequest({
      method: 'POST',
      path: ['api', 'v1', 'validation', 'validate_flow'],
      query: { is_elyra: queryString(is_elyra) },
      body: req.body,
    });

    res.json(response.data);
  } catch (err) {
    await handleProxyError({ res, err, logger, fallbackMessage: 'Failed to validate flow' });
  }
};

/**
 * Export routes function that registers all validation endpoints
 */
export const routes = (router: Router): void => {
  router.post('/validation/validate', validateFlow);
};
