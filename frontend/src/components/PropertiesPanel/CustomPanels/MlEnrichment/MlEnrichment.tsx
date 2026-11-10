/**
 * @file MlEnrichment.tsx
 *
 * Configuration panel body for the `ml_enrichment` operator node.
 *
 * **Data flow**:
 * - `controller.getAppData().operatorMetadata` — backend attribute metadata (descriptions, defaults)
 * - `controller.getPropertyValue({ name })` — reads saved node parameter
 * - `controller.updatePropertyValue({ name }, value)` — writes node parameter on change
 */

import React from 'react';
import { getRequiredParamValidator } from '@/utils/requiredParamValidation';
import { RequiredParamTooltip } from '@/components/common';
import { TextInput } from '@carbon/react';
import { useIntl } from 'react-intl';
import type { OperatorFeature, OperatorMetadata } from '@/types';
import { NodeOperator } from '@/constants/operators';
import { ML_ENRICHMENT_ATTRIBUTE as ATTR } from './constants';
import { messages } from './MlEnrichment.messages';
import common from '../../CommonPropertiesPanel.module.scss';

interface MlEnrichmentPanelBodyProps {
  controller: any;
}

export function MlEnrichmentPanelBody({
  controller,
}: MlEnrichmentPanelBodyProps): React.JSX.Element {
  const intl = useIntl();
  // ── Read operator attribute metadata ──────────────────────────────────
  // eslint-disable-next-line @typescript-eslint/no-unsafe-call
  const operatorMetadata = (controller?.getAppData?.()?.operatorMetadata ?? {}) as Record<string, OperatorMetadata>;
  const nodeAttributes: Record<string, OperatorFeature> = operatorMetadata[NodeOperator.ML_ENRICHMENT]?.attributes ?? {};

  // ── Read current saved values, falling back to backend defaults ────────
  const outputColumnPrefix: string =
    // eslint-disable-next-line @typescript-eslint/no-unsafe-call
    (controller?.getPropertyValue?.({ name: ATTR.OUTPUT_COLUMN_PREFIX }) as string | undefined)
    ?? (nodeAttributes[ATTR.OUTPUT_COLUMN_PREFIX]?.default as string | undefined)
    ?? '';

  // ── Required param validation ─────────────────────────────────────────────
  const validate = getRequiredParamValidator(nodeAttributes);
  const outputColumnPrefixValidation = validate(ATTR.OUTPUT_COLUMN_PREFIX, outputColumnPrefix);

  return (
    <div className={common.commonPropertiesPanelBody}>

      {/* ── Output column prefix ─────────────────────────────────────── */}
      <div className={common.formField}>
        <div className={common.labelWithTooltip}>
          <RequiredParamTooltip
            paramId={ATTR.OUTPUT_COLUMN_PREFIX}
            nodeAttributes={nodeAttributes}
            definition={nodeAttributes[ATTR.OUTPUT_COLUMN_PREFIX]?.description ?? ''}
          >
            {intl.formatMessage(messages.outputColumnPrefix)}
          </RequiredParamTooltip>
        </div>
        <TextInput
          id="output_column_prefix"
          labelText={intl.formatMessage(messages.outputColumnPrefix)}
          hideLabel
          value={outputColumnPrefix}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
            // eslint-disable-next-line @typescript-eslint/no-unsafe-call
            controller?.updatePropertyValue?.({ name: ATTR.OUTPUT_COLUMN_PREFIX }, e.target.value);
          }}
          invalid={outputColumnPrefixValidation.isInvalid}
          invalidText={outputColumnPrefixValidation.errorMessage}
        />
      </div>

    </div>
  );
}
