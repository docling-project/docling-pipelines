/**
 * @file LanguageDetect properties panel body.
 *
 * Renders the configuration UI for the `lang_detect` operator node.
 *
 * Parameters map directly to `LanguageDetect.get_metadata()["attributes"]`:
 *
 * **Data flow**:
 * - `controller.getAppData().operatorMetadata` — backend attribute metadata (descriptions, defaults)
 * - `controller.getPropertyValue({ name })` — reads saved node parameter
 * - `controller.updatePropertyValue({ name }, value)` — writes node parameter on change
 */

import React from 'react';
import { getRequiredParamValidator } from '@/utils/requiredParamValidation';
import { RequiredParamTooltip } from '@/components/common';
import { DefinitionTooltip, Dropdown, Toggle } from '@carbon/react';
import { useIntl } from 'react-intl';
import type { OperatorFeature, OperatorMetadata } from '@/types';
import { NodeOperator } from '@/constants/operators';
import {
  LANGUAGE_DETECT_ATTR as ATTR,
  LANGUAGE_DETECT_PROVIDER_ITEMS as PROVIDER_ITEMS,
} from './constants';
import { messages } from './LanguageDetect.messages';
import common from '../../CommonPropertiesPanel.module.scss';

interface LanguageDetectPanelBodyProps {
  controller: any;
}

export function LanguageDetectPanelBody({
  controller,
}: LanguageDetectPanelBodyProps): React.JSX.Element {
  const intl = useIntl();

  // ── Read operator attribute metadata from Redux (passed via Canvas.tsx) ──
  // eslint-disable-next-line @typescript-eslint/no-unsafe-call
  const operatorMetadata = (controller?.getAppData?.()?.operatorMetadata ?? {}) as Record<string, OperatorMetadata>;
  const nodeAttributes: Record<string, OperatorFeature> = operatorMetadata[NodeOperator.LANG_DETECT]?.attributes ?? {};

  // ── Read current saved values, falling back to backend defaults ──────────
  const languageProvider: string =
    // eslint-disable-next-line @typescript-eslint/no-unsafe-call
    (controller?.getPropertyValue?.({ name: ATTR.LANGUAGE_PROVIDER }) as string | undefined)
    ?? (nodeAttributes[ATTR.LANGUAGE_PROVIDER]?.default as string | undefined)
    ?? 'fasttext';

  const filterUnknownLanguage: boolean =
    // eslint-disable-next-line @typescript-eslint/no-unsafe-call
    (controller?.getPropertyValue?.({ name: ATTR.FILTER_UNKNOWN_LANGUAGE }) as boolean | undefined)
    ?? (nodeAttributes[ATTR.FILTER_UNKNOWN_LANGUAGE]?.default as boolean | undefined)
    ?? false;

  // ── Required param validation ─────────────────────────────────────────────
  const validate = getRequiredParamValidator(nodeAttributes);
  const languageProviderValidation = validate(ATTR.LANGUAGE_PROVIDER, languageProvider);

  return (
    <div className={common.commonPropertiesPanelBody}>

      {/* ── Language provider ────────────────────────────────────────── */}
      <div className={common.formField}>
        <div className={common.labelWithTooltip}>
          <RequiredParamTooltip
            paramId={ATTR.LANGUAGE_PROVIDER}
            nodeAttributes={nodeAttributes}
            definition={nodeAttributes[ATTR.LANGUAGE_PROVIDER]?.description ?? ''}
          >
            {intl.formatMessage(messages.languageProvider)}
          </RequiredParamTooltip>
        </div>
        <Dropdown
          id="language_provider"
          titleText={intl.formatMessage(messages.languageProvider)}
          hideLabel
          label={intl.formatMessage(messages.selectProvider)}
          items={PROVIDER_ITEMS}
          selectedItem={languageProvider}
          onChange={({ selectedItem }: { selectedItem: string | null }) => {
            if (selectedItem) {
              // eslint-disable-next-line @typescript-eslint/no-unsafe-call
              controller?.updatePropertyValue?.({ name: ATTR.LANGUAGE_PROVIDER }, selectedItem);
            }
          }}
          invalid={languageProviderValidation.isInvalid}
          invalidText={languageProviderValidation.errorMessage}
        />
      </div>

      {/* ── Filter unknown language ──────────────────────────────────── */}
      <div className={common.formField}>
        <div className={common.labelWithTooltip}>
          <DefinitionTooltip
            definition={nodeAttributes[ATTR.FILTER_UNKNOWN_LANGUAGE]?.description ?? ''}
            openOnHover
            align="right"
          >
            {intl.formatMessage(messages.filterUnknownLanguage)}
          </DefinitionTooltip>
        </div>
        <Toggle
          id="filter_unknown_language"
          labelText={intl.formatMessage(messages.filterUnknownLanguage)}
          hideLabel
          labelA={intl.formatMessage(messages.off)}
          labelB={intl.formatMessage(messages.on)}
          toggled={filterUnknownLanguage}
          onToggle={(checked: boolean) => {
            // eslint-disable-next-line @typescript-eslint/no-unsafe-call
            controller?.updatePropertyValue?.({ name: ATTR.FILTER_UNKNOWN_LANGUAGE }, checked);
          }}
        />
      </div>
    </div>
  );
}
