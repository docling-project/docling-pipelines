/**
 * @file Readability operator configuration panel body.
 *
 * Renders the configuration UI for the `readability` operator node.
 *
 * Parameters (from ReadabilityOperator.get_metadata()["attributes"]):
 * - `readability_score_list` — list of score identifiers to compute (multi-select)
 *
 * The valid values and their display names are sourced from:
 * 1. `controller.getAppData().operatorMetadata["readability"].attributes.readability_score_list.valid_values`
 *    (live from backend, preferred)
 * 2. `READABILITY_SCORE_OPTIONS` constant (static fallback)
 *
 * UI conventions:
 * - `DefinitionTooltip` with `openOnHover` → description on hover
 * - `hideLabel` on Carbon inputs → no duplicate label text
 * - `.formField` wrapper → consistent vertical spacing
 */

import React, { useMemo } from 'react';
import { getRequiredParamValidator } from '@/utils/requiredParamValidation';
import { RequiredParamTooltip } from '@/components/common';
import { FilterableMultiSelect } from '@carbon/react';
import { useIntl } from 'react-intl';
import type { OperatorFeature, OperatorMetadata } from '@/types';
import { NodeOperator } from '@/constants/operators';
import { READABILITY_ATTRIBUTE as ATTR, READABILITY_SCORE_LABELS, READABILITY_SCORE_OPTIONS } from './constants';
import { messages } from './Readability.messages';
import common from '../../CommonPropertiesPanel.module.scss';

interface ReadabilityPanelBodyProps {
  controller: any;
}

/* eslint-disable @typescript-eslint/no-unsafe-call, @typescript-eslint/no-unsafe-member-access */
export function ReadabilityPanelBody({ controller }: ReadabilityPanelBodyProps): React.JSX.Element {
  const intl = useIntl();
  // ── Read operator attribute metadata from Redux (passed via Canvas.tsx) ──
  const operatorMetadata = (controller?.getAppData?.()?.operatorMetadata ?? {}) as Record<string, OperatorMetadata>;
  const nodeAttributes: Record<string, OperatorFeature> = operatorMetadata[NodeOperator.READABILITY]?.attributes ?? {};

  // ── Resolve valid score options: prefer live metadata, fall back to static list ──
  const metadataValidValues = (nodeAttributes[ATTR.SCORE_LIST] as Record<string, unknown> | undefined)?.valid_values;
  const scoreOptions: string[] = Array.isArray(metadataValidValues)
    ? (metadataValidValues as string[])
    : [...READABILITY_SCORE_OPTIONS];

  // ── Read current saved value from Elyra, falling back to all scores selected ──
  const scoreListRaw = controller?.getPropertyValue?.({ name: ATTR.SCORE_LIST }) as string[] | string | undefined;

  const selectedScores: string[] = useMemo(() => {
    if (Array.isArray(scoreListRaw)) {
      return scoreListRaw;
    }
    if (typeof scoreListRaw === 'string' && scoreListRaw.length > 0) {
      return scoreListRaw.split(',').map((s) => s.trim()).filter(Boolean);
    }
    // Default: all scores selected (matches backend default)
    const metaDefault = (nodeAttributes[ATTR.SCORE_LIST] as Record<string, unknown> | undefined)?.default;
    if (Array.isArray(metaDefault)) {
      return metaDefault as string[];
    }
    return [...READABILITY_SCORE_OPTIONS];
  }, [scoreListRaw, nodeAttributes]);

  const initialSelectedItems = useMemo(
    () => scoreOptions.filter((score) => selectedScores.includes(score)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [scoreOptions.join(','), selectedScores.join(',')]
  );

  // ── Required param validation ─────────────────────────────────────────────
  const validate = getRequiredParamValidator(nodeAttributes);
  const scoreListValidation = validate(ATTR.SCORE_LIST, selectedScores);

  return (
    <div className={common.commonPropertiesPanelBody}>

      {/* ── Score list multi-select ─────────────────────────────────────── */}
      <div className={common.formField}>
        <div className={common.labelWithTooltip}>
          <RequiredParamTooltip
            paramId={ATTR.SCORE_LIST}
            nodeAttributes={nodeAttributes}
            definition={nodeAttributes[ATTR.SCORE_LIST]?.description
              ?? intl.formatMessage(messages.scoreListDescription)}
          >
            {intl.formatMessage(messages.scoreList)}
          </RequiredParamTooltip>
        </div>
        <FilterableMultiSelect
          id="readability_score_list"
          titleText={intl.formatMessage(messages.scoreList)}
          hideLabel
          placeholder={intl.formatMessage(messages.scoreListPlaceholder)}
          items={scoreOptions}
          itemToString={(item: string | null) => {
            if (!item) { return ''; }
            return READABILITY_SCORE_LABELS[item] ?? item;
          }}
          initialSelectedItems={initialSelectedItems}
          onChange={({ selectedItems }: { selectedItems: string[] }) => {
            controller?.updatePropertyValue?.({ name: ATTR.SCORE_LIST }, selectedItems);
          }}
          invalid={scoreListValidation.isInvalid}
          invalidText={scoreListValidation.errorMessage}
        />
      </div>

    </div>
  );
}
