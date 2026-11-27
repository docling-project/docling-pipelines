/**
 * @file Save-button gating shared by the properties panel entry points.
 *
 * Combines the generic required-parameter check with operator-specific value
 * validators so `CommonPropertiesWrapper` (fires on every property change) and
 * `CommonPropertiesPanel` (fires on mount) cannot diverge.
 */

import { NodeOperator } from '@/constants/operators';
import { hasAnyRequiredParamMissing } from '@/utils/requiredParamValidation';
import type { OperatorFeature } from '@/types';
import { hasInvalidChunkSize } from './CustomPanels/Chunker/chunkSizeValidation';

type OperatorValueValidator = (propertyValues: Record<string, unknown>) => boolean;

/** Per-operator validators returning true when the current values are invalid. */
const OPERATOR_VALUE_VALIDATORS: Partial<Record<string, OperatorValueValidator>> = {
  [NodeOperator.CHUNKER]: hasInvalidChunkSize,
};

/**
 * True when Save must be disabled: a required param is missing, or the
 * operator-specific validator reports an invalid value.
 */
export function shouldDisableSave(
  operatorName: string,
  nodeAttributes: Record<string, OperatorFeature>,
  propertyValues: Record<string, unknown>
): boolean {
  if (hasAnyRequiredParamMissing(nodeAttributes, propertyValues)) { return true; }
  return OPERATOR_VALUE_VALIDATORS[operatorName]?.(propertyValues) ?? false;
}
