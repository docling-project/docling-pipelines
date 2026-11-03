/**
 * @file VectorDB operator properties panel body.
 *
 * Renders the configuration UI for a `vectordb` operator node on the canvas.
 *
 * **Data flow**:
 * - `controller.getAppData()` — reads operator metadata, nodeId, and pipelineFlow
 * - `controller.getPropertyValue({ name })` — reads a saved node parameter
 * - `controller.updatePropertyValue({ name }, value)` — writes a node parameter
 *
 * **Feature mapping flow** (triggered when the user clicks "Add / Edit feature mappings"):
 * 1. Validate and parse the provider configuration textarea as JSON.
 * 2. Call `enrichFlowFeaturesForNode` with the live pipeline flow and provider configuration patch.
 * 3. Pass the returned `available_resources`, `feature_mappings`, and `available_features` to the tearsheet.
 *
 * **Mandatory flag resolution for the summary table**:
 * - Rows saved after the fix carry `is_mandatory` directly.
 * - Legacy rows (saved before `is_mandatory` existed) fall back to
 *   `nodeFeatureMap[nodeId].input_features[feature].mandatory_for_vector_db`
 *   because VectorDB produces no output features of its own — `mandatory_for_vector_db`
 *   is carried on the features flowing *into* the node (input_features).
 */

import React, { useMemo, useState } from 'react';
import { useIntl } from 'react-intl';
import { getRequiredParamValidator } from '@/utils/requiredParamValidation';
import { RequiredParamTooltip, VaultInput } from '@/components/common';
import {
  Accordion,
  AccordionItem,
  DefinitionTooltip,
  Dropdown,
  InlineNotification,
  TextArea,
  TextInput,
  Toggle,
} from '@carbon/react';
import { NoDataEmptyState } from '@carbon/ibm-products';
import type { FeatureMappingRow, NodeFeatureEntry, OperatorMetadata } from '@/types';
import { NodeOperator } from '@/constants/operators';
import { isValidJsonObject } from '@/utils/json';
import {
  DEFAULT_ENGINE_VALUES,
  VECTORDB_ATTRIBUTES as ATTR,
  VECTORDB_PROVIDERS,
  getProviderConfig,
} from './constants';
import { messages } from './VectorDB.messages';
import { clearProviderConfigResource, mergeProviderConfig } from './vectordb-save';
import { VectorDBSummaryTable } from './VectorDBSummaryTable';
import { VectorDBFeatureMappingTearsheet } from './VectorDBFeatureMappingTearsheet';
import common from '../../CommonPropertiesPanel.module.scss';
import styles from './VectorDB.module.scss';

interface VectorDBPanelBodyProps {
  controller: any;
}

interface VectorDBEmptyStateProps {
  onAddClick: () => void;
}

function VectorDBEmptyState({ onAddClick }: VectorDBEmptyStateProps): React.JSX.Element {
  const intl = useIntl();

  return (
    <div className={styles.emptyStateWrapper}>
      <NoDataEmptyState
        title={intl.formatMessage(messages.featureMappingTitle)}
        subtitle={intl.formatMessage(messages.featureMappingDesc)}
        size="sm"
        action={{
          kind: 'tertiary',
          text: intl.formatMessage(messages.addFeatureMappings),
          onClick: onAddClick,
        }}
      />
    </div>
  );
}

