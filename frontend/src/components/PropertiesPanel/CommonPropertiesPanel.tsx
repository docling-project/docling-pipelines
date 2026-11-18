/**
 * Common Properties Panel - custom panel rendered by Elyra's CommonProperties
 *
 * This component is used as a `customPanel` registered via CommonPropertiesPanelWrapper.
 * Elyra's CommonProperties (with rightFlyout: true) manages the flyout container,
 * expand/collapse button, and Save/Cancel buttons.
 * This panel only renders the inner content: header (icon, label, description) + tabs.
 *
 * To add a configuration panel for a new operator, create a component under
 * CustomPanels/<OperatorName>/ and add it to OPERATOR_PANEL_MAP below.
 */

import React, {
  useState,
  useRef,
  useEffect,
  useCallback,
  useMemo,
} from 'react';
import {
  Tabs,
  TabList,
  Tab,
  TabPanels,
  TabPanel,
  TextInput,
  IconButton,
} from '@carbon/react';
import { Edit } from '@carbon/icons-react';
import { useIntl } from 'react-intl';
import { NodeOperator } from '@/constants/operators';
import { getOperatorLabel } from '@/constants/operatorLabels';
import { getIconForOperator } from '@/utils/paletteEnhancer';
import { AnnotationFilterPanelBody } from './CustomPanels/AnnotationFilter/AnnotationFilter';
import { BranchingPanelBody } from './CustomPanels/Branching/Branching';
import { ChunkerPanelBody } from './CustomPanels/Chunker/Chunker';
import { DocumentClassifierPanelBody } from './CustomPanels/DocumentClassifier/DocumentClassifier';
import { DocumentSetPanelBody } from './CustomPanels/DocumentSet/DocumentSet';
import { EdedupPanelBody } from './CustomPanels/Ededup/Ededup';
import { EmbeddingsPanelBody } from './CustomPanels/Embeddings/Embeddings';
import { EntityCurationPanelBody } from './CustomPanels/EntityCuration/EntityCuration';
import { ExtractPanelBody } from './CustomPanels/Extract/Extract';
import { IngestSourcePanelBody } from './CustomPanels/IngestSource/IngestSource';
import { MergingPanelBody } from './CustomPanels/Merging/Merging';
import { MlEnrichmentPanelBody } from './CustomPanels/MlEnrichment/MlEnrichment';
import { PiiAndHapPanelBody } from './CustomPanels/PiiAndHap/PiiAndHap';
import { ReadabilityPanelBody } from './CustomPanels/Readability/Readability';
import { RedactionPanelBody } from './CustomPanels/Redaction/Redaction';
import { LanguageDetectPanelBody } from './CustomPanels/LanguageDetect/LanguageDetect';
import { ACLPanelBody } from './CustomPanels/ACL/ACL';
import { VectorDBPanelBody } from './CustomPanels/VectorDB/VectorDB';
import { DocQualityPanelBody } from './CustomPanels/DocQuality/DocQuality';
import { NoopPanelBody } from './CustomPanels/Noop/Noop';
import { StorageOutputPanelBody } from './CustomPanels/StorageOutput/StorageOutput';
import { InputFeaturesTab } from './FeatureTabs/InputFeaturesTab';
import { OutputFeaturesTab } from './FeatureTabs/OutputFeaturesTab';
import type { NodeFeatureMap } from '@/utils/fetchNodeFeatures';
import type { FeatureAttributes } from '@/types';
import styles from './CommonPropertiesPanel.module.scss';
import { PROPERTIES_PANEL_CONSTANTS } from '@/constants/propertiesPanelConstants';
import { hasAnyRequiredParamMissing } from '@/utils/requiredParamValidation';
import { messages } from './CommonPropertiesPanel.messages';
import type { OperatorFeature, OperatorMetadata } from '@/types';

