/**
 * @file StorageOutput operator properties panel body.
 *
 * **provider_config** renders structured, per-provider fields.
 * Switching `provider` resets `provider_config` so stale fields from the previous
 * provider are never persisted.
 */

import React, { useCallback } from 'react';
import { useIntl } from 'react-intl';
import {
  Accordion,
  AccordionItem,
  Dropdown,
  NumberInput,
  TextInput,
  Toggle,
} from '@carbon/react';
import type { OperatorFeature, OperatorMetadata } from '@/types';
import { NodeOperator } from '@/constants/operators';
import { getRequiredParamValidator } from '@/utils/requiredParamValidation';
import { RequiredParamTooltip, VaultInput } from '@/components/common';
import { isVaultReference } from '@/utils/vault';
import { isValidJsonObject, toJsonString } from '@/utils/json';
import { JsonTextArea } from '@/components/common/JsonTextArea/JsonTextArea';
import { TagInput } from '@/components/common/TagInput/TagInput';
import {
  BOX_CONFIG_KEY,
  DESTINATION_CONFIG_KEY,
  FILESYSTEM_CONFIG_KEY,
  GOOGLE_DRIVE_CONFIG_KEY,
  OUTPUT_FORMAT_KEY,
  OUTPUT_STRUCTURE_KEY,
  S3_CONFIG_KEY,
  S3_PROVIDERS,
  SHAREPOINT_CONFIG_KEY,
  SHAREPOINT_PROVIDERS,
  STORAGE_OUTPUT_ATTRIBUTE as ATTR,
  type ContentFormat,
  type OutputStructureType,
  type WriteMode,
} from './constants';
import { messages } from './StorageOutput.messages';
import common from '../../CommonPropertiesPanel.module.scss';
import { useProviderConfigDefaults } from '@/hooks/useProviderConfigDefaults';

interface StorageOutputPanelBodyProps {
  controller: any;
}

