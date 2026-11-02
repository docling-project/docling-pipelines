/**
 * @file Redaction operator configuration panel body.
 *
 * Renders the configuration UI for the `redaction` operator node.
 *
 * Parameters (from RedactionOperator.get_metadata()["attributes"]):
 * - `redaction_regex`              — required; regex pattern or plain word to redact
 * - `redaction_masking_character`  — optional; single character used to mask matches (default "*")
 *
 * UI conventions:
 * - `DefinitionTooltip` with `openOnHover` → description on hover
 * - `hideLabel` on Carbon inputs → no duplicate label text
 * - `.formField` wrapper → consistent vertical spacing
 * - Attribute metadata read from `controller.getAppData().operatorMetadata`
 */

import React from 'react';
import { getRequiredParamValidator } from '@/utils/requiredParamValidation';
import { RequiredParamTooltip } from '@/components/common';
import { TextInput } from '@carbon/react';
import { useIntl } from 'react-intl';
import type { OperatorFeature, OperatorMetadata } from '@/types';
import { NodeOperator } from '@/constants/operators';
import { REDACTION_ATTRIBUTE as ATTR } from './constants';
import { messages } from './Redaction.messages';

const REDACTION_REGEX_EXAMPLE = '\\b\\d{3}-\\d{2}-\\d{4}\\b';
import common from '../../CommonPropertiesPanel.module.scss';

interface RedactionPanelBodyProps {
  controller: any;
}

/* eslint-disable @typescript-eslint/no-unsafe-call, @typescript-eslint/no-unsafe-member-access */
export function RedactionPanelBody({ controller }: RedactionPanelBodyProps): React.JSX.Element {
  const intl = useIntl();
  // ── Read operator attribute metadata from Redux (passed via Canvas.tsx) ──
  const operatorMetadata = (controller?.getAppData?.()?.operatorMetadata ?? {}) as Record<string, OperatorMetadata>;
  const nodeAttributes: Record<string, OperatorFeature> = operatorMetadata[NodeOperator.REDACTION]?.attributes ?? {};

  // ── Read current saved values from Elyra, falling back to backend defaults ──
  const redactionRegex = (controller?.getPropertyValue?.({ name: ATTR.REDACTION_REGEX }) as string | undefined)
    ?? (nodeAttributes[ATTR.REDACTION_REGEX]?.default as string | undefined)
    ?? '';

  const maskingCharacter = (controller?.getPropertyValue?.({ name: ATTR.REDACTION_MASKING_CHARACTER }) as string | undefined)
    ?? (nodeAttributes[ATTR.REDACTION_MASKING_CHARACTER]?.default as string | undefined)
    ?? '*';

  // ── Required param validation ─────────────────────────────────────────────
  const validate = getRequiredParamValidator(nodeAttributes);
  const redactionRegexValidation = validate(ATTR.REDACTION_REGEX, redactionRegex);
  const maskingCharacterValidation = validate(ATTR.REDACTION_MASKING_CHARACTER, maskingCharacter);

  return (
    <div className={common.commonPropertiesPanelBody}>

      {/* ── Redaction pattern ───────────────────────────────────────────── */}
      <div className={common.formField}>
        <div className={common.labelWithTooltip}>
          <RequiredParamTooltip
            paramId={ATTR.REDACTION_REGEX}
            nodeAttributes={nodeAttributes}
            definition={nodeAttributes[ATTR.REDACTION_REGEX]?.description
              ?? intl.formatMessage(messages.redactionRegexDescription)}
          >
            {intl.formatMessage(messages.redactionRegex)}
          </RequiredParamTooltip>
        </div>
        <TextInput
          id="redaction_regex"
          labelText={intl.formatMessage(messages.redactionRegex)}
          hideLabel
          placeholder={intl.formatMessage(messages.redactionRegexPlaceholder, { pattern: REDACTION_REGEX_EXAMPLE })}
          value={redactionRegex}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
            controller?.updatePropertyValue?.({ name: ATTR.REDACTION_REGEX }, e.target.value);
          }}
          invalid={redactionRegexValidation.isInvalid}
          invalidText={redactionRegexValidation.errorMessage}
        />
      </div>

      {/* ── Masking character ───────────────────────────────────────────── */}
      <div className={common.formField}>
        <div className={common.labelWithTooltip}>
          <RequiredParamTooltip
            paramId={ATTR.REDACTION_MASKING_CHARACTER}
            nodeAttributes={nodeAttributes}
            definition={nodeAttributes[ATTR.REDACTION_MASKING_CHARACTER]?.description
              ?? intl.formatMessage(messages.maskingCharacterDescription)}
          >
            {intl.formatMessage(messages.maskingCharacter)}
          </RequiredParamTooltip>
        </div>
        <TextInput
          id="redaction_masking_character"
          labelText={intl.formatMessage(messages.maskingCharacter)}
          hideLabel
          placeholder="*"
          maxLength={1}
          value={maskingCharacter}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
            controller?.updatePropertyValue?.({ name: ATTR.REDACTION_MASKING_CHARACTER }, e.target.value);
          }}
          invalid={maskingCharacterValidation.isInvalid}
          invalidText={maskingCharacterValidation.errorMessage}
        />
      </div>

    </div>
  );
}
