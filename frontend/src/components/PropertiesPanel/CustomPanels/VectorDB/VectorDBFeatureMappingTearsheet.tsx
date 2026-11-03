/**
 * @file Feature mapping tearsheet for the VectorDB operator.
 *
 * Owns the enrichment API call lifecycle. The tearsheet opens immediately;
 * a loading skeleton is shown while the API is in flight and replaced with
 * content once resolved. The parent panel is never blocked on loading.
 *
 * Existing-resource behaviour:
 * - Similarity and engine dropdowns are read-only when an existing resource is
 *   selected and `stored_resource_metadata` carries those values.
 * - An info notification explains the read-only constraint to the user.
 * - The "Create new" name input is hidden when an existing resource is selected.
 * - New resource name validation: must start with a letter or underscore;
 *   only letters, numbers, and underscores are allowed.
 * - Unsupported resource: the Save button is disabled and the mappings table
 *   is replaced with an error empty state.
 */

import React, { useState, useMemo, useEffect, useCallback } from 'react';
import { useIntl } from 'react-intl';
import { useThemeElement } from '@/contexts';
import {
  Checkbox,
  ComboBox,
  DataTableSkeleton,
  Dropdown,
  InlineNotification,
  Loading,
  TextInput,
  TextInputSkeleton,
} from '@carbon/react';
import { ErrorEmptyState } from '@carbon/ibm-products';
import { Tearsheet } from '@carbon/ibm-products';
import type { FeatureMappingRow, FeatureMappingItem, VectorDBEnrichmentResult } from '@/types';
import { enrichFlowFeaturesForNode } from './vectordb-enrichment';
import {
  DEFAULT_COLUMN_MAPPINGS,
  VECTORDB_LABELS,
  VECTORDB_PROVIDERS,
  omitProviderConfigKeys,
  type ProviderConfig,
} from './constants';
import { messages } from './VectorDBFeatureMappingTearsheet.messages';
import { VectorDBFeatureMappingTable } from './VectorDBFeatureMappingTable';
import { AddFeatureMappingModal } from './AddFeatureMappingModal';
import styles from './VectorDB.module.scss';

const { CREATE_NEW } = VECTORDB_LABELS;

/** Validation for new resource names: must start with letter/underscore, then word chars only. */
const NEW_RESOURCE_NAME_RE = /^[A-Za-z_]\w*$/;

interface VectorDBFeatureMappingTearsheetProps {
  open: boolean;
  onClose: () => void;
  onSave: (data: {
    resourceName: string;
    similarityMetric: string;
    engine: string;
    featureMappings: FeatureMappingRow[];
    addSparseVector: boolean;
  }) => void;
  /** Provider-specific config — keys, labels, defaults. No if/switch needed. */
  providerCfg: ProviderConfig;
  /** The active provider string (e.g. "opensearch" / "milvus") — passed to enrichment API. */
  provider: string;
  /** Previously saved index/collection name — pre-fills the selector on re-open. */
  savedResourceName: string;
  currentFeatureMappings: FeatureMappingRow[];
  /** Full Elyra pipeline JSON — passed to the enrichment API. */
  pipelineFlow: object;
  /** Elyra node ID of this vectordb node. */
  nodeId: string;
  /** Already-parsed provider_config object. */
  parsedProviderConfig: Record<string, unknown>;
  /** Whether sparse vector (BM25) support is enabled. Milvus-only. */
  addSparseVector: boolean;
  /** Valid similarity values from operator metadata (space_type / metric_type). */
  vectorSimilarityOptions: string[];
  /** Saved similarity value from provider_config — pre-fills dropdown on re-open. */
  savedVectorSimilarity: string;
  /** Valid engine values from operator metadata (OpenSearch only). */
  engineOptions: string[];
  /** Saved engine from provider_config — pre-fills dropdown on re-open. */
  savedEngine: string;
}

/**
 * Derive the initial rows for the mappings table on tearsheet open.
 *
 * Priority:
 * 1. currentFeatureMappings (user's saved edits) when they exist — preserves
 *    column edits the user made on a previous save for the same resource.
 *    Descriptions and mandatory flags are enriched from available_features.
 * 2. API-returned feature_mappings when no saved mappings exist yet (first open).
 * 3. available_features keys as a last resort when API returns no mappings.
 */
