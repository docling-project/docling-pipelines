/**
 * @file EntityCuration properties panel body.
 *
 * Renders the configuration UI for the `entity_curation` operator node.
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
import { ENTITY_CURATION_ATTRIBUTE as ATTR } from './constants';
import { messages } from './EntityCuration.messages';
import common from '../../CommonPropertiesPanel.module.scss';

interface EntityCurationPanelBodyProps {
  controller: any;
}

export function EntityCurationPanelBody({
  controller,
}: EntityCurationPanelBodyProps): React.JSX.Element {
  const intl = useIntl();

  // ── Read operator attribute metadata from Redux (passed in via Canvas.tsx) ──
  // eslint-disable-next-line @typescript-eslint/no-unsafe-call
  const operatorMetadata = (controller?.getAppData?.()?.operatorMetadata ?? {}) as Record<string, OperatorMetadata>;
  const nodeAttributes: Record<string, OperatorFeature> = operatorMetadata[NodeOperator.ENTITY_CURATION]?.attributes ?? {};

  // ── Read current saved values, falling back to backend defaults from metadata ──
  // eslint-disable-next-line @typescript-eslint/no-unsafe-call
  const entitiesColumn = (controller?.getPropertyValue?.({ name: ATTR.ENTITIES_COLUMN }) as string | undefined)
    ?? (nodeAttributes[ATTR.ENTITIES_COLUMN]?.default as string | undefined);

  // eslint-disable-next-line @typescript-eslint/no-unsafe-call
  const documentTypeColumn = (controller?.getPropertyValue?.({ name: ATTR.DOCUMENT_TYPE_COLUMN }) as string | undefined)
    ?? (nodeAttributes[ATTR.DOCUMENT_TYPE_COLUMN]?.default as string | undefined);

  // ── Required param validation ─────────────────────────────────────────────
  const validate = getRequiredParamValidator(nodeAttributes);
  const entitiesColumnValidation = validate(ATTR.ENTITIES_COLUMN, entitiesColumn);
  const documentTypeColumnValidation = validate(ATTR.DOCUMENT_TYPE_COLUMN, documentTypeColumn);

  return (
    <div className={common.commonPropertiesPanelBody}>

      {/* ── Entities column ───────────────────────────────────────────── */}
      <div className={common.formField}>
        <div className={common.labelWithTooltip}>
          <RequiredParamTooltip
            paramId={ATTR.ENTITIES_COLUMN}
            nodeAttributes={nodeAttributes}
            definition={nodeAttributes[ATTR.ENTITIES_COLUMN]?.description ?? ''}
          >
            {intl.formatMessage(messages.entitiesColumn)}
          </RequiredParamTooltip>
        </div>
        <TextInput
          id="entities_column"
          labelText={intl.formatMessage(messages.entitiesColumn)}
          hideLabel
          value={entitiesColumn}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
            // eslint-disable-next-line @typescript-eslint/no-unsafe-call
            controller?.updatePropertyValue?.({ name: ATTR.ENTITIES_COLUMN }, e.target.value);
          }}
          invalid={entitiesColumnValidation.isInvalid}
          invalidText={entitiesColumnValidation.errorMessage}
        />
      </div>

      {/* ── Document type column ──────────────────────────────────────── */}
      <div className={common.formField}>
        <div className={common.labelWithTooltip}>
          <RequiredParamTooltip
            paramId={ATTR.DOCUMENT_TYPE_COLUMN}
            nodeAttributes={nodeAttributes}
            definition={nodeAttributes[ATTR.DOCUMENT_TYPE_COLUMN]?.description ?? ''}
          >
            {intl.formatMessage(messages.documentTypeColumn)}
          </RequiredParamTooltip>
        </div>
        <TextInput
          id="document_type_column"
          labelText={intl.formatMessage(messages.documentTypeColumn)}
          hideLabel
          value={documentTypeColumn}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
            // eslint-disable-next-line @typescript-eslint/no-unsafe-call
            controller?.updatePropertyValue?.({ name: ATTR.DOCUMENT_TYPE_COLUMN }, e.target.value);
          }}
          invalid={documentTypeColumnValidation.isInvalid}
          invalidText={documentTypeColumnValidation.errorMessage}
        />
      </div>

    </div>
  );
}