// ---------------------------------------------------------------------------
// Operator → ConfigureComponent map
// Add new operator panels here as they are implemented.
// TODO: Register additional operator panels here once their metadata is confirmed.
// ---------------------------------------------------------------------------
const OPERATOR_PANEL_MAP: Record<string, React.ComponentType<{ controller: any }>> = {
  [NodeOperator.INGEST_SOURCE]: IngestSourcePanelBody,
  [NodeOperator.EXTRACT]: ExtractPanelBody,
  [NodeOperator.CHUNKER]: ChunkerPanelBody,
  [NodeOperator.EMBEDDINGS]: EmbeddingsPanelBody,
  [NodeOperator.DOCUMENT_CLASSIFIER]: DocumentClassifierPanelBody,
  [NodeOperator.DOCUMENT_SET]: DocumentSetPanelBody,
  [NodeOperator.ML_ENRICHMENT]: MlEnrichmentPanelBody,
  [NodeOperator.LANG_DETECT]: LanguageDetectPanelBody,
  [NodeOperator.DOC_QUALITY]: DocQualityPanelBody,
  [NodeOperator.SQL_FILTER]: AnnotationFilterPanelBody,
  [NodeOperator.DEDUPLICATION]: EdedupPanelBody,
  [NodeOperator.REDACTION]: RedactionPanelBody,
  [NodeOperator.READABILITY]: ReadabilityPanelBody,
  [NodeOperator.ENTITY_CURATION]: EntityCurationPanelBody,
  [NodeOperator.VECTORDB]: VectorDBPanelBody,
  [NodeOperator.ACL_OPERATOR]: ACLPanelBody,
  [NodeOperator.NOOP]: NoopPanelBody,
  [NodeOperator.PII_AND_HAP]: PiiAndHapPanelBody,
  [NodeOperator.BRANCHING]: BranchingPanelBody,
  [NodeOperator.MERGING]: MergingPanelBody,
  [NodeOperator.STORAGE_OUTPUT]: StorageOutputPanelBody,
};

interface CommonPropertiesPanelProps {
  // Elyra customPanel props
  parameters?: any;
  controller?: any;
  data?: any;
}

/**
 * Inner panel content rendered by Elyra CommonProperties as a customPanel.
 * Do NOT add Save/Cancel buttons or outer flyout wrappers here —
 * CommonProperties (rightFlyout: true) provides those automatically.
 */