/* eslint-disable @typescript-eslint/no-unsafe-call */
export function StorageOutputPanelBody({
  controller,
}: StorageOutputPanelBodyProps): React.JSX.Element {
  const intl = useIntl();

  const writeModeLabels: Record<WriteMode, string> = {
    processed_content: intl.formatMessage(messages.modeProcessedContent),
    refetch_original: intl.formatMessage(messages.modeRefetchOriginal),
    comprehensive_export: intl.formatMessage(messages.modeComprehensiveExport),
  };

  const contentFormatLabels: Record<ContentFormat, string> = {
    md: intl.formatMessage(messages.formatMd),
    txt: intl.formatMessage(messages.formatTxt),
    json: intl.formatMessage(messages.formatJson),
  };

  const structureTypeLabels: Record<OutputStructureType, string> = {
    flat: intl.formatMessage(messages.structureFlat),
    hierarchical: intl.formatMessage(messages.structureHierarchical),
  };

  // ── Operator metadata ─────────────────────────────────────────────────────
  const operatorMetadata = (controller?.getAppData?.()?.operatorMetadata ?? {}) as Record<string, OperatorMetadata>;
  const nodeAttributes: Record<string, OperatorFeature> = operatorMetadata[NodeOperator.STORAGE_OUTPUT]?.attributes ?? {};

  // destination_config.properties.*
  const destAttrs = (nodeAttributes[ATTR.DESTINATION_CONFIG] as Record<string, unknown> | undefined)
    ?.properties as Record<string, OperatorFeature> | undefined ?? {};

  // destination_config.properties.provider_config.providers.<provider>.properties.*
  const providerSchemas = (destAttrs[DESTINATION_CONFIG_KEY.PROVIDER_CONFIG] as Record<string, unknown> | undefined)
    ?.providers as Record<string, { properties?: Record<string, OperatorFeature> }> | undefined ?? {};

  // output_format.properties.*
  const outputFormatAttrs = (nodeAttributes[ATTR.OUTPUT_FORMAT] as Record<string, unknown> | undefined)
    ?.properties as Record<string, OperatorFeature> | undefined ?? {};

  // output_structure.properties.*
  const outputStructureAttrs = (nodeAttributes[ATTR.OUTPUT_STRUCTURE] as Record<string, unknown> | undefined)
    ?.properties as Record<string, OperatorFeature> | undefined ?? {};

  // ── Read saved top-level values ───────────────────────────────────────────

  const mode = (controller?.getPropertyValue?.({ name: ATTR.MODE }) as WriteMode | undefined)
    ?? (nodeAttributes[ATTR.MODE]?.default as WriteMode | undefined);

  const modeItems: WriteMode[] = (nodeAttributes[ATTR.MODE] as Record<string, unknown> | undefined)
    ?.valid_values as WriteMode[] ?? ['processed_content', 'refetch_original', 'comprehensive_export'];

  const destinationConfig = (controller?.getPropertyValue?.({ name: ATTR.DESTINATION_CONFIG }) as Record<string, unknown> | undefined) ?? {};

  const provider = (destinationConfig[DESTINATION_CONFIG_KEY.PROVIDER] as string | undefined) ?? '';

  const providerItems: string[] = (destAttrs[DESTINATION_CONFIG_KEY.PROVIDER] as Record<string, unknown> | undefined)
    ?.valid_values as string[] ?? [];

  const providerConfig = (destinationConfig[DESTINATION_CONFIG_KEY.PROVIDER_CONFIG] as Record<string, unknown> | undefined) ?? {};
  const credentialsRaw = destinationConfig[DESTINATION_CONFIG_KEY.CREDENTIALS];
  const credentialsStored = (credentialsRaw !== undefined && credentialsRaw !== null)
    ? (typeof credentialsRaw === 'string' ? credentialsRaw : toJsonString(credentialsRaw))
    : '';

  // ── Read saved output_format values ──────────────────────────────────────

  const outputFormat = (controller?.getPropertyValue?.({ name: ATTR.OUTPUT_FORMAT }) as Record<string, unknown> | undefined) ?? {};

  const contentFormat = (outputFormat[OUTPUT_FORMAT_KEY.CONTENT_FORMAT] as ContentFormat | undefined)
    ?? (outputFormatAttrs[OUTPUT_FORMAT_KEY.CONTENT_FORMAT]?.default as ContentFormat | undefined)
    ?? 'md';

  const contentFormatItems: ContentFormat[] = (outputFormatAttrs[OUTPUT_FORMAT_KEY.CONTENT_FORMAT] as Record<string, unknown> | undefined)
    ?.valid_values as ContentFormat[] ?? ['md', 'txt', 'json'];

  const includeMetadataSidecar = (outputFormat[OUTPUT_FORMAT_KEY.INCLUDE_METADATA_SIDECAR] as boolean | undefined)
    ?? (outputFormatAttrs[OUTPUT_FORMAT_KEY.INCLUDE_METADATA_SIDECAR]?.default as boolean | undefined)
    ?? false;

  // ── Read saved output_structure values ────────────────────────────────────

  const outputStructure = (controller?.getPropertyValue?.({ name: ATTR.OUTPUT_STRUCTURE }) as Record<string, unknown> | undefined) ?? {};

  const structureType = (outputStructure[OUTPUT_STRUCTURE_KEY.TYPE] as OutputStructureType | undefined)
    ?? (outputStructureAttrs[OUTPUT_STRUCTURE_KEY.TYPE]?.default as OutputStructureType | undefined)
    ?? 'flat';

  const structureTypeItems: OutputStructureType[] = (outputStructureAttrs[OUTPUT_STRUCTURE_KEY.TYPE] as Record<string, unknown> | undefined)
    ?.valid_values as OutputStructureType[] ?? ['flat', 'hierarchical'];

  const pathTemplate = (outputStructure[OUTPUT_STRUCTURE_KEY.PATH_TEMPLATE] as string | undefined) ?? '';

  const overwriteExisting = (outputStructure[OUTPUT_STRUCTURE_KEY.OVERWRITE_EXISTING] as boolean | undefined)
    ?? (outputStructureAttrs[OUTPUT_STRUCTURE_KEY.OVERWRITE_EXISTING]?.default as boolean | undefined)
    ?? true;

  // ── Provider config field helpers ─────────────────────────────────────────

  /** Read a string field from provider_config, falling back to schema default or ''. */
  const pcStr = (key: string): string => {
    const val = providerConfig[key];
    if (typeof val === 'string') { return val; }
    const schema = providerSchemas[provider]?.properties?.[key];
    const def = (schema as Record<string, unknown> | undefined)?.default;
    return typeof def === 'string' ? def : '';
  };

  /** Read a boolean field from provider_config, falling back to schema default. */
  const pcBool = (key: string, fallback = true): boolean => {
    const val = providerConfig[key];
    if (typeof val === 'boolean') { return val; }
    const schema = providerSchemas[provider]?.properties?.[key];
    const def = (schema as Record<string, unknown> | undefined)?.default;
    return typeof def === 'boolean' ? def : fallback;
  };

  /** Read a number field from provider_config, falling back to schema default. */
  const pcNum = (key: string, fallback: number): number => {
    const val = providerConfig[key];
    if (typeof val === 'number') { return val; }
    const schema = providerSchemas[provider]?.properties?.[key];
    const def = (schema as Record<string, unknown> | undefined)?.default;
    return typeof def === 'number' ? def : fallback;
  };

  // ── Derived provider_config field values ──────────────────────────────────

  // filesystem
  const fsRootPath = pcStr(FILESYSTEM_CONFIG_KEY.ROOT_PATH);

  // s3 / ibm_cos
  const s3AccessKey = pcStr(S3_CONFIG_KEY.ACCESS_KEY);
  const s3SecretKey = pcStr(S3_CONFIG_KEY.SECRET_KEY);
  const s3Bucket = pcStr(S3_CONFIG_KEY.BUCKET);
  const s3KeyPrefix = pcStr(S3_CONFIG_KEY.KEY_PREFIX);
  const s3EndpointUrl = pcStr(S3_CONFIG_KEY.ENDPOINT_URL);
  const s3Region = pcStr(S3_CONFIG_KEY.REGION);
  const s3VerifyBucketOwner = pcBool(S3_CONFIG_KEY.VERIFY_EXPECTED_BUCKET_OWNER, false);

  const contentTypeMapStored = (providerConfig[S3_CONFIG_KEY.CONTENT_TYPE_MAP] as Record<string, unknown> | null | undefined) ?? null;

  // box
  const boxCredentialsPath = pcStr(BOX_CONFIG_KEY.CREDENTIALS_PATH);
  const boxFolderId = pcStr(BOX_CONFIG_KEY.FOLDER_ID);

  // sharepoint / onedrive
  const spClientId = pcStr(SHAREPOINT_CONFIG_KEY.CLIENT_ID);
  const spClientSecret = pcStr(SHAREPOINT_CONFIG_KEY.CLIENT_SECRET);
  const spTenantId = pcStr(SHAREPOINT_CONFIG_KEY.TENANT_ID);
  const spDriveId = pcStr(SHAREPOINT_CONFIG_KEY.DRIVE_ID);
  const spFolderPath = pcStr(SHAREPOINT_CONFIG_KEY.FOLDER_PATH);
  const spGraphApiVersion = pcStr(SHAREPOINT_CONFIG_KEY.GRAPH_API_VERSION) || 'v1.0';

  // google_drive
  const gdFolderId = pcStr(GOOGLE_DRIVE_CONFIG_KEY.FOLDER_ID);
  const gdDriveId = pcStr(GOOGLE_DRIVE_CONFIG_KEY.DRIVE_ID);
  const gdServiceAccountPath = pcStr(GOOGLE_DRIVE_CONFIG_KEY.SERVICE_ACCOUNT_JSON_PATH);
  const gdCredentialsPath = pcStr(GOOGLE_DRIVE_CONFIG_KEY.CREDENTIALS_PATH);
  const gdTokenPath = pcStr(GOOGLE_DRIVE_CONFIG_KEY.TOKEN_PATH);
  const gdScopes: string[] = Array.isArray(providerConfig[GOOGLE_DRIVE_CONFIG_KEY.SCOPES])
    ? (providerConfig[GOOGLE_DRIVE_CONFIG_KEY.SCOPES] as string[])
    : [];
  const gdChunkSizeMb = pcNum(GOOGLE_DRIVE_CONFIG_KEY.CHUNK_SIZE_MB, 5);

  // common across all providers
  const createDirs = pcBool('create_dirs', true);

  useProviderConfigDefaults(controller, nodeAttributes);

  // ── Validation ────────────────────────────────────────────────────────────
  const validate = getRequiredParamValidator(nodeAttributes);
  const modeValidation = validate(ATTR.MODE, mode ?? undefined);
  const destConfigValidation = validate(ATTR.DESTINATION_CONFIG, destinationConfig);

  // ── Update helpers ────────────────────────────────────────────────────────

  /** Merge a single key into provider_config and persist destination_config. */
  const updateProviderConfig = useCallback((key: string, value: unknown): void => {
    controller?.updatePropertyValue?.(
      { name: ATTR.DESTINATION_CONFIG },
      {
        ...destinationConfig,
        [DESTINATION_CONFIG_KEY.PROVIDER_CONFIG]: { ...providerConfig, [key]: value },
      }
    );
  }, [controller, destinationConfig, providerConfig]);

  const updateOutputFormat = useCallback((key: string, value: unknown): void => {
    controller?.updatePropertyValue?.(
      { name: ATTR.OUTPUT_FORMAT },
      { ...outputFormat, [key]: value }
    );
  }, [controller, outputFormat]);

  const updateOutputStructure = useCallback((key: string, value: unknown): void => {
    controller?.updatePropertyValue?.(
      { name: ATTR.OUTPUT_STRUCTURE },
      { ...outputStructure, [key]: value }
    );
  }, [controller, outputStructure]);

  return (
    <div className={common.commonPropertiesPanelBody}>

      {/* ══ MODE ══════════════════════════════════════════════════════════ */}
      <div className={common.formField}>
        <div className={common.labelWithTooltip}>
          <RequiredParamTooltip
            paramId={ATTR.MODE}
            nodeAttributes={nodeAttributes}
            definition={nodeAttributes[ATTR.MODE]?.description ?? ''}
          >
            {intl.formatMessage(messages.mode)}
          </RequiredParamTooltip>
        </div>
        <Dropdown
          id="mode"
          titleText={intl.formatMessage(messages.mode)}
          hideLabel
          label={intl.formatMessage(messages.selectMode)}
          items={modeItems}
          selectedItem={mode ?? null}
          itemToString={(item: WriteMode | null) => (item ? writeModeLabels[item] : '')}
          invalid={modeValidation.isInvalid}
          invalidText={modeValidation.errorMessage}
          onChange={({ selectedItem }: { selectedItem: WriteMode | null }) => {
            if (selectedItem) {
              controller?.updatePropertyValue?.({ name: ATTR.MODE }, selectedItem);
            }
          }}
        />
      </div>

      {/* ══ DESTINATION CONFIGURATION ════════════════════════════════════ */}
      <Accordion align="start">
        <AccordionItem title={intl.formatMessage(messages.destinationConfigTitle)} open>
          <div className={common.accordionContent}>
            {nodeAttributes[ATTR.DESTINATION_CONFIG]?.description && (
              <p className={common.accordionDescription}>
                {nodeAttributes[ATTR.DESTINATION_CONFIG]?.description}
              </p>
            )}

      {/* Provider */}
      <div className={common.formField}>
        <div className={common.labelWithTooltip}>
          <RequiredParamTooltip
            paramId={DESTINATION_CONFIG_KEY.PROVIDER}
            nodeAttributes={destAttrs}
            definition={destAttrs[DESTINATION_CONFIG_KEY.PROVIDER]?.description ?? ''}
          >
            {intl.formatMessage(messages.provider)}
          </RequiredParamTooltip>
        </div>
        <Dropdown
          id="destination_provider"
          titleText={intl.formatMessage(messages.provider)}
          hideLabel
          label={intl.formatMessage(messages.selectProvider)}
          items={providerItems}
          selectedItem={provider || null}
          invalid={destConfigValidation.isInvalid && !provider}
          invalidText={destConfigValidation.errorMessage}
          onChange={({ selectedItem }: { selectedItem: string | null }) => {
            if (selectedItem) {
              // Reset provider_config and credentials when provider changes.
              controller?.updatePropertyValue?.(
                { name: ATTR.DESTINATION_CONFIG },
                {
                  [DESTINATION_CONFIG_KEY.PROVIDER]: selectedItem,
                  [DESTINATION_CONFIG_KEY.PROVIDER_CONFIG]: {},
                  [DESTINATION_CONFIG_KEY.CREDENTIALS]: {},
                }
              );
            }
          }}
        />
      </div>

      {/* ── filesystem provider_config ──────────────────────────────────── */}
      {provider === 'filesystem' && (
        <div className={common.subSection}>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={FILESYSTEM_CONFIG_KEY.ROOT_PATH}
                nodeAttributes={providerSchemas['filesystem']?.properties ?? {}}
                definition={providerSchemas['filesystem']?.properties?.[FILESYSTEM_CONFIG_KEY.ROOT_PATH]?.description ?? ''}
              >
                {intl.formatMessage(messages.rootPath)}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="fs_root_path"
              labelText={intl.formatMessage(messages.rootPath)}
              hideLabel
              value={fsRootPath}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                updateProviderConfig(FILESYSTEM_CONFIG_KEY.ROOT_PATH, e.target.value);
              }}
            />
          </div>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={FILESYSTEM_CONFIG_KEY.CREATE_DIRS}
                nodeAttributes={providerSchemas['filesystem']?.properties ?? {}}
                definition={providerSchemas['filesystem']?.properties?.[FILESYSTEM_CONFIG_KEY.CREATE_DIRS]?.description ?? ''}
              >
                {intl.formatMessage(messages.createDirs)}
              </RequiredParamTooltip>
            </div>
            <Toggle
              id="fs_create_dirs"
              labelText={intl.formatMessage(messages.createDirs)}
              hideLabel
              labelA={intl.formatMessage(messages.off)}
              labelB={intl.formatMessage(messages.on)}
              toggled={createDirs}
              onToggle={(checked: boolean) => { updateProviderConfig(FILESYSTEM_CONFIG_KEY.CREATE_DIRS, checked); }}
            />
          </div>
        </div>
      )}

      {/* ── s3 / ibm_cos provider_config ───────────────────────────────── */}
      {S3_PROVIDERS.has(provider) && (
        <div className={common.subSection}>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={S3_CONFIG_KEY.ACCESS_KEY}
                nodeAttributes={providerSchemas[provider]?.properties ?? {}}
                definition={providerSchemas[provider]?.properties?.[S3_CONFIG_KEY.ACCESS_KEY]?.description ?? ''}
              >
                {intl.formatMessage(messages.accessKey)}
              </RequiredParamTooltip>
            </div>
            <VaultInput
              id="s3_access_key"
              labelText={intl.formatMessage(messages.accessKey)}
              value={s3AccessKey}
              onChange={(val: string) => {
                updateProviderConfig(S3_CONFIG_KEY.ACCESS_KEY, val);
              }}
            />
          </div>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={S3_CONFIG_KEY.SECRET_KEY}
                nodeAttributes={providerSchemas[provider]?.properties ?? {}}
                definition={providerSchemas[provider]?.properties?.[S3_CONFIG_KEY.SECRET_KEY]?.description ?? ''}
              >
                {intl.formatMessage(messages.secretKey)}
              </RequiredParamTooltip>
            </div>
            <VaultInput
              id="s3_secret_key"
              labelText={intl.formatMessage(messages.secretKey)}
              value={s3SecretKey}
              onChange={(val: string) => {
                updateProviderConfig(S3_CONFIG_KEY.SECRET_KEY, val);
              }}
            />
          </div>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={S3_CONFIG_KEY.BUCKET}
                nodeAttributes={providerSchemas[provider]?.properties ?? {}}
                definition={providerSchemas[provider]?.properties?.[S3_CONFIG_KEY.BUCKET]?.description ?? ''}
              >
                {intl.formatMessage(messages.bucket)}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="s3_bucket"
              labelText={intl.formatMessage(messages.bucket)}
              hideLabel
              value={s3Bucket}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                updateProviderConfig(S3_CONFIG_KEY.BUCKET, e.target.value);
              }}
            />
          </div>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={S3_CONFIG_KEY.KEY_PREFIX}
                nodeAttributes={providerSchemas[provider]?.properties ?? {}}
                definition={providerSchemas[provider]?.properties?.[S3_CONFIG_KEY.KEY_PREFIX]?.description ?? ''}
              >
                {intl.formatMessage(messages.keyPrefix)}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="s3_key_prefix"
              labelText={intl.formatMessage(messages.keyPrefix)}
              hideLabel
              value={s3KeyPrefix}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                updateProviderConfig(S3_CONFIG_KEY.KEY_PREFIX, e.target.value);
              }}
            />
          </div>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={S3_CONFIG_KEY.ENDPOINT_URL}
                nodeAttributes={providerSchemas[provider]?.properties ?? {}}
                definition={providerSchemas[provider]?.properties?.[S3_CONFIG_KEY.ENDPOINT_URL]?.description ?? ''}
              >
                {intl.formatMessage(messages.endpointUrl)}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="s3_endpoint_url"
              labelText={intl.formatMessage(messages.endpointUrl)}
              hideLabel
              value={s3EndpointUrl}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                updateProviderConfig(S3_CONFIG_KEY.ENDPOINT_URL, e.target.value || null);
              }}
            />
          </div>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={S3_CONFIG_KEY.REGION}
                nodeAttributes={providerSchemas[provider]?.properties ?? {}}
                definition={providerSchemas[provider]?.properties?.[S3_CONFIG_KEY.REGION]?.description ?? ''}
              >
                {intl.formatMessage(messages.region)}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="s3_region"
              labelText={intl.formatMessage(messages.region)}
              hideLabel
              value={s3Region}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                updateProviderConfig(S3_CONFIG_KEY.REGION, e.target.value || null);
              }}
            />
          </div>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={S3_CONFIG_KEY.VERIFY_EXPECTED_BUCKET_OWNER}
                nodeAttributes={providerSchemas[provider]?.properties ?? {}}
                definition={providerSchemas[provider]?.properties?.[S3_CONFIG_KEY.VERIFY_EXPECTED_BUCKET_OWNER]?.description ?? ''}
              >
                {intl.formatMessage(messages.verifyExpectedBucketOwner)}
              </RequiredParamTooltip>
            </div>
            <Toggle
              id="s3_verify_bucket_owner"
              labelText={intl.formatMessage(messages.verifyExpectedBucketOwner)}
              hideLabel
              labelA={intl.formatMessage(messages.off)}
              labelB={intl.formatMessage(messages.on)}
              toggled={s3VerifyBucketOwner}
              onToggle={(checked: boolean) => { updateProviderConfig(S3_CONFIG_KEY.VERIFY_EXPECTED_BUCKET_OWNER, checked); }}
            />
          </div>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={S3_CONFIG_KEY.CREATE_DIRS}
                nodeAttributes={providerSchemas[provider]?.properties ?? {}}
                definition={providerSchemas[provider]?.properties?.[S3_CONFIG_KEY.CREATE_DIRS]?.description ?? ''}
              >
                {intl.formatMessage(messages.createDirs)}
              </RequiredParamTooltip>
            </div>
            <Toggle
              id="s3_create_dirs"
              labelText={intl.formatMessage(messages.createDirs)}
              hideLabel
              labelA={intl.formatMessage(messages.off)}
              labelB={intl.formatMessage(messages.on)}
              toggled={createDirs}
              onToggle={(checked: boolean) => { updateProviderConfig(S3_CONFIG_KEY.CREATE_DIRS, checked); }}
            />
          </div>
          {/* content_type_map: power-user override — keep as JSON textarea */}
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={S3_CONFIG_KEY.CONTENT_TYPE_MAP}
                nodeAttributes={providerSchemas[provider]?.properties ?? {}}
                definition={providerSchemas[provider]?.properties?.[S3_CONFIG_KEY.CONTENT_TYPE_MAP]?.description ?? ''}
              >
                {intl.formatMessage(messages.contentTypeMap)}
              </RequiredParamTooltip>
            </div>
            <JsonTextArea
              id="s3_content_type_map"
              labelText={intl.formatMessage(messages.contentTypeMap)}
              storedValue={contentTypeMapStored}
              rows={3}
              onChange={(value) => {
                updateProviderConfig(S3_CONFIG_KEY.CONTENT_TYPE_MAP, value ?? undefined);
              }}
            />
          </div>
        </div>
      )}

      {/* ── box provider_config ─────────────────────────────────────────── */}
      {provider === 'box' && (
        <div className={common.subSection}>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={BOX_CONFIG_KEY.CREDENTIALS_PATH}
                nodeAttributes={providerSchemas['box']?.properties ?? {}}
                definition={providerSchemas['box']?.properties?.[BOX_CONFIG_KEY.CREDENTIALS_PATH]?.description ?? ''}
              >
                {intl.formatMessage(messages.boxCredentialsPath)}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="box_credentials_path"
              labelText={intl.formatMessage(messages.boxCredentialsPath)}
              hideLabel
              value={boxCredentialsPath}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                updateProviderConfig(BOX_CONFIG_KEY.CREDENTIALS_PATH, e.target.value);
              }}
            />
          </div>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={BOX_CONFIG_KEY.FOLDER_ID}
                nodeAttributes={providerSchemas['box']?.properties ?? {}}
                definition={providerSchemas['box']?.properties?.[BOX_CONFIG_KEY.FOLDER_ID]?.description ?? ''}
              >
                {intl.formatMessage(messages.boxFolderId)}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="box_folder_id"
              labelText={intl.formatMessage(messages.boxFolderId)}
              hideLabel
              value={boxFolderId}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                updateProviderConfig(BOX_CONFIG_KEY.FOLDER_ID, e.target.value);
              }}
            />
          </div>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={BOX_CONFIG_KEY.CREATE_DIRS}
                nodeAttributes={providerSchemas['box']?.properties ?? {}}
                definition={providerSchemas['box']?.properties?.[BOX_CONFIG_KEY.CREATE_DIRS]?.description ?? ''}
              >
                {intl.formatMessage(messages.createDirs)}
              </RequiredParamTooltip>
            </div>
            <Toggle
              id="box_create_dirs"
              labelText={intl.formatMessage(messages.createDirs)}
              hideLabel
              labelA={intl.formatMessage(messages.off)}
              labelB={intl.formatMessage(messages.on)}
              toggled={createDirs}
              onToggle={(checked: boolean) => { updateProviderConfig(BOX_CONFIG_KEY.CREATE_DIRS, checked); }}
            />
          </div>
        </div>
      )}

      {/* ── sharepoint / onedrive provider_config ───────────────────────── */}
      {SHAREPOINT_PROVIDERS.has(provider) && (
        <div className={common.subSection}>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={SHAREPOINT_CONFIG_KEY.CLIENT_ID}
                nodeAttributes={providerSchemas[provider]?.properties ?? {}}
                definition={providerSchemas[provider]?.properties?.[SHAREPOINT_CONFIG_KEY.CLIENT_ID]?.description ?? ''}
              >
                {intl.formatMessage(messages.clientId)}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="sp_client_id"
              labelText={intl.formatMessage(messages.clientId)}
              hideLabel
              value={spClientId}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                updateProviderConfig(SHAREPOINT_CONFIG_KEY.CLIENT_ID, e.target.value);
              }}
            />
          </div>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={SHAREPOINT_CONFIG_KEY.CLIENT_SECRET}
                nodeAttributes={providerSchemas[provider]?.properties ?? {}}
                definition={providerSchemas[provider]?.properties?.[SHAREPOINT_CONFIG_KEY.CLIENT_SECRET]?.description ?? ''}
              >
                {intl.formatMessage(messages.clientSecret)}
              </RequiredParamTooltip>
            </div>
            <VaultInput
              id="sp_client_secret"
              labelText={intl.formatMessage(messages.clientSecret)}
              value={spClientSecret}
              onChange={(val: string) => {
                updateProviderConfig(SHAREPOINT_CONFIG_KEY.CLIENT_SECRET, val);
              }}
            />
          </div>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={SHAREPOINT_CONFIG_KEY.TENANT_ID}
                nodeAttributes={providerSchemas[provider]?.properties ?? {}}
                definition={providerSchemas[provider]?.properties?.[SHAREPOINT_CONFIG_KEY.TENANT_ID]?.description ?? ''}
              >
                {intl.formatMessage(messages.tenantId)}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="sp_tenant_id"
              labelText={intl.formatMessage(messages.tenantId)}
              hideLabel
              value={spTenantId}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                updateProviderConfig(SHAREPOINT_CONFIG_KEY.TENANT_ID, e.target.value);
              }}
            />
          </div>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={SHAREPOINT_CONFIG_KEY.DRIVE_ID}
                nodeAttributes={providerSchemas[provider]?.properties ?? {}}
                definition={providerSchemas[provider]?.properties?.[SHAREPOINT_CONFIG_KEY.DRIVE_ID]?.description ?? ''}
              >
                {intl.formatMessage(messages.spDriveId)}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="sp_drive_id"
              labelText={intl.formatMessage(messages.spDriveId)}
              hideLabel
              value={spDriveId}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                updateProviderConfig(SHAREPOINT_CONFIG_KEY.DRIVE_ID, e.target.value);
              }}
            />
          </div>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={SHAREPOINT_CONFIG_KEY.FOLDER_PATH}
                nodeAttributes={providerSchemas[provider]?.properties ?? {}}
                definition={providerSchemas[provider]?.properties?.[SHAREPOINT_CONFIG_KEY.FOLDER_PATH]?.description ?? ''}
              >
                {intl.formatMessage(messages.folderPath)}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="sp_folder_path"
              labelText={intl.formatMessage(messages.folderPath)}
              hideLabel
              value={spFolderPath}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                updateProviderConfig(SHAREPOINT_CONFIG_KEY.FOLDER_PATH, e.target.value);
              }}
            />
          </div>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={SHAREPOINT_CONFIG_KEY.GRAPH_API_VERSION}
                nodeAttributes={providerSchemas[provider]?.properties ?? {}}
                definition={providerSchemas[provider]?.properties?.[SHAREPOINT_CONFIG_KEY.GRAPH_API_VERSION]?.description ?? ''}
              >
                {intl.formatMessage(messages.graphApiVersion)}
              </RequiredParamTooltip>
            </div>
            <Dropdown
              id="sp_graph_api_version"
              titleText={intl.formatMessage(messages.graphApiVersion)}
              hideLabel
              label={intl.formatMessage(messages.selectVersion)}
              items={['v1.0', 'beta']}
              selectedItem={spGraphApiVersion}
              onChange={({ selectedItem }: { selectedItem: string | null }) => {
                if (selectedItem) { updateProviderConfig(SHAREPOINT_CONFIG_KEY.GRAPH_API_VERSION, selectedItem); }
              }}
            />
          </div>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={SHAREPOINT_CONFIG_KEY.CREATE_DIRS}
                nodeAttributes={providerSchemas[provider]?.properties ?? {}}
                definition={providerSchemas[provider]?.properties?.[SHAREPOINT_CONFIG_KEY.CREATE_DIRS]?.description ?? ''}
              >
                {intl.formatMessage(messages.createDirs)}
              </RequiredParamTooltip>
            </div>
            <Toggle
              id="sp_create_dirs"
              labelText={intl.formatMessage(messages.createDirs)}
              hideLabel
              labelA={intl.formatMessage(messages.off)}
              labelB={intl.formatMessage(messages.on)}
              toggled={createDirs}
              onToggle={(checked: boolean) => { updateProviderConfig(SHAREPOINT_CONFIG_KEY.CREATE_DIRS, checked); }}
            />
          </div>
        </div>
      )}

      {/* ── google_drive provider_config ────────────────────────────────── */}
      {provider === 'google_drive' && (
        <div className={common.subSection}>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={GOOGLE_DRIVE_CONFIG_KEY.FOLDER_ID}
                nodeAttributes={providerSchemas['google_drive']?.properties ?? {}}
                definition={providerSchemas['google_drive']?.properties?.[GOOGLE_DRIVE_CONFIG_KEY.FOLDER_ID]?.description ?? ''}
              >
                {intl.formatMessage(messages.gdFolderId)}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="gd_folder_id"
              labelText={intl.formatMessage(messages.gdFolderId)}
              hideLabel
              value={gdFolderId}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                updateProviderConfig(GOOGLE_DRIVE_CONFIG_KEY.FOLDER_ID, e.target.value);
              }}
            />
          </div>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={GOOGLE_DRIVE_CONFIG_KEY.DRIVE_ID}
                nodeAttributes={providerSchemas['google_drive']?.properties ?? {}}
                definition={providerSchemas['google_drive']?.properties?.[GOOGLE_DRIVE_CONFIG_KEY.DRIVE_ID]?.description ?? ''}
              >
                {intl.formatMessage(messages.gdDriveId)}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="gd_drive_id"
              labelText={intl.formatMessage(messages.gdDriveId)}
              hideLabel
              value={gdDriveId}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                updateProviderConfig(GOOGLE_DRIVE_CONFIG_KEY.DRIVE_ID, e.target.value || null);
              }}
            />
          </div>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={GOOGLE_DRIVE_CONFIG_KEY.SERVICE_ACCOUNT_JSON_PATH}
                nodeAttributes={providerSchemas['google_drive']?.properties ?? {}}
                definition={providerSchemas['google_drive']?.properties?.[GOOGLE_DRIVE_CONFIG_KEY.SERVICE_ACCOUNT_JSON_PATH]?.description ?? ''}
              >
                {intl.formatMessage(messages.serviceAccountJsonPath)}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="gd_service_account_path"
              labelText={intl.formatMessage(messages.serviceAccountJsonPath)}
              hideLabel
              value={gdServiceAccountPath}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                updateProviderConfig(GOOGLE_DRIVE_CONFIG_KEY.SERVICE_ACCOUNT_JSON_PATH, e.target.value || null);
              }}
            />
          </div>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={GOOGLE_DRIVE_CONFIG_KEY.CREDENTIALS_PATH}
                nodeAttributes={providerSchemas['google_drive']?.properties ?? {}}
                definition={providerSchemas['google_drive']?.properties?.[GOOGLE_DRIVE_CONFIG_KEY.CREDENTIALS_PATH]?.description ?? ''}
              >
                {intl.formatMessage(messages.gdCredentialsPath)}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="gd_credentials_path"
              labelText={intl.formatMessage(messages.gdCredentialsPath)}
              hideLabel
              value={gdCredentialsPath}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                updateProviderConfig(GOOGLE_DRIVE_CONFIG_KEY.CREDENTIALS_PATH, e.target.value || null);
              }}
            />
          </div>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={GOOGLE_DRIVE_CONFIG_KEY.TOKEN_PATH}
                nodeAttributes={providerSchemas['google_drive']?.properties ?? {}}
                definition={providerSchemas['google_drive']?.properties?.[GOOGLE_DRIVE_CONFIG_KEY.TOKEN_PATH]?.description ?? ''}
              >
                {intl.formatMessage(messages.tokenPath)}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="gd_token_path"
              labelText={intl.formatMessage(messages.tokenPath)}
              hideLabel
              value={gdTokenPath}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                updateProviderConfig(GOOGLE_DRIVE_CONFIG_KEY.TOKEN_PATH, e.target.value || null);
              }}
            />
          </div>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={GOOGLE_DRIVE_CONFIG_KEY.SCOPES}
                nodeAttributes={providerSchemas['google_drive']?.properties ?? {}}
                definition={providerSchemas['google_drive']?.properties?.[GOOGLE_DRIVE_CONFIG_KEY.SCOPES]?.description ?? ''}
              >
                {intl.formatMessage(messages.scopes)}
              </RequiredParamTooltip>
            </div>
            <TagInput
              id="gd_scopes"
              tags={gdScopes}
              labelText={intl.formatMessage(messages.scopes)}
              hideLabel
              helperText={intl.formatMessage(messages.scopesHelperText)}
              onChange={(newScopes) => {
                updateProviderConfig(GOOGLE_DRIVE_CONFIG_KEY.SCOPES, newScopes);
              }}
            />
          </div>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={GOOGLE_DRIVE_CONFIG_KEY.CHUNK_SIZE_MB}
                nodeAttributes={providerSchemas['google_drive']?.properties ?? {}}
                definition={providerSchemas['google_drive']?.properties?.[GOOGLE_DRIVE_CONFIG_KEY.CHUNK_SIZE_MB]?.description ?? ''}
              >
                {intl.formatMessage(messages.chunkSizeMb)}
              </RequiredParamTooltip>
            </div>
            <NumberInput
              id="gd_chunk_size_mb"
              label={intl.formatMessage(messages.chunkSizeMb)}
              hideLabel
              min={1}
              value={gdChunkSizeMb}
              onChange={(_e: unknown, { value }: { value: number | string }) => {
                updateProviderConfig(GOOGLE_DRIVE_CONFIG_KEY.CHUNK_SIZE_MB, Number(value));
              }}
            />
          </div>
          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={GOOGLE_DRIVE_CONFIG_KEY.CREATE_DIRS}
                nodeAttributes={providerSchemas['google_drive']?.properties ?? {}}
                definition={providerSchemas['google_drive']?.properties?.[GOOGLE_DRIVE_CONFIG_KEY.CREATE_DIRS]?.description ?? ''}
              >
                {intl.formatMessage(messages.createDirs)}
              </RequiredParamTooltip>
            </div>
            <Toggle
              id="gd_create_dirs"
              labelText={intl.formatMessage(messages.createDirs)}
              hideLabel
              labelA={intl.formatMessage(messages.off)}
              labelB={intl.formatMessage(messages.on)}
              toggled={createDirs}
              onToggle={(checked: boolean) => { updateProviderConfig(GOOGLE_DRIVE_CONFIG_KEY.CREATE_DIRS, checked); }}
            />
          </div>
        </div>
      )}

      {/* ── Credentials (optional, all providers) ───────────────────────── */}
      {provider && (
        <div className={common.formField}>
          <VaultInput
            id="destination_credentials"
            labelText={intl.formatMessage(messages.credentials)}
            labelComponent={
              <RequiredParamTooltip
                paramId={DESTINATION_CONFIG_KEY.CREDENTIALS}
                nodeAttributes={destAttrs}
                definition={destAttrs[DESTINATION_CONFIG_KEY.CREDENTIALS]?.description ?? ''}
              >
                {intl.formatMessage(messages.credentials)}
              </RequiredParamTooltip>
            }
            multiline
            rows={4}
            value={credentialsStored}
            invalid={
              !isVaultReference(credentialsStored) &&
              credentialsStored.trim() !== '' &&
              !isValidJsonObject(credentialsStored)
            }
            invalidText={intl.formatMessage(messages.credentialsInvalid)}
            onChange={(val: string) => {
              let parsedValue: unknown = val;
              if (isVaultReference(val)) {
                parsedValue = val;
              } else if (val.trim() === '') {
                parsedValue = {};
              } else {
                try {
                  parsedValue = JSON.parse(val);
                } catch {
                  parsedValue = val;
                }
              }
              controller?.updatePropertyValue?.(
                { name: ATTR.DESTINATION_CONFIG },
                { ...destinationConfig, [DESTINATION_CONFIG_KEY.CREDENTIALS]: parsedValue }
              );
            }}
          />
        </div>
      )}

          </div>
        </AccordionItem>

        {/* ══ OUTPUT FORMAT ════════════════════════════════════════════════ */}
        <AccordionItem title={intl.formatMessage(messages.outputFormatTitle)}>
          <div className={common.accordionContent}>
            {nodeAttributes[ATTR.OUTPUT_FORMAT]?.description && (
              <p className={common.accordionDescription}>
                {nodeAttributes[ATTR.OUTPUT_FORMAT]?.description}
              </p>
            )}

          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={OUTPUT_FORMAT_KEY.CONTENT_FORMAT}
                nodeAttributes={outputFormatAttrs}
                definition={outputFormatAttrs[OUTPUT_FORMAT_KEY.CONTENT_FORMAT]?.description ?? ''}
              >
                {intl.formatMessage(messages.contentFormat)}
              </RequiredParamTooltip>
            </div>
            <Dropdown
              id="content_format"
              titleText={intl.formatMessage(messages.contentFormat)}
              hideLabel
              label={intl.formatMessage(messages.selectFormat)}
              items={contentFormatItems}
              selectedItem={contentFormat}
              itemToString={(item: ContentFormat | null) => (item ? contentFormatLabels[item] : '')}
              onChange={({ selectedItem }: { selectedItem: ContentFormat | null }) => {
                if (selectedItem) { updateOutputFormat(OUTPUT_FORMAT_KEY.CONTENT_FORMAT, selectedItem); }
              }}
            />
          </div>

          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={OUTPUT_FORMAT_KEY.INCLUDE_METADATA_SIDECAR}
                nodeAttributes={outputFormatAttrs}
                definition={outputFormatAttrs[OUTPUT_FORMAT_KEY.INCLUDE_METADATA_SIDECAR]?.description ?? ''}
              >
                {intl.formatMessage(messages.includeMetadataSidecar)}
              </RequiredParamTooltip>
            </div>
            <Toggle
              id="include_metadata_sidecar"
              labelText={intl.formatMessage(messages.includeMetadataSidecar)}
              hideLabel
              labelA={intl.formatMessage(messages.off)}
              labelB={intl.formatMessage(messages.on)}
              toggled={includeMetadataSidecar}
              onToggle={(checked: boolean) => { updateOutputFormat(OUTPUT_FORMAT_KEY.INCLUDE_METADATA_SIDECAR, checked); }}
            />
          </div>

          </div>
        </AccordionItem>

        {/* ══ OUTPUT STRUCTURE ══════════════════════════════════════════ */}
        <AccordionItem title={intl.formatMessage(messages.outputStructureTitle)}>
          <div className={common.accordionContent}>
            {nodeAttributes[ATTR.OUTPUT_STRUCTURE]?.description && (
              <p className={common.accordionDescription}>
                {nodeAttributes[ATTR.OUTPUT_STRUCTURE]?.description}
              </p>
            )}

          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={OUTPUT_STRUCTURE_KEY.TYPE}
                nodeAttributes={outputStructureAttrs}
                definition={outputStructureAttrs[OUTPUT_STRUCTURE_KEY.TYPE]?.description ?? ''}
              >
                {intl.formatMessage(messages.structureType)}
              </RequiredParamTooltip>
            </div>
            <Dropdown
              id="structure_type"
              titleText={intl.formatMessage(messages.structureType)}
              hideLabel
              label={intl.formatMessage(messages.selectStructure)}
              items={structureTypeItems}
              selectedItem={structureType}
              itemToString={(item: OutputStructureType | null) => (item ? structureTypeLabels[item] : '')}
              onChange={({ selectedItem }: { selectedItem: OutputStructureType | null }) => {
                if (selectedItem) { updateOutputStructure(OUTPUT_STRUCTURE_KEY.TYPE, selectedItem); }
              }}
            />
          </div>

          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={OUTPUT_STRUCTURE_KEY.PATH_TEMPLATE}
                nodeAttributes={outputStructureAttrs}
                definition={outputStructureAttrs[OUTPUT_STRUCTURE_KEY.PATH_TEMPLATE]?.description ?? ''}
              >
                {intl.formatMessage(messages.pathTemplate)}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="path_template"
              labelText={intl.formatMessage(messages.pathTemplate)}
              hideLabel
              value={pathTemplate}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                updateOutputStructure(OUTPUT_STRUCTURE_KEY.PATH_TEMPLATE, e.target.value || undefined);
              }}
            />
          </div>

          <div className={common.formField}>
            <div className={common.labelWithTooltip}>
              <RequiredParamTooltip
                paramId={OUTPUT_STRUCTURE_KEY.OVERWRITE_EXISTING}
                nodeAttributes={outputStructureAttrs}
                definition={outputStructureAttrs[OUTPUT_STRUCTURE_KEY.OVERWRITE_EXISTING]?.description ?? ''}
              >
                {intl.formatMessage(messages.overwriteExisting)}
              </RequiredParamTooltip>
            </div>
            <Toggle
              id="overwrite_existing"
              labelText={intl.formatMessage(messages.overwriteExisting)}
              hideLabel
              labelA={intl.formatMessage(messages.off)}
              labelB={intl.formatMessage(messages.on)}
              toggled={overwriteExisting}
              onToggle={(checked: boolean) => { updateOutputStructure(OUTPUT_STRUCTURE_KEY.OVERWRITE_EXISTING, checked); }}
            />
          </div>

          </div>
        </AccordionItem>
      </Accordion>

    </div>
  );
}
