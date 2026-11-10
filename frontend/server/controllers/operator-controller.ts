import axios from 'axios';
import type { Request, Response, Router } from 'express';
import { log4js, logUtil } from '../../src/utils/logger';
import { BODY_HEADERS, NO_BODY_HEADERS, buildForwardHeaders } from './http-headers';

const logger = log4js.getLogger('operator.controller');

/**
 * Fetch operator metadata from backend API
 * This is the BFF controller that proxies requests to the Python FastAPI backend
 */
const fetchOperatorMetadata = async (req: Request, res: Response) => {
  try {
    const requestUrl = `${process.env.BACKEND_API_URL}/api/v1/operators/metadata`;
    logUtil.debug({ logger, message: 'Request URL', data: requestUrl });

    const response = await axios.get(requestUrl, { headers: buildForwardHeaders(req, NO_BODY_HEADERS) });

    res.json(response.data);

  } catch (error) {
    logUtil.error({ logger, message: 'Error fetching operator metadata', data: error.message });

    const status = error.response?.status ?? 500;
    const errorData = error.response?.data ?? { error: 'Failed to fetch operator metadata' };

    res.status(status).json(errorData);
  }
};

/**
 * Enrich flow pipeline with per-node feature metadata.
 * Proxies to POST /api/v1/validation/enrich_flow_features on the Python backend.
 */
const enrichFlowFeatures = async (req: Request, res: Response) => {
  try {
    const requestUrl = `${process.env.BACKEND_API_URL}/api/v1/validation/enrich_flow_features`;
    logUtil.debug({ logger, message: 'Enriching flow features', data: requestUrl });

    const response = await axios.post(requestUrl, req.body, { headers: buildForwardHeaders(req, BODY_HEADERS) });

    res.json(response.data);

  } catch (error) {
    logUtil.error({ logger, message: 'Error enriching flow features', data: error.message });

    const status = error.response?.status ?? 500;
    const errorData = error.response?.data ?? { error: 'Failed to enrich flow features' };

    res.status(status).json(errorData);
  }
};

const ALLOWED_PROVIDERS = ['ollama', 'watsonx'] as const;
type AllowedProvider = typeof ALLOWED_PROVIDERS[number];

/**
 * Fetch available models for a given LLM/embedding provider.
 * Proxies to GET /api/v1/providers/{provider}/models on the Python backend.
 * Supported providers: ollama, watsonx, litellm.
 */
const fetchProviderModels = async (req: Request, res: Response) => {
  const { provider } = req.params;
  const { api_base } = req.query as { api_base?: string };

  if (!ALLOWED_PROVIDERS.includes(provider as AllowedProvider)) {
    logUtil.warn({ logger, message: 'Unsupported provider requested', data: { provider } });
    return res.status(400).json({ error: `Unsupported provider: ${provider}. Allowed providers: ${ALLOWED_PROVIDERS.join(', ')}` });
  }

  try {
    const params = new URLSearchParams();
    if (api_base) params.append('api_base', api_base);

    const query = params.toString() ? `?${params.toString()}` : '';
    const requestUrl = `${process.env.BACKEND_API_URL}/api/v1/providers/${provider}/models${query}`;
    logUtil.debug({ logger, message: 'Fetching provider models', data: { provider, url: requestUrl } });

    const response = await axios.get(requestUrl, {
      headers: buildForwardHeaders(req, NO_BODY_HEADERS),
    });

    res.json(response.data);
  } catch (error) {
    logUtil.error({ logger, message: 'Error fetching provider models', data: error.message });

    const status = error.response?.status ?? 500;
    const errorData = error.response?.data ?? { error: `Failed to fetch models for provider: ${provider}` };

    res.status(status).json(errorData);
  }
};

/**
 * Export routes function that registers all operator endpoints
 */
export const routes = (router: Router) => {
  router.get('/fetchOperatorMetadata', fetchOperatorMetadata);
  router.post('/enrichFlowFeatures', enrichFlowFeatures);
  router.get('/providers/:provider/models', fetchProviderModels);
};
