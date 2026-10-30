import type {
  FlowValidationResponse,
  ValidationAlertItem,
} from '@/services/api';

/**
 * Factory function to create a mock ValidationAlertItem with default values.
 *
 * @param partial Optional partial ValidationAlertItem properties to override defaults.
 * @returns Complete ValidationAlertItem object.
 */
export function createMockValidationAlertItem(
  partial?: Partial<ValidationAlertItem>
): ValidationAlertItem {
  return {
    code: null,
    message: null,
    message_code: null,
    node_id: null,
    node_name: null,
    operator: null,
    action_type: null,
    ...partial,
  };
}

/**
 * Factory function to create a mock FlowValidationResponse with default values.
 *
 * @param partial Optional partial FlowValidationResponse properties to override defaults.
 * @returns Complete FlowValidationResponse object.
 */
export function createMockValidationResponse(
  partial?: Partial<FlowValidationResponse>
): FlowValidationResponse {
  return {
    status: 'success',
    message: 'Flow validated successfully',
    errors: [],
    warnings: [],
    ...partial,
  };
}