function buildTableRows(
  enrichmentResult: VectorDBEnrichmentResult | null,
  currentFeatureMappings: FeatureMappingRow[]
): FeatureMappingItem[] {
  const availableFeatures = enrichmentResult?.available_features ?? {};
  const apiMappings = enrichmentResult?.feature_mappings ?? [];

  // Priority 1: user's previously saved mappings — use saved column values,
  // enrich descriptions and mandatory flags from the latest API response.
  if (currentFeatureMappings.length > 0) {
    return currentFeatureMappings.map(({ feature_name, mapped_column_name }) => ({
      feature: feature_name,
      description: availableFeatures[feature_name]?.description ?? '',
      column: mapped_column_name || (DEFAULT_COLUMN_MAPPINGS[feature_name] ?? feature_name),
      isMandatory: availableFeatures[feature_name]?.mandatory_for_vector_db ?? false,
    }));
  }

  // Priority 2: API-returned mappings (first open, no saved mappings yet).
  if (apiMappings.length > 0) {
    return apiMappings.map(({ feature_name, mapped_column_name }) => ({
      feature: feature_name,
      description: availableFeatures[feature_name]?.description ?? '',
      column: mapped_column_name || (DEFAULT_COLUMN_MAPPINGS[feature_name] ?? feature_name),
      isMandatory: availableFeatures[feature_name]?.mandatory_for_vector_db ?? false,
    }));
  }

  // Priority 3: available_features keys with default column names.
  const featureKeys = Object.keys(availableFeatures);
  if (featureKeys.length > 0) {
    return featureKeys.map((name) => ({
      feature: name,
      description: availableFeatures[name]?.description ?? '',
      column: DEFAULT_COLUMN_MAPPINGS[name] ?? name,
      isMandatory: availableFeatures[name]?.mandatory_for_vector_db ?? false,
    }));
  }

  return [];
}

