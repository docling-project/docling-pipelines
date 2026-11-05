import type { Request, Response, Router } from 'express';
import { log4js, logUtil } from '../../src/utils/logger';
import { handleProxyError, proxyRequest } from '../utils/proxy';

const logger = log4js.getLogger('operator.controller');

/**
 * Fetch operator metadata from backend API
 * This is the BFF controller that proxies requests to the Python FastAPI backend
 */
const fetchOperatorMetadata = async (_req: Request, res: Response): Promise<void> => {
  try {
    const response = await proxyRequest({ method: 'GET', path: '/api/v1/operators/metadata' });

    res.json(response.data);
  } catch (err) {
    handleProxyError({ res, err, logger, fallbackMessage: 'Failed to fetch operator metadata' });
  }
};

/**
 * Enrich flow pipeline with per-node feature metadata.
 * Proxies to POST /api/v1/validation/enrich_flow_features on the Python backend.
 */
const enrichFlowFeatures = async (req: Request, res: Response): Promise<void> => {
  try {
    const response = await proxyRequest({
      method: 'POST',
      path: '/api/v1/validation/enrich_flow_features',
      body: req.body,
    });

    res.json(response.data);
  } catch (err) {
    handleProxyError({ res, err, logger, fallbackMessage: 'Failed to enrich flow features' });
  }
};

const ALLOWED_PROVIDERS = ['ollama', 'watsonx'] as const;
type AllowedProvider = typeof ALLOWED_PROVIDERS[number];

/**
 * Fetch available models for a given LLM/embedding provider.
 * Proxies to GET /api/v1/providers/{provider}/models on the Python backend.
 * Supported providers: ollama, watsonx.
 */
const fetchProviderModels = async (req: Request, res: Response): Promise<void> => {
  const { provider = '' } = req.params;
  const { api_base } = req.query as { api_base?: string };

  if (!ALLOWED_PROVIDERS.includes(provider as AllowedProvider)) {
    logUtil.warn({ logger, message: 'Unsupported provider requested', data: { provider } });
    res.status(400).json({ error: `Unsupported provider: ${provider}. Allowed providers: ${ALLOWED_PROVIDERS.join(', ')}` });
    return;
  }

  try {
    const params = new URLSearchParams();
    if (api_base) params.append('api_base', api_base);

    const query = params.toString() ? `?${params.toString()}` : '';
    const response = await proxyRequest({ method: 'GET', path: `/api/v1/providers/${provider}/models${query}` });

    res.json(response.data);
  } catch (err) {
    handleProxyError({ res, err, logger, fallbackMessage: `Failed to fetch models for provider: ${provider}` });
  }
};

/**
 * Export routes function that registers all operator endpoints
 */
export const routes = (router: Router): void => {
  router.get('/fetchOperatorMetadata', fetchOperatorMetadata);
  router.post('/enrichFlowFeatures', enrichFlowFeatures);
  router.get('/providers/:provider/models', fetchProviderModels);
};