export function CommonPropertiesPanel({
  controller,
}: CommonPropertiesPanelProps): React.JSX.Element {
  const intl = useIntl();
  const [selectedTab, setSelectedTab] = useState(0);

  // Resolve node info from Elyra controller app data
  // eslint-disable-next-line @typescript-eslint/no-unsafe-call
  const currentNodeId: string = controller?.getAppData()?.nodeId ?? '';
  // eslint-disable-next-line @typescript-eslint/no-unsafe-call
  const nodes: any[] = controller?.getAppData()?.pipelineFlow?.pipelines?.[0]?.nodes ?? [];
  const selectedNode = nodes.find((n: any) => n.id === currentNodeId);
  const operatorName: string = selectedNode?.op ?? '';
  // Feature map and loading state passed in from Canvas.tsx via appData
  // eslint-disable-next-line @typescript-eslint/no-unsafe-call
  const appData = controller?.getAppData() ?? {};
  // eslint-disable-next-line @typescript-eslint/no-unsafe-member-access
  const nodeFeatureMap: NodeFeatureMap = appData.nodeFeatureMap ?? {};
  // eslint-disable-next-line @typescript-eslint/no-unsafe-member-access
  const featuresLoading: boolean = appData.featuresLoading === true;
  const currentNodeFeatures = nodeFeatureMap[currentNodeId] ?? { input_features: {}, output_features: {} };

  const metadata = getOperatorLabel(operatorName);

  // Display label — Source of truth from controller property value if set, else fallback to metadata label
  const computedLabel: string =
    // eslint-disable-next-line @typescript-eslint/no-unsafe-call
    (controller?.getPropertyValue?.({ name: PROPERTIES_PANEL_CONSTANTS.DISPLAY_LABEL_PROPERTY }) as string | undefined) ??
    (selectedNode?.app_data?.ui_data?.label as string | undefined) ??
    metadata.label;

  const [isEditingLabel, setIsEditingLabel] = useState(false);
  const displayLabelInputRef = useRef<HTMLInputElement>(null);

  const handleEditLabel = (): void => {
    setIsEditingLabel(true);
    setTimeout(() => {
      displayLabelInputRef.current?.focus();
    }, 0);
  };

  const handleLabelChange = (e: React.ChangeEvent<HTMLInputElement>): void => {
    const newValue = e.target.value;
    // eslint-disable-next-line @typescript-eslint/no-unsafe-call
    controller?.updatePropertyValue?.({ name: PROPERTIES_PANEL_CONSTANTS.DISPLAY_LABEL_PROPERTY }, newValue);
  };

  const handleLabelBlur = (): void => {
    setIsEditingLabel(false);
  };

  /* eslint-disable @typescript-eslint/no-unsafe-call */
  const operatorMetadata = useMemo(
    () => (controller?.getAppData?.()?.operatorMetadata ?? {}) as Record<string, OperatorMetadata>,
    [controller]
  );

  const nodeAttributes = useMemo(
    (): Record<string, OperatorFeature> => operatorMetadata[operatorName]?.attributes ?? {},
    [operatorMetadata, operatorName]
  );

  // Disable the Save button whenever at least one required attribute is missing a value.
  const updateSaveButton = useCallback((): void => {

    const propertyValues = (controller?.getPropertyValues?.() ?? {}) as Record<string, unknown>;

    const shouldDisable = hasAnyRequiredParamMissing(nodeAttributes, propertyValues);

    controller?.setSaveButtonDisable?.(shouldDisable);
  }, [controller, nodeAttributes]);

  useEffect(() => {
    updateSaveButton();
  }, [updateSaveButton]);

  // Look up the operator-specific configuration panel (falls back to null = placeholder)
  const ConfigureComponent = OPERATOR_PANEL_MAP[operatorName] ?? null;

  const inputFeatures = currentNodeFeatures.input_features;
  const ownOutputFeatures = currentNodeFeatures.output_features;

  // The Output tab should show everything a downstream node would receive:
  // the node's own new features PLUS the input features that pass through.
  // Merge nodes are excluded — the backend already writes their union directly
  // into output_features (the active strategy bucket).
  const isMerge = operatorName === 'merge';
  const outputFeatures: Record<string, FeatureAttributes> = isMerge
    ? ownOutputFeatures
    : { ...inputFeatures, ...ownOutputFeatures };

  return (
    <div className={styles.commonPropertiesPanelContainer}>
      {/* Header: operator icon + operator type label */}
      <div className={styles.commonPropertiesPanelHeader}>
        <span className={styles.nodeIcon}>{getIconForOperator(operatorName)}</span>
        <p className={styles.nodeLabel}>{metadata.label}</p>
      </div>

      {/* Editable display label */}
      <div className={styles.displayLabel}>
        <TextInput
          id="displayLabel"
          ref={displayLabelInputRef}
          value={computedLabel}
          size="sm"
          labelText={intl.formatMessage(messages.displayName)}
          hideLabel
          readOnly={!isEditingLabel}
          onChange={handleLabelChange}
          onBlur={handleLabelBlur}
        />
        {!isEditingLabel && (
          <IconButton
            label={intl.formatMessage(messages.editDisplayName)}
            autoAlign
            size="sm"
            kind="ghost"
            onClick={handleEditLabel}
          >
            <Edit />
          </IconButton>
        )}
      </div>

      {/* Node description */}
      <div className={styles.nodeDescription}>{metadata.description}</div>

      {/* Configuration / Input / Output tabs */}
      <Tabs
        selectedIndex={selectedTab}
        onChange={({ selectedIndex }): void => {
          setSelectedTab(selectedIndex);
        }}
      >
        <TabList aria-label={intl.formatMessage(messages.tabsAriaLabel)}>
          <Tab>{intl.formatMessage(messages.configurationTab)}</Tab>
          <Tab>{intl.formatMessage(messages.inputTab)}</Tab>
          <Tab>{intl.formatMessage(messages.outputTab)}</Tab>
        </TabList>
        <TabPanels>
          <TabPanel>
            <div className={styles.tabContent}>
              {ConfigureComponent ? (
                <ConfigureComponent key={currentNodeId} controller={controller} />
              ) : (
                <p className={styles.configurationLabel}>
                  {intl.formatMessage(messages.configurationPlaceholder)}
                </p>
              )}
            </div>
          </TabPanel>
          <TabPanel>
            <InputFeaturesTab
              nodeId={currentNodeId}
              inputFeatures={inputFeatures}
              pipelineNodes={nodes}
              isLoading={featuresLoading}
            />
          </TabPanel>
          <TabPanel>
            <OutputFeaturesTab
              nodeId={currentNodeId}
              outputFeatures={outputFeatures}
              pipelineNodes={nodes}
              isLoading={featuresLoading}
              controller={controller}
            />
          </TabPanel>
        </TabPanels>
      </Tabs>
    </div>
  );
}
