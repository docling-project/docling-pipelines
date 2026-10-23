/**
 * @file Noop properties panel body.
 *
 * Renders the configuration UI for the `noop` operator node.
 *
 *
 * **Data flow**:
 * - Field value is read from `controller.getPropertyValue()` (saved node params),
 *   falling back to the operator metadata default when available, then to the
 *   frontend constant default.
 * - Changes are written back immediately via `controller.updatePropertyValue()`.
 */

import React from 'react';
import { getRequiredParamValidator } from '@/utils/requiredParamValidation';
import { RequiredParamTooltip } from '@/components/common';
import { NumberInput } from '@carbon/react';
import { useIntl } from 'react-intl';
import type { OperatorFeature, OperatorMetadata } from '@/types';
import { NodeOperator } from '@/constants/operators';
import { NOOP_ATTRIBUTE as ATTR, NOOP_DEFAULTS } from './constants';
import { messages } from './Noop.messages';
import common from '../../CommonPropertiesPanel.module.scss';

interface NoopPanelBodyProps {
  controller: any;
}

export function NoopPanelBody({ controller }: NoopPanelBodyProps): React.JSX.Element {
  const intl = useIntl();
  // ── Read operator attribute metadata from Redux (passed in via Canvas.tsx) ──
  // eslint-disable-next-line @typescript-eslint/no-unsafe-call
  const operatorMetadata = (controller?.getAppData?.()?.operatorMetadata ?? {}) as Record<string, OperatorMetadata>;
  const nodeAttributes: Record<string, OperatorFeature> = operatorMetadata[NodeOperator.NOOP]?.attributes ?? {};

  // ── Read current saved value, falling back to backend default then frontend default ──
  const sleepSec: number =
    // eslint-disable-next-line @typescript-eslint/no-unsafe-call
    (controller?.getPropertyValue?.({ name: ATTR.SLEEP_SEC }) as number | undefined) ??
    (nodeAttributes[ATTR.SLEEP_SEC]?.default as number | undefined) ??
    NOOP_DEFAULTS.SLEEP_SEC;

  // ── Required param validation ─────────────────────────────────────────────
  const validate = getRequiredParamValidator(nodeAttributes);
  const sleepSecValidation = validate(ATTR.SLEEP_SEC, sleepSec);

  return (
    <div className={common.commonPropertiesPanelBody}>

      {/* ── Sleep duration ────────────────────────────────────────────── */}
      <div className={common.formField}>
        <div className={common.labelWithTooltip}>
          <RequiredParamTooltip
            paramId={ATTR.SLEEP_SEC}
            nodeAttributes={nodeAttributes}
            definition={
              (nodeAttributes[ATTR.SLEEP_SEC]?.description as string | undefined) ??
              intl.formatMessage(messages.sleepSecDescription)
            }
          >
            {intl.formatMessage(messages.sleepSec)}
          </RequiredParamTooltip>
        </div>
        <NumberInput
          id="sleep_sec"
          label={intl.formatMessage(messages.sleepSec)}
          hideLabel
          value={sleepSec}
          min={0}
          step={1}
          onChange={(_e: unknown, { value }: { value: number | string }) => {
            const parsedNumInput = Number(value);
            if (!Number.isNaN(parsedNumInput)) {
              // eslint-disable-next-line @typescript-eslint/no-unsafe-call
              controller?.updatePropertyValue?.({ name: ATTR.SLEEP_SEC }, parsedNumInput);
            }
          }}
          invalid={sleepSecValidation.isInvalid}
          invalidText={sleepSecValidation.errorMessage}
        />
      </div>

    </div>
  );
}
