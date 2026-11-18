/**
 * Validation Actions
 *
 * HTTP calls to BFF endpoints for flow validation.
 */

import { type AxiosResponse } from 'axios';
import { log4js, logUtil } from '@/utils/logger';
import { apiClient } from '../client';

const logger = log4js.getLogger('validation.actions');

const BFF_HEADERS = {
  'Accept': 'application/json',
  'X-Requested-With': 'XMLHttpRequest',
};

export type ValidationActionType = 'highlight' | 'open_properties' | 'none';

export interface ValidationAlertItem {
  code: string | null;
  message: string | null;
  message_code: string | null;
  node_id: string | null;
  node_name: string | null;
  operator: string | null;
  action_type?: ValidationActionType | null;
}

export interface FlowValidationResponse {
  status: string;
  message: string | null;
  errors: ValidationAlertItem[];
  warnings: ValidationAlertItem[];
}

/**
 * Validate a flow definition via BFF (Elyra format by default)
 *
 * Calls BFF endpoint: POST /api/validation/validate?is_elyra=true
 * BFF proxies to Python backend: POST /api/v1/validation/validate_flow?is_elyra=true
 *
 * The backend validate_flow endpoint (when is_elyra=true) expects:
 *   { "name": "<any string>", "definition": <raw Elyra PipelineFlowDef> }
 * matching the ElyraFlowCreateRequest DTO shape.
 */
export const validateFlow = async (
  flowDefinition: object,
  isElyra = true
): Promise<AxiosResponse<FlowValidationResponse>> => {
  const url = `/api/validation/validate?is_elyra=${isElyra}`;

  // Wrap the raw Elyra pipeline JSON in the ElyraFlowCreateRequest shape
  // that the backend validate_flow endpoint expects when is_elyra=true.
  const body = isElyra
    ? { name: 'validate', definition: flowDefinition }
    : flowDefinition;

  try {
    const response = await apiClient.post<FlowValidationResponse>(url, body, {
      headers: BFF_HEADERS,
    });

    logUtil.info({
      logger,
      message: 'Flow validation completed',
      data: {
        status: response.data.status,
        errors: response.data.errors.length,
        warnings: response.data.warnings.length,
      },
    });

    return response;
  } catch (error) {
    logUtil.error({ logger, message: 'Flow validation request failed', data: error });
    throw error;
  }
};
