/**
 * @file ACL operator properties panel body.
 *
 * Renders the configuration UI for the `acl_operator` node.
 */

import React from 'react';
import { Toggle } from '@carbon/react';
import { useIntl } from 'react-intl';
import type { OperatorFeature, OperatorMetadata } from '@/types';
import { NodeOperator } from '@/constants/operators';
import { ACL_ATTR as ATTR } from './constants';
import { messages } from './ACL.messages';
import { JsonTextArea } from '@/components/common/JsonTextArea/JsonTextArea';
import { RequiredParamTooltip } from '@/components/common';
import { getRequiredParamValidator } from '@/utils/requiredParamValidation';
import common from '../../CommonPropertiesPanel.module.scss';

interface ACLPanelBodyProps {
  controller: any;
}

/* eslint-disable @typescript-eslint/no-unsafe-call, @typescript-eslint/no-unsafe-member-access */
export function ACLPanelBody({ controller }: ACLPanelBodyProps): React.JSX.Element {
  const intl = useIntl();

  // ── Operator attribute metadata ──
  const operatorMetadata = (controller?.getAppData?.()?.operatorMetadata ?? {}) as Record<string, OperatorMetadata>;
  const nodeAttributes: Record<string, OperatorFeature> = operatorMetadata[NodeOperator.ACL_OPERATOR]?.attributes ?? {};

  // ── Read current saved values, falling back to backend defaults ──
  const providerConfigStored =
    (controller?.getPropertyValue?.({ name: ATTR.PROVIDER_CONFIG }) as Record<string, unknown> | null | undefined)
    ?? null;

  const failOnError: boolean =
    (controller?.getPropertyValue?.({ name: ATTR.FAIL_ON_ERROR }) as boolean | undefined)
    ?? (nodeAttributes[ATTR.FAIL_ON_ERROR]?.default as boolean | undefined)
    ?? true;

  // ── Required param validator ──────────────────────────────────────────────
  const validate = getRequiredParamValidator(nodeAttributes);
  const providerConfigValidation = validate(ATTR.PROVIDER_CONFIG, providerConfigStored);

  return (
    <div className={common.commonPropertiesPanelBody}>

      {/* ── Provider configuration ───────────────────────────────────── */}
      <div className={common.formField}>
        <div className={common.labelWithTooltip}>
          <RequiredParamTooltip
            paramId={ATTR.PROVIDER_CONFIG}
            nodeAttributes={nodeAttributes}
            definition={nodeAttributes[ATTR.PROVIDER_CONFIG]?.description ?? ''}
          >
            {intl.formatMessage(messages.providerConfig)}
          </RequiredParamTooltip>
        </div>
        <JsonTextArea
          id="provider_config"
          labelText={intl.formatMessage(messages.providerConfig)}
          storedValue={providerConfigStored}
          placeholder='{"resolve_inheritance": true, "expand_groups": true}'
          invalid={providerConfigValidation.isInvalid}
          invalidText={providerConfigValidation.errorMessage}
          onChange={(value) => {
            controller?.updatePropertyValue?.({ name: ATTR.PROVIDER_CONFIG }, value);
          }}
        />
      </div>

      {/* ── Fail on error ────────────────────────────────────────────── */}
      <div className={common.formField}>
        <div className={common.labelWithTooltip}>
          <RequiredParamTooltip
            paramId={ATTR.FAIL_ON_ERROR}
            nodeAttributes={nodeAttributes}
            definition={nodeAttributes[ATTR.FAIL_ON_ERROR]?.description ?? ''}
          >
            {intl.formatMessage(messages.failOnError)}
          </RequiredParamTooltip>
        </div>
        <Toggle
          id="fail_on_error"
          labelText={intl.formatMessage(messages.failOnError)}
          hideLabel
          labelA={intl.formatMessage(messages.off)}
          labelB={intl.formatMessage(messages.on)}
          toggled={failOnError}
          onToggle={(checked: boolean) => {
            controller?.updatePropertyValue?.({ name: ATTR.FAIL_ON_ERROR }, checked);
          }}
        />
      </div>
    </div>
  );
}