export function VectorDBFeatureMappingTearsheet({
  open,
  onClose,
  onSave,
  providerCfg,
  provider,
  savedResourceName,
  currentFeatureMappings,
  pipelineFlow,
  nodeId,
  parsedProviderConfig,
  vectorSimilarityOptions,
  savedVectorSimilarity,
  engineOptions,
  savedEngine,
  addSparseVector,
}: VectorDBFeatureMappingTearsheetProps): React.JSX.Element {
  const intl = useIntl();
  const portalTarget = useThemeElement();
  const {
    resourceLabel,
    resourceNameKey,
    similarityLabel,
    hasEngine,
  } = providerCfg;

  const similarityMetricLabels: Record<string, string> = {
    l2: intl.formatMessage(messages.metricL2),
    L2: intl.formatMessage(messages.metricL2Milvus),
    cosine: intl.formatMessage(messages.metricCosine),
    COSINE: intl.formatMessage(messages.metricCosine),
    inner_product: intl.formatMessage(messages.metricInnerProduct),
    IP: intl.formatMessage(messages.metricIPMilvus),
    BM25: intl.formatMessage(messages.metricBM25),
  };

  const engineOptionLabels: Record<string, string> = {
    faiss: intl.formatMessage(messages.engineFaiss),
    lucene: intl.formatMessage(messages.engineLucene),
    nmslib: intl.formatMessage(messages.engineNmslib),
    jvector: intl.formatMessage(messages.engineJvector),
  };

  /** Validate a proposed new resource name. Returns an error string or null. */
  const validateNewName = useCallback((name: string, existingNames: string[]): string | null => {
    const trimmed = name.trim();
    if (!trimmed) { return intl.formatMessage(messages.nameRequired); }
    if (!/^[A-Za-z_]/.test(trimmed)) { return intl.formatMessage(messages.nameMustStartWithLetter); }
    if (!NEW_RESOURCE_NAME_RE.test(trimmed)) { return intl.formatMessage(messages.nameOnlyLettersNumbersUnderscores); }
    if (existingNames.includes(trimmed)) { return intl.formatMessage(messages.nameAlreadyExists, { name: trimmed }); }
    return null;
  }, [intl]);

  // ── Enrichment state — owned here, not in the parent panel ──
  const [loading, setLoading] = useState(false);
  // Separate from `loading`: true only while re-enriching after resource selection.
  // Controls keep showing while only the table area skeleton is active.
  const [loadingMappings, setLoadingMappings] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [enrichmentResult, setEnrichmentResult] = useState<VectorDBEnrichmentResult | null>(null);

  // ── Form state ──
  const [selectedResource, setSelectedResource] = useState<string>(CREATE_NEW);
  const [newResourceName, setNewResourceName] = useState<string>('');
  const [newNameError, setNewNameError] = useState<string | null>(intl.formatMessage(messages.nameRequired));
  const [resourceNameEdited, setResourceNameEdited] = useState<boolean>(true);
  const [similarityMetric, setSimilarityMetric] = useState<string>(savedVectorSimilarity);
  const [engine, setEngine] = useState<string>(savedEngine);
  const [submitted, setSubmitted] = useState<boolean>(false);
  const [isAddModalOpen, setIsAddModalOpen] = useState<boolean>(false);
  const [tableRows, setTableRows] = useState<FeatureMappingItem[]>([]);
  const [sparseVectorEnabled, setSparseVectorEnabled] = useState<boolean>(addSparseVector);

  // Cancellation token for in-flight API calls — incremented on each new call
  // so stale responses from superseded requests are discarded.
  const runRef = React.useRef(0);

  // Fire the enrichment API whenever the tearsheet opens.
  // The tearsheet opens immediately; the loading skeleton renders inside it.
  useEffect(() => {
    if (!open) { return; }

    runRef.current += 1;
    const token = runRef.current;

    const run = async () => {
      setLoading(true);
      setLoadError(null);
      setEnrichmentResult(null);

      try {
        // Pass savedResourceName so the backend returns stored_resource_metadata
        // (vector_similarity, dimension_size) for the already-saved resource.
        // Pass undefined when creating new (empty savedResourceName) so the backend
        // returns defaults instead.
        const result = await enrichFlowFeaturesForNode(
          pipelineFlow, nodeId, provider, parsedProviderConfig, resourceNameKey,
          savedResourceName || undefined,
          sparseVectorEnabled
        );
        if (runRef.current !== token) { return; }
        setEnrichmentResult(result);

        // Initialise form state from the API response.
        const availableResources = result?.available_resources ?? [];
        const storedMeta = result?.stored_resource_metadata;
        const isCreateNew = !availableResources.includes(savedResourceName);

        setSelectedResource(isCreateNew ? CREATE_NEW : savedResourceName);
        setNewResourceName(isCreateNew ? savedResourceName : '');
        setNewNameError(validateNewName(isCreateNew ? savedResourceName : '', availableResources));
        setResourceNameEdited(true);
        setSimilarityMetric(storedMeta?.vector_similarity ?? savedVectorSimilarity);
        setEngine(savedEngine);
        setSubmitted(false);
        setIsAddModalOpen(false);
        setSparseVectorEnabled(addSparseVector);
        setTableRows(buildTableRows(result, currentFeatureMappings));
      } catch {
        if (runRef.current !== token) { return; }
        setLoadError(intl.formatMessage(messages.loadResourcesError));
        // Still show the tearsheet with last-saved mappings so the user is not blocked.
        setSelectedResource(savedResourceName ? savedResourceName : CREATE_NEW);
        setNewResourceName('');
        setTableRows(buildTableRows(null, currentFeatureMappings));
      } finally {
        if (runRef.current === token) { setLoading(false); }
      }
    };

    void run();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]); // re-runs only when the tearsheet opens/closes

  const availableResources = enrichmentResult?.available_resources ?? [];
  const storedMeta = enrichmentResult?.stored_resource_metadata;
  const availableFeatures = enrichmentResult?.available_features ?? {};

  const isCreateNew = selectedResource === CREATE_NEW;

  const effectiveResourceName = isCreateNew
    ? newResourceName.trim()
    : selectedResource;

  // Similarity and engine are locked for existing resources when the backend
  // already knows those values (they were set at index/collection creation time).
  const isConfigReadOnly = !isCreateNew && Boolean(storedMeta?.vector_similarity);

  const handleResourceChange = ({ selectedItem }: { selectedItem?: string | null }): void => {
    const selectedResourceName = selectedItem ?? CREATE_NEW;
    setSelectedResource(selectedResourceName);
    setLoadError(null);

    // Strip all resource-specific keys from provider_config before sending —
    // these are saved state and must not bleed into the API call for a different
    // resource (or for create-new). Uses providerCfg.resourceSpecificKeys so
    // no hardcoded key names live in this component.
    const baseConfig = omitProviderConfigKeys(parsedProviderConfig, providerCfg.resourceSpecificKeys);

    runRef.current += 1;
    const token = runRef.current;

    // When creating new: omit the resource name so the backend returns generic
    // defaults. When selecting existing: pass the name so the backend returns
    // stored_resource_metadata and feature_mappings for that specific resource.
    const resourceArg = selectedResourceName === CREATE_NEW ? undefined : selectedResourceName;

    const fetchOnResourceChange = async () => {
      setLoadingMappings(true);
      try {
        const result = await enrichFlowFeaturesForNode(
          pipelineFlow, nodeId, provider, baseConfig, resourceNameKey, resourceArg,
          sparseVectorEnabled
        );
        if (runRef.current !== token) { return; }
        setEnrichmentResult(result);
        // For existing resources use the stored similarity; for new ones reset to the saved default.
        const freshMeta = result?.stored_resource_metadata;
        const nextSimilarity = resourceArg
          ? (freshMeta?.vector_similarity ?? savedVectorSimilarity)
          : savedVectorSimilarity;
        setSimilarityMetric(nextSimilarity);
        setEngine(savedEngine);
        // Always drive rows from the API response when the user switches resource —
        // passing currentFeatureMappings would bleed saved column values from a previously
        // configured resource into the new selection (including switching to "Create new").
        setTableRows(buildTableRows(result, []));
      } catch {
        if (runRef.current !== token) { return; }
        setLoadError(
          resourceArg
            ? intl.formatMessage(messages.loadResourceDetailsError)
            : intl.formatMessage(messages.loadNewResourceMappingsError)
        );
      } finally {
        if (runRef.current === token) { setLoadingMappings(false); }
      }
    };

    void fetchOnResourceChange();
  };

  const handleNewNameChange = (e: React.ChangeEvent<HTMLInputElement>): void => {
    const val = e.target.value;
    setNewResourceName(val);
    setResourceNameEdited(true);
    setNewNameError(validateNewName(val, availableResources));
  };

  const handleColumnChange = (featureName: string, column: string): void => {
    setTableRows((prev) =>
      prev.map((row) => (row.feature === featureName ? { ...row, column } : row))
    );
  };

  const handleRemoveSelected = (featureNames: string[]): void => {
    setTableRows((prev) =>
      prev.filter((row) => row.isMandatory || !featureNames.includes(row.feature))
    );
  };

  const handleAddFeature = (feature: string, column: string): void => {
    const isMandatory = availableFeatures[feature]?.mandatory_for_vector_db ?? false;
    const description = availableFeatures[feature]?.description ?? '';
    setTableRows((prev) => [
      ...prev,
      { feature, description, column, isMandatory },
    ]);
  };

  const handleSparseVectorChange = (_evt: React.ChangeEvent<HTMLInputElement>, { checked }: { checked: boolean }): void => {
    setSparseVectorEnabled(checked);
    setLoadError(null);

    const baseConfig = omitProviderConfigKeys(parsedProviderConfig, providerCfg.resourceSpecificKeys);
    const resourceArg = isCreateNew ? undefined : selectedResource;

    runRef.current += 1;
    const token = runRef.current;

    const fetchOnSparseToggle = async () => {
      setLoadingMappings(true);
      try {
        const result = await enrichFlowFeaturesForNode(
          pipelineFlow, nodeId, provider, baseConfig, resourceNameKey, resourceArg, checked
        );
        if (runRef.current !== token) { return; }
        setEnrichmentResult(result);
        setTableRows(buildTableRows(result, []));
      } catch {
        if (runRef.current !== token) { return; }
        setLoadError(intl.formatMessage(messages.reloadMappingsError));
      } finally {
        if (runRef.current === token) { setLoadingMappings(false); }
      }
    };

    void fetchOnSparseToggle();
  };

  const isUnsupported =
    !isCreateNew &&
    enrichmentResult?.is_docpipe_supported_resource?.supported === false;

  // newNameError only blocks save when we are in "Create new" mode — it holds
  // stale validation state when the user switches to an existing resource.
  const canSave =
    !loading &&
    !loadingMappings &&
    Boolean(effectiveResourceName) &&
    (!isCreateNew || !newNameError) &&
    !isUnsupported;

  const handleSave = (): void => {
    setSubmitted(true);
    if (!canSave) { return; }

    const mappings: FeatureMappingRow[] = tableRows
      .filter((row) => row.column.trim())
      .map((row) => ({
        feature_name: row.feature,
        mapped_column_name: row.column.trim(),
        is_mandatory: row.isMandatory,
      }));

    onSave({
      resourceName: effectiveResourceName,
      similarityMetric,
      engine,
      featureMappings: mappings,
      addSparseVector: sparseVectorEnabled,
    });
    onClose();
  };

  const dropdownItems = [CREATE_NEW, ...availableResources];
  const alreadyMapped = useMemo(() => tableRows.map((r) => r.feature), [tableRows]);

  const unsupportedSubtitle =
    resourceLabel === 'collection'
      ? intl.formatMessage(messages.unsupportedCollectionSubtitle, { resourceLabel })
      : intl.formatMessage(messages.unsupportedIndexSubtitle, { resourceLabel });

  return (
    <Tearsheet
      open={open}
      title={currentFeatureMappings.length > 0 ? intl.formatMessage(messages.editTitle) : intl.formatMessage(messages.addTitle)}
      description={intl.formatMessage(messages.description, { resourceLabel })}
      onClose={onClose}
      portalTarget={portalTarget}
      actions={[
        {
          label: intl.formatMessage(messages.save),
          onClick: handleSave,
          kind: 'primary' as const,
          disabled: !canSave,
        },
        {
          label: intl.formatMessage(messages.cancel),
          onClick: onClose,
          kind: 'secondary' as const,
        },
      ]}
    >
      <div className={styles.tearsheetForm}>
        {/* Full-body centered spinner while the enrichment API is in flight */}
        {loading && (
          <div className={styles.tearsheetLoadingCenter}>
            <Loading withOverlay={false} small={false} />
          </div>
        )}

        {!loading && (
          <>
            {/* API error — shown when enrichment fails; table still usable with saved data */}
            {loadError && (
              <InlineNotification
                kind="error"
                title={intl.formatMessage(messages.errorTitle)}
                subtitle={loadError}
                lowContrast
                hideCloseButton
              />
            )}

            {/* Read-only notice for existing resources */}
            {isConfigReadOnly && (
              <InlineNotification
                kind="info"
                title={intl.formatMessage(messages.readOnlyNotice, {
                  similarityLabel,
                  hasEngine: String(hasEngine),
                  resourceLabel,
                })}
                lowContrast
                hideCloseButton
              />
            )}

            {/* Controls row — ComboBox always present; remaining fields hidden when unsupported
                so the user can only select a different resource, not configure the broken one. */}
            <div className={styles.rowInputs}>
              <ComboBox
                id="resource-select"
                titleText={intl.formatMessage(messages.searchOrSelectResource, { resourceLabel })}
                placeholder={intl.formatMessage(messages.searchOrSelectResource, { resourceLabel })}
                items={dropdownItems}
                selectedItem={selectedResource}
                onChange={handleResourceChange}
              />

              {/* New-name / similarity / engine / dimension — hidden for unsupported resources */}
              {!isUnsupported && (
                <>
                  {/* New-name input — only shown when creating a new resource */}
                  {isCreateNew && (
                    <TextInput
                      id="new-resource-name"
                      labelText={intl.formatMessage(messages.enterNewResourceName, { resourceLabel })}
                      placeholder={intl.formatMessage(messages.newResourceNamePlaceholder, { resourceLabel })}
                      value={newResourceName}
                      invalid={(resourceNameEdited || submitted) && Boolean(newNameError)}
                      invalidText={newNameError ?? undefined}
                      onChange={handleNewNameChange}
                    />
                  )}

                  {/* Similarity/engine/dimension:
                      - loadingMappings → skeletons (API in flight after resource selection)
                      - isConfigReadOnly → disabled TextInputs (existing resource, values known)
                      - else            → editable Dropdowns (create new) */}
                  {loadingMappings && !isCreateNew ? (
                    <>
                      <TextInputSkeleton hideLabel />
                      {hasEngine && <TextInputSkeleton hideLabel />}
                    </>
                  ) : isConfigReadOnly ? (
                    <>
                      <TextInput
                        id="similarity-metric-readonly"
                        labelText={similarityLabel}
                        value={similarityMetricLabels[similarityMetric] ?? similarityMetric}
                        disabled
                      />
                      {hasEngine && (
                        <TextInput
                          id="engine-readonly"
                          labelText={intl.formatMessage(messages.engine)}
                          value={(engineOptionLabels[engine] ?? engine)}
                          disabled
                        />
                      )}
                      {storedMeta?.dimension_size !== null && storedMeta?.dimension_size !== undefined && (
                        <TextInput
                          id="dimension-size-readonly"
                          labelText={intl.formatMessage(messages.dimensionSize)}
                          value={String(storedMeta.dimension_size)}
                          disabled
                        />
                      )}
                    </>
                  ) : (
                    <>
                      <Dropdown
                        id="similarity-metric-select"
                        titleText={similarityLabel}
                        label={intl.formatMessage(messages.selectSimilarity, { similarityLabel: similarityLabel.toLowerCase() })}
                        items={vectorSimilarityOptions.map((v) => similarityMetricLabels[v] ?? v)}
                        selectedItem={similarityMetricLabels[similarityMetric] ?? similarityMetric}
                        onChange={({ selectedItem }: { selectedItem?: string | null }) => {
                          if (selectedItem) {
                            const value = vectorSimilarityOptions.find(
                              (v) => (similarityMetricLabels[v] ?? v) === selectedItem
                            );
                            if (value) { setSimilarityMetric(value); }
                          }
                        }}
                      />
                      {hasEngine && (
                        <Dropdown
                          id="engine-select"
                          titleText={intl.formatMessage(messages.engine)}
                          label={intl.formatMessage(messages.selectEngine)}
                          items={engineOptions.map((v) => engineOptionLabels[v] ?? v)}
                          selectedItem={engineOptionLabels[engine] ?? engine}
                          onChange={({ selectedItem }: { selectedItem?: string | null }) => {
                            if (selectedItem) {
                              const value = engineOptions.find(
                                (v) => (engineOptionLabels[v] ?? v) === selectedItem
                              );
                              if (value) { setEngine(value); }
                            }
                          }}
                        />
                      )}
                    </>
                  )}
                </>
              )}
            </div>

            {/* Milvus-only: sparse vector (BM25) toggle — hidden when unsupported (nothing to configure) */}
            {provider === VECTORDB_PROVIDERS.MILVUS && !isUnsupported && (
              <div className={styles.sparseVectorCheckbox}>
                <Checkbox
                  id="add-sparse-vector"
                  labelText={intl.formatMessage(messages.sparseVectorLabel)}
                  checked={sparseVectorEnabled}
                  onChange={handleSparseVectorChange}
                />
              </div>
            )}

            {/* Table area — skeleton while re-enriching after resource selection */}
            {loadingMappings ? (
              <DataTableSkeleton
                columnCount={3}
                rowCount={4}
                showHeader={false}
                showToolbar={false}
              />
            ) : isUnsupported ? (
              <div className={styles.emptyStateWrapper}>
                <ErrorEmptyState
                  title={intl.formatMessage(messages.unsupportedTitle, { resourceLabel })}
                  subtitle={unsupportedSubtitle}
                />
              </div>
            ) : (
              <>
                <VectorDBFeatureMappingTable
                  rows={tableRows}
                  onColumnChange={handleColumnChange}
                  onRemoveSelected={handleRemoveSelected}
                  onAddClick={() => { setIsAddModalOpen(true); }}
                />

                {/* Add feature mapping modal — inside Tearsheet so Carbon stacks it correctly */}
                <AddFeatureMappingModal
                  open={isAddModalOpen}
                  availableFeatures={availableFeatures}
                  alreadyMapped={alreadyMapped}
                  onClose={() => { setIsAddModalOpen(false); }}
                  onAdd={handleAddFeature}
                />
              </>
            )}
          </>
        )}
      </div>
    </Tearsheet>
  );
}