/* eslint-disable @typescript-eslint/no-unsafe-call, @typescript-eslint/no-unsafe-member-access */
export function VectorDBPanelBody({
  controller,
}: VectorDBPanelBodyProps): React.JSX.Element {
  const intl = useIntl();
  const [isTearsheetOpen, setIsTearsheetOpen] = useState(false);
  // Tracks whether the Advanced JSON textarea has been touched — gates the invalid
  // indicator so the textarea does not show red before the user types anything.
  const [advancedConfigDirty, setAdvancedConfigDirty] = useState(false);
  const [providerConfigError, setProviderConfigError] = useState<string | null>(null);
  // Holds the raw textarea value while the user is mid-edit and the JSON is not yet
  // valid. We never write an unparseable string to provider_config — that would corrupt
  // parsedSavedConfig and wipe managed keys (username, password, etc.) on the next render.
  const [advancedConfigDraft, setAdvancedConfigDraft] = useState<string | null>(null);
  // Tracks the user's chosen auth method. Seeded from saved config; updated when the
  // dropdown changes. Keeps the selector showing the chosen method even while the
  // relevant fields are still empty (before the user types a value).
  const [opensearchAuthMethod, setOpensearchAuthMethod] = useState<'none' | 'basic' | 'jwt' | 'aws'>('none');

  // ── Operator metadata ──
  const appData = controller?.getAppData?.() ?? {};
  const operatorMetadata = (appData.operatorMetadata ?? {}) as Record<string, OperatorMetadata>;
  const nodeAttributes = operatorMetadata[NodeOperator.VECTORDB]?.attributes ?? {};
  const currentNodeId: string = appData.nodeId ?? '';
  const pipelineFlow: object = appData.pipelineFlow ?? {};
  const nodeFeatureMap = (appData.nodeFeatureMap ?? {}) as Record<string, NodeFeatureEntry>;
  // VectorDB introduces no output features of its own — mandatory_for_vector_db lives
  // on the features flowing into this node (input_features), not output_features.
  const currentNodeInputFeatures = nodeFeatureMap[currentNodeId]?.input_features ?? {};
  // True while the background enrich API call is in-flight (Phase 1 of panel open).
  // Used to show a skeleton in the summary table instead of checkboxes with wrong state.
  const featuresLoading: boolean = appData.featuresLoading === true;

  // ── Extract providers dynamically from metadata ──
  const providerConfigAttr = nodeAttributes[ATTR.PROVIDER_CONFIG] as Record<string, unknown> | undefined;
  const providersMap = (providerConfigAttr?.providers ?? {}) as Record<string, unknown>;
  const providerOptions: string[] =
    Object.keys(providersMap).length > 0
      ? Object.keys(providersMap)
      : [VECTORDB_PROVIDERS.OPENSEARCH, VECTORDB_PROVIDERS.MILVUS];

  // ── Read saved provider + provider-specific config ──
  const defaultProvider =
    (nodeAttributes[ATTR.PROVIDER]?.default as string | undefined) ?? VECTORDB_PROVIDERS.OPENSEARCH;
  const provider =
    (controller?.getPropertyValue?.({ name: ATTR.PROVIDER }) as string | undefined) ?? defaultProvider;

  // All provider-specific differences (keys, labels, defaults) live here.
  const cfg = getProviderConfig(provider);

  // Extract similarity and engine options from operator metadata for the active provider.
  const activeProviderProps = (
    ((providersMap[provider] as Record<string, unknown> | undefined)?.['properties'] ?? {})
  ) as Record<string, { valid_values?: string[]; default?: string }>;

  const vectorSimilarityOptions: string[] =
    activeProviderProps[cfg.similarityKey]?.valid_values ?? cfg.defaultSimilarityValues;
  const vectorSimilarityDefault: string =
    activeProviderProps[cfg.similarityKey]?.default ?? cfg.defaultSimilarityValues[0] ?? '';

  const engineOptions: string[] =
    cfg.hasEngine ? (activeProviderProps[cfg.engineKey]?.valid_values ?? DEFAULT_ENGINE_VALUES) : [];
  const engineDefault: string =
    cfg.hasEngine ? (activeProviderProps[cfg.engineKey]?.default ?? 'faiss') : '';

  const rawProviderConfig = controller?.getPropertyValue?.({ name: ATTR.PROVIDER_CONFIG });
  const providerConfig =
    typeof rawProviderConfig === 'string'
      ? rawProviderConfig
      : typeof rawProviderConfig === 'object' && rawProviderConfig !== null
      ? JSON.stringify(rawProviderConfig, null, 2)
      : '';

  // Memoised so the same object reference is reused across renders when providerConfig
  // has not changed — avoids passing a new object to the tearsheet on every render.
  const parsedSavedConfig = useMemo<Record<string, unknown>>(() => {
    try { return JSON.parse(providerConfig) as Record<string, unknown>; }
    catch { return {}; }
  }, [providerConfig]);

  const savedVectorSimilarity =
    (parsedSavedConfig[cfg.similarityKey] as string | undefined) ?? vectorSimilarityDefault;
  const savedEngine =
    cfg.hasEngine ? ((parsedSavedConfig[cfg.engineKey] as string | undefined) ?? engineDefault) : '';

  // Resource name is stored inside provider_config under the provider-specific key.
  const savedResourceName =
    (parsedSavedConfig[cfg.resourceNameKey] as string | undefined) ?? '';

  // Read on every render — controller internal state changes but its reference
  // stays the same, so useMemo([controller]) never invalidates.
  const featureMappings =
    (controller?.getPropertyValue?.({ name: ATTR.FEATURE_MAPPINGS }) as FeatureMappingRow[] | undefined) ?? [];

  // add_sparse_vector is a top-level node parameter (not inside provider_config).
  // Default is false to match the backend default.
  const savedAddSparseVector =
    (controller?.getPropertyValue?.({ name: ATTR.ADD_SPARSE_VECTOR }) as boolean | undefined) ?? false;

  // ── Authentication & Connection Fields Helper ──
  // Write a single key into provider_config. Pass `extra` to stamp additional keys
  // atomically in the same write (e.g. auth_type alongside a Milvus credential field).
  // Clearing a key: pass '' | null | undefined as value.
  const updateProviderConfigField = (
    key: string,
    value: unknown,
    extra?: Record<string, unknown>
  ): void => {
    const nextConfig = { ...parsedSavedConfig, ...extra };
    if (value === '' || value === null || value === undefined) {
      delete nextConfig[key];
    } else {
      nextConfig[key] = value;
    }
    controller?.updatePropertyValue?.({ name: ATTR.PROVIDER_CONFIG }, nextConfig);
  };

  // Stamp auth_type alongside any Milvus credential field so the backend always
  // knows which auth mode is active, even if the dropdown was never touched.
  const updateMilvusAuthField = (key: string, value: unknown): void => {
    updateProviderConfigField(key, value, { auth_type: milvusAuthType });
  };

  // Connection & Settings fields for OpenSearch
  const opensearchHost = (parsedSavedConfig.host as string | undefined) ?? 'localhost';
  const opensearchPort = parsedSavedConfig.port !== undefined && parsedSavedConfig.port !== null ? String(parsedSavedConfig.port) : '9200';
  const opensearchUseSsl = (parsedSavedConfig.use_ssl as boolean | undefined) ?? false;
  const opensearchVerifyCerts = (parsedSavedConfig.verify_certs as boolean | undefined) ?? false;

  // Auth fields for OpenSearch
  const opensearchUsername = (parsedSavedConfig.username as string | undefined) ?? '';
  const opensearchPassword = (parsedSavedConfig.password as string | undefined) ?? '';
  const opensearchJwtToken = (parsedSavedConfig.jwt_token as string | undefined) ?? '';
  const opensearchAwsAuth = (parsedSavedConfig.aws_auth as boolean | undefined) ?? false;
  const opensearchAwsRegion = (parsedSavedConfig.aws_region as string | undefined) ?? '';

  // Derive the active auth method from saved config so the selector stays in sync
  // when the panel re-mounts or when provider_config is loaded from a saved flow.
  const derivedOpensearchAuthMethod: 'none' | 'basic' | 'jwt' | 'aws' =
    opensearchAwsAuth ? 'aws'
    : opensearchJwtToken ? 'jwt'
    : (opensearchUsername || opensearchPassword) ? 'basic'
    : 'none';

  // Connection & Settings fields for Milvus
  const milvusHost = (parsedSavedConfig.host as string | undefined) ?? 'localhost';
  const milvusPort = parsedSavedConfig.port !== undefined && parsedSavedConfig.port !== null ? String(parsedSavedConfig.port) : '19530';
  const milvusDatabase = (parsedSavedConfig.database as string | undefined) ?? 'default';
  const milvusSecure = (parsedSavedConfig.secure as boolean | undefined) ?? false;

  // Auth fields for Milvus
  const milvusAuthType = (parsedSavedConfig.auth_type as string | undefined) ?? 'standalone';
  const milvusUsername = (parsedSavedConfig.username as string | undefined) ?? '';
  const milvusPassword = (parsedSavedConfig.password as string | undefined) ?? '';
  const milvusToken = (parsedSavedConfig.token as string | undefined) ?? '';
  const milvusUri = (parsedSavedConfig.uri as string | undefined) ?? '';

  // Keys managed by the structured UI fields (connection, auth, settings accordions)
  // and by the feature mapping tearsheet (resource name, similarity, engine, algorithm, index type).
  // All of these are excluded from the advanced JSON textarea so the user never sees duplicates.
  // resourceSpecificKeys (index_name/collection_name, space_type/metric_type, engine)
  // are included — they are managed by the tearsheet.
  // algorithm / index_type are intentionally NOT included here: they are no longer
  // controlled by a dedicated UI input, so they should surface in the advanced textarea
  // if the user set them previously, and remain editable via JSON.
  const tearsheetManagedKeys = cfg.resourceSpecificKeys.filter(
    (k) => k !== 'algorithm' && k !== 'index_type'
  );
  const OPENSEARCH_MANAGED_KEYS = new Set([
    'host', 'port', 'use_ssl', 'verify_certs',
    'username', 'password', 'jwt_token', 'aws_auth', 'aws_region',
    ...tearsheetManagedKeys,
  ]);
  const MILVUS_MANAGED_KEYS = new Set([
    'host', 'port', 'database', 'secure',
    'auth_type', 'username', 'password', 'token', 'uri',
    ...tearsheetManagedKeys,
  ]);
  const managedKeys = provider === VECTORDB_PROVIDERS.OPENSEARCH ? OPENSEARCH_MANAGED_KEYS : MILVUS_MANAGED_KEYS;

  // Advanced config: only the keys NOT covered by a structured input field.
  const advancedConfig = useMemo(() => {
    const filtered = Object.fromEntries(
      Object.entries(parsedSavedConfig).filter(([k]) => !managedKeys.has(k))
    );
    return Object.keys(filtered).length > 0 ? JSON.stringify(filtered, null, 2) : '';
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providerConfig, provider]);

  // Merge display-side defaults into parsedSavedConfig for the enrichment API.
  // Untouched fields (host, port, use_ssl, etc.) are absent from parsedSavedConfig
  // but the backend still needs them — explicit saves always win.
  const resolvedProviderConfig = useMemo<Record<string, unknown>>(() => {
    if (provider === VECTORDB_PROVIDERS.OPENSEARCH) {
      const defaults: Record<string, unknown> = {
        host: opensearchHost,
        port: Number(opensearchPort),
        use_ssl: opensearchUseSsl,
      };
      if (opensearchUseSsl) {
        defaults.verify_certs = opensearchVerifyCerts;
      }
      // parsedSavedConfig spreads last so explicit saves always override defaults.
      return { ...defaults, ...parsedSavedConfig };
    }
    if (provider === VECTORDB_PROVIDERS.MILVUS) {
      const defaults: Record<string, unknown> = {
        auth_type: milvusAuthType,
        database: milvusDatabase,
        secure: milvusSecure,
      };
      if (milvusAuthType !== 'uri') {
        defaults.host = milvusHost;
        defaults.port = Number(milvusPort);
      }
      return { ...defaults, ...parsedSavedConfig };
    }
    return parsedSavedConfig;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider, parsedSavedConfig]);

  // ── Required param validation ─────────────────────────────────────────────
  const validate = getRequiredParamValidator(nodeAttributes);
  const providerValidation = validate(ATTR.PROVIDER, provider);

  // Advanced textarea is invalid when:
  // - the user has a mid-edit draft that is not yet valid JSON (advancedConfigDraft !== null), OR
  // - the persisted value is not valid JSON (legacy data edge case).
  // Structured fields (Connection / Auth accordions) have their own independent validity — they
  // are always valid as long as they are well-typed inputs and never share this flag.
  const isAdvancedConfigValid = !advancedConfigDirty || (advancedConfigDraft === null && (advancedConfig === '' || isValidJsonObject(advancedConfig)));

  const handleAdvancedConfigChange = (e: React.ChangeEvent<HTMLTextAreaElement>): void => {
    setAdvancedConfigDirty(true);
    setProviderConfigError(null);
    const raw = e.target.value;
    const trimmed = raw.trim();

    if (trimmed === '') {
      // User cleared the textarea — drop all non-managed keys, keep managed ones.
      setAdvancedConfigDraft(null);
      const managedOnly = Object.fromEntries(
        Object.entries(parsedSavedConfig).filter(([k]) => managedKeys.has(k))
      );
      controller?.updatePropertyValue?.({ name: ATTR.PROVIDER_CONFIG }, managedOnly);
      return;
    }

    try {
      const parsed = JSON.parse(trimmed) as Record<string, unknown>;
      // Valid JSON — persist immediately. Managed keys (username, password, etc.)
      // always win so the structured fields are never overwritten by the textarea.
      setAdvancedConfigDraft(null);
      const merged = {
        ...parsed,
        ...Object.fromEntries(Object.entries(parsedSavedConfig).filter(([k]) => managedKeys.has(k))),
      };
      controller?.updatePropertyValue?.({ name: ATTR.PROVIDER_CONFIG }, merged);
    } catch {
      // Invalid JSON mid-edit — keep raw text in local draft state only.
      // Never write an unparseable string to provider_config: doing so would corrupt
      // parsedSavedConfig on the next render and wipe managed keys like username/password.
      setAdvancedConfigDraft(raw);
    }
  };

  // ── Open tearsheet: validate config then open immediately ──
  // The tearsheet itself owns the API call and loading state.
  const handleOpenTearsheet = (): void => {
    if (advancedConfigDraft !== null || (advancedConfig !== '' && !isAdvancedConfigValid)) {
      setProviderConfigError(intl.formatMessage(messages.advancedConfigInvalidError));
      return;
    }
    setProviderConfigError(null);
    setIsTearsheetOpen(true);
  };

  const handleSaveFeatureMappings = (data: {
    resourceName: string;
    similarityMetric: string;
    engine: string;
    featureMappings: FeatureMappingRow[];
    addSparseVector: boolean;
  }): void => {
    const configPatch: Record<string, unknown> = {
      [cfg.resourceNameKey]: data.resourceName,
      [cfg.similarityKey]: data.similarityMetric,
    };
    if (cfg.hasEngine) {
      configPatch[cfg.engineKey] = data.engine;
    }
    const mergedConfig = mergeProviderConfig(providerConfig, configPatch);
    controller?.updatePropertyValue?.({ name: ATTR.PROVIDER_CONFIG }, mergedConfig);
    controller?.updatePropertyValue?.({ name: ATTR.FEATURE_MAPPINGS }, data.featureMappings);
    // Persist add_sparse_vector as a top-level node parameter (Milvus-only).
    // For other providers it is saved as false so a provider switch produces
    // a clean state — the backend treats absent/false identically.
    controller?.updatePropertyValue?.({ name: ATTR.ADD_SPARSE_VECTOR }, data.addSparseVector);
  };

  const hasMappings = featureMappings.length > 0 && Boolean(savedResourceName);

  // is_mandatory is persisted from the tearsheet (new saves) so mandatory rows are
  // correctly disabled in the summary table without needing a live enrichment call.
  // For legacy rows saved before is_mandatory existed, fall back to
  // input_features[feature].mandatory_for_vector_db — VectorDB consumes features
  // from upstream nodes, so mandatory flags live on input_features, not output_features.
  const summaryRows = featureMappings.map(({ feature_name, mapped_column_name, is_mandatory }) => ({
    feature: feature_name,
    column: mapped_column_name,
    isMandatory: is_mandatory ?? currentNodeInputFeatures[feature_name]?.mandatory_for_vector_db ?? false,
  }));

  const handleSummaryRemoveSelected = (featureNames: string[]): void => {
    const toRemove = new Set(featureNames);
    const updated = featureMappings.filter((m) => !toRemove.has(m.feature_name));
    controller?.updatePropertyValue?.({ name: ATTR.FEATURE_MAPPINGS }, updated);
    // hasMappings requires both featureMappings.length > 0 AND a saved resource name.
    // If the user batch-removes all rows, clear index_name from provider_config too
    // so the panel reverts to the empty state instead of showing a blank summary card.
    if (updated.length === 0) {
      controller?.updatePropertyValue?.(
        { name: ATTR.PROVIDER_CONFIG },
        clearProviderConfigResource(parsedSavedConfig, cfg.resourceNameKey)
      );
    }
  };

  return (
    <div className={common.commonPropertiesPanelBody}>
      {/* ── Provider Dropdown ── */}
      <div className={common.formField}>
        <div className={common.labelWithTooltip}>
          <RequiredParamTooltip
            paramId={ATTR.PROVIDER}
            nodeAttributes={nodeAttributes}
            definition={nodeAttributes[ATTR.PROVIDER]?.description ?? 'Vector database backend provider'}
          >
            {intl.formatMessage(messages.provider)}
          </RequiredParamTooltip>
        </div>
        <Dropdown
          id="vectordb-provider-dropdown"
          label={intl.formatMessage(messages.selectProvider)}
          titleText={intl.formatMessage(messages.provider)}
          hideLabel
          items={providerOptions}
          selectedItem={provider || null}
          onChange={({ selectedItem }: { selectedItem?: string | null }) => {
            if (selectedItem) {
              controller?.updatePropertyValue?.({ name: ATTR.PROVIDER }, selectedItem);
              // Wipe provider_config entirely on provider switch — connection params,
              // auth fields, and resource keys are all provider-specific and invalid
              // for a different backend. Feature mappings are also stale.
              controller?.updatePropertyValue?.({ name: ATTR.PROVIDER_CONFIG }, {});
              controller?.updatePropertyValue?.({ name: ATTR.FEATURE_MAPPINGS }, []);
              setProviderConfigError(null);
              setAdvancedConfigDraft(null);
              setAdvancedConfigDirty(false);
            }
          }}
          invalid={providerValidation.isInvalid}
          invalidText={providerValidation.errorMessage}
        />
      </div>

      {/* ── Provider Configuration Accordion ── */}
      <div className={common.formField}>
        <Accordion className={styles.providerAccordion}>
          {/* Connection Settings Accordion Item */}
          <AccordionItem title={intl.formatMessage(messages.connectionTitle)} open>
            {provider === VECTORDB_PROVIDERS.OPENSEARCH && (
              <div className={common.accordionContent}>
                <div className={common.formField}>
                  <TextInput
                    id="opensearch-host"
                    labelText={intl.formatMessage(messages.host)}
                    value={opensearchHost}
                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                      updateProviderConfigField('host', e.target.value);
                    }}
                    placeholder="localhost"
                  />
                </div>
                <div className={common.formField}>
                  <TextInput
                    id="opensearch-port"
                    labelText={intl.formatMessage(messages.port)}
                    value={opensearchPort}
                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                      const num = parseInt(e.target.value, 10);
                      updateProviderConfigField('port', Number.isNaN(num) ? e.target.value : num);
                    }}
                    placeholder="9200"
                  />
                </div>
                <div className={common.formField}>
                  <Toggle
                    id="opensearch-use-ssl"
                    labelText={intl.formatMessage(messages.useSsl)}
                    labelA={intl.formatMessage(messages.off)}
                    labelB={intl.formatMessage(messages.on)}
                    toggled={opensearchUseSsl}
                    onToggle={(checked: boolean) => {
                      updateProviderConfigField('use_ssl', checked);
                    }}
                  />
                </div>
                {opensearchUseSsl && (
                  <div className={common.formField}>
                    <Toggle
                      id="opensearch-verify-certs"
                      labelText={intl.formatMessage(messages.verifySslCerts)}
                      labelA={intl.formatMessage(messages.off)}
                      labelB={intl.formatMessage(messages.on)}
                      toggled={opensearchVerifyCerts}
                      onToggle={(checked: boolean) => {
                        updateProviderConfigField('verify_certs', checked);
                      }}
                    />
                  </div>
                )}
              </div>
            )}

            {provider === VECTORDB_PROVIDERS.MILVUS && (
              <div className={common.accordionContent}>
                {milvusAuthType !== 'uri' && (
                  <>
                    <div className={common.formField}>
                      <TextInput
                        id="milvus-host"
                        labelText={intl.formatMessage(messages.host)}
                        value={milvusHost}
                        onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                          updateProviderConfigField('host', e.target.value);
                        }}
                        placeholder="localhost"
                      />
                    </div>
                    <div className={common.formField}>
                      <TextInput
                        id="milvus-port"
                        labelText={intl.formatMessage(messages.port)}
                        value={milvusPort}
                        onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                          const num = parseInt(e.target.value, 10);
                          updateProviderConfigField('port', Number.isNaN(num) ? e.target.value : num);
                        }}
                        placeholder="19530"
                      />
                    </div>
                  </>
                )}
                <div className={common.formField}>
                  <TextInput
                    id="milvus-database"
                    labelText={intl.formatMessage(messages.databaseName)}
                    value={milvusDatabase}
                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                      updateProviderConfigField('database', e.target.value);
                    }}
                    placeholder="default"
                  />
                </div>
                {milvusAuthType !== 'uri' && (
                  <div className={common.formField}>
                    <Toggle
                      id="milvus-secure"
                      labelText={intl.formatMessage(messages.secureTls)}
                      labelA={intl.formatMessage(messages.off)}
                      labelB={intl.formatMessage(messages.on)}
                      toggled={milvusSecure}
                      onToggle={(checked: boolean) => {
                        updateProviderConfigField('secure', checked);
                      }}
                    />
                  </div>
                )}
              </div>
            )}
          </AccordionItem>

          {/* Authentication Accordion Item */}
          <AccordionItem title={intl.formatMessage(messages.authenticationTitle)} open>
            {provider === VECTORDB_PROVIDERS.OPENSEARCH && (
              <div className={common.accordionContent}>
                {/* Auth method selector — maps to the three mutually exclusive backend auth paths */}
                <div className={common.formField}>
                  <Dropdown
                    id="opensearch-auth-method"
                    titleText={intl.formatMessage(messages.authMethod)}
                    label={intl.formatMessage(messages.selectMethod)}
                    items={['none', 'basic', 'jwt', 'aws']}
                    itemToString={(item: string | null) => {
                      if (item === 'none') { return intl.formatMessage(messages.authNone); }
                      if (item === 'basic') { return intl.formatMessage(messages.authBasic); }
                      if (item === 'jwt') { return intl.formatMessage(messages.authJwt); }
                      if (item === 'aws') { return intl.formatMessage(messages.authAws); }
                      return item ?? '';
                    }}
                    selectedItem={derivedOpensearchAuthMethod !== 'none' ? derivedOpensearchAuthMethod : opensearchAuthMethod}
                    onChange={({ selectedItem }: { selectedItem?: string | null }) => {
                      const next = (selectedItem ?? 'none') as 'none' | 'basic' | 'jwt' | 'aws';
                      setOpensearchAuthMethod(next);
                      // Clear all auth fields from the previous method so the backend
                      // never sees more than one auth method at a time.
                      const cleared: Record<string, unknown> = { ...parsedSavedConfig };
                      delete cleared.username;
                      delete cleared.password;
                      delete cleared.jwt_token;
                      delete cleared.aws_auth;
                      delete cleared.aws_region;
                      controller?.updatePropertyValue?.({ name: ATTR.PROVIDER_CONFIG }, cleared);
                    }}
                  />
                </div>

                {/* Basic auth fields */}
                {(derivedOpensearchAuthMethod === 'basic' || (derivedOpensearchAuthMethod === 'none' && opensearchAuthMethod === 'basic')) && (
                  <>
                    <div className={common.formField}>
                      <TextInput
                        id="opensearch-username"
                        labelText={intl.formatMessage(messages.username)}
                        value={opensearchUsername}
                        onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                          updateProviderConfigField('username', e.target.value);
                        }}
                        placeholder="admin"
                      />
                    </div>
                    <div className={common.formField}>
                      <VaultInput
                        id="opensearch-password"
                        labelText={intl.formatMessage(messages.password)}
                        value={opensearchPassword}
                        onChange={(v: string) => {
                          updateProviderConfigField('password', v);
                        }}
                      />
                    </div>
                  </>
                )}

                {/* JWT token field */}
                {(derivedOpensearchAuthMethod === 'jwt' || (derivedOpensearchAuthMethod === 'none' && opensearchAuthMethod === 'jwt')) && (
                  <div className={common.formField}>
                    <VaultInput
                      id="opensearch-jwt-token"
                      labelText={intl.formatMessage(messages.jwtToken)}
                      value={opensearchJwtToken}
                      onChange={(v: string) => {
                        updateProviderConfigField('jwt_token', v);
                      }}
                    />
                  </div>
                )}

                {/* AWS IAM fields */}
                {(derivedOpensearchAuthMethod === 'aws' || (derivedOpensearchAuthMethod === 'none' && opensearchAuthMethod === 'aws')) && (
                  <div className={common.formField}>
                    <TextInput
                      id="opensearch-aws-region"
                      labelText={intl.formatMessage(messages.awsRegion)}
                      value={opensearchAwsRegion}
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                        updateProviderConfigField('aws_region', e.target.value);
                        // aws_auth flag must be true when AWS IAM is the chosen method
                        updateProviderConfigField('aws_auth', true);
                      }}
                      placeholder="us-east-1"
                    />
                  </div>
                )}
              </div>
            )}

            {provider === VECTORDB_PROVIDERS.MILVUS && (
              <div className={common.accordionContent}>
                <div className={common.formField}>
                  <Dropdown
                    id="milvus-auth-type"
                    label={intl.formatMessage(messages.selectAuthType)}
                    titleText={intl.formatMessage(messages.authType)}
                    items={['standalone', 'grpc', 'uri', 'token']}
                    selectedItem={milvusAuthType}
                    onChange={({ selectedItem }: { selectedItem?: string | null }) => {
                      if (selectedItem) {
                        // Clear all auth-type-specific fields from the previous selection
                        // and write the new auth_type atomically so the backend never sees
                        // a mix of fields from different auth types.
                        const cleared: Record<string, unknown> = { ...parsedSavedConfig };
                        delete cleared.username;
                        delete cleared.password;
                        delete cleared.token;
                        delete cleared.uri;
                        cleared.auth_type = selectedItem;
                        controller?.updatePropertyValue?.({ name: ATTR.PROVIDER_CONFIG }, cleared);
                      }
                    }}
                  />
                </div>
                {(milvusAuthType === 'standalone' || milvusAuthType === 'grpc' || milvusAuthType === 'token') && (
                  <div className={common.formField}>
                    <TextInput
                      id="milvus-username"
                      labelText={intl.formatMessage(messages.username)}
                      value={milvusUsername}
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                        updateMilvusAuthField('username', e.target.value);
                      }}
                    />
                  </div>
                )}
                {(milvusAuthType === 'standalone' || milvusAuthType === 'grpc') && (
                  <div className={common.formField}>
                    <VaultInput
                      id="milvus-password"
                      labelText={intl.formatMessage(messages.password)}
                      labelComponent={
                        <div className={common.labelWithTooltip}>
                          <DefinitionTooltip
                            definition={intl.formatMessage(messages.passwordTooltip)}
                            openOnHover
                            align="right"
                          >
                            {intl.formatMessage(messages.password)}
                          </DefinitionTooltip>
                        </div>
                      }
                      value={milvusPassword}
                      onChange={(v: string) => {
                        updateMilvusAuthField('password', v);
                      }}
                    />
                  </div>
                )}
                {milvusAuthType === 'token' && (
                  <div className={common.formField}>
                    <VaultInput
                      id="milvus-token"
                      labelText={intl.formatMessage(messages.token)}
                      labelComponent={
                        <div className={common.labelWithTooltip}>
                          <DefinitionTooltip
                            definition={intl.formatMessage(messages.tokenTooltip)}
                            openOnHover
                            align="right"
                          >
                            {intl.formatMessage(messages.token)}
                          </DefinitionTooltip>
                        </div>
                      }
                      value={milvusToken}
                      onChange={(v: string) => {
                        updateMilvusAuthField('token', v);
                      }}
                    />
                  </div>
                )}
                {milvusAuthType === 'uri' && (
                  <div className={common.formField}>
                    <TextInput
                      id="milvus-uri"
                      labelText={intl.formatMessage(messages.uri)}
                      value={milvusUri}
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                        updateMilvusAuthField('uri', e.target.value);
                      }}
                      placeholder="https://xxx.zillizcloud.com"
                    />
                  </div>
                )}
              </div>
            )}
          </AccordionItem>

          {/* Advanced JSON Accordion Item */}
          <AccordionItem title={intl.formatMessage(messages.advancedTitle)}>
            <div className={common.accordionContent}>
              <div className={common.formField}>
                <TextArea
                  id="vectordb-provider-config-textarea"
                  labelText={intl.formatMessage(messages.additionalConfig)}
                  placeholder="{}"
                  helperText={intl.formatMessage(messages.additionalConfigHelperText)}
                  rows={5}
                  value={advancedConfigDraft ?? advancedConfig}
                  onChange={handleAdvancedConfigChange}
                  invalid={!isAdvancedConfigValid}
                  invalidText={intl.formatMessage(messages.additionalConfigInvalid)}
                />
              </div>
            </div>
          </AccordionItem>
        </Accordion>
      </div>

      {/* ── Provider configuration validation error ── */}
      {providerConfigError && (
        <InlineNotification
          kind="error"
          title={intl.formatMessage(messages.errorTitle)}
          subtitle={providerConfigError}
          lowContrast
          hideCloseButton
        />
      )}

      {hasMappings && (
        /* ── Summary card: shown after save ── */
        <VectorDBSummaryTable
          savedResourceName={savedResourceName}
          rows={summaryRows}
          onRemove={handleSummaryRemoveSelected}
          onEdit={handleOpenTearsheet}
          loading={featuresLoading}
        />
      )}

      {!hasMappings && (
        /* ── Empty state: shown before first save ── */
        <VectorDBEmptyState onAddClick={handleOpenTearsheet} />
      )}

      {/* ── Feature Mapping Tearsheet ── */}
      {/* Always mounted so Carbon's close animation plays; state resets inside on open. */}
      <VectorDBFeatureMappingTearsheet
        open={isTearsheetOpen}
        onClose={() => { setIsTearsheetOpen(false); }}
        onSave={handleSaveFeatureMappings}
        providerCfg={cfg}
        provider={provider}
        savedResourceName={savedResourceName}
        currentFeatureMappings={featureMappings}
        pipelineFlow={pipelineFlow}
        nodeId={currentNodeId}
        parsedProviderConfig={resolvedProviderConfig}
        vectorSimilarityOptions={vectorSimilarityOptions}
        savedVectorSimilarity={savedVectorSimilarity}
        engineOptions={engineOptions}
        savedEngine={savedEngine}
        addSparseVector={savedAddSparseVector}
      />
    </div>
  );
}
