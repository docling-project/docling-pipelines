/**
 * @file StorageOutput operator properties panel body.
 *
 * **provider_config** renders structured, per-provider fields.
 * Switching `provider` resets `provider_config` so stale fields from the previous
 * provider are never persisted.
 */

import React, { useCallback } from 'react';
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
  CONTENT_FORMAT_LABELS,
  DESTINATION_CONFIG_KEY,
  FILESYSTEM_CONFIG_KEY,
  GOOGLE_DRIVE_CONFIG_KEY,
  OUTPUT_FORMAT_KEY,
  OUTPUT_STRUCTURE_KEY,
  OUTPUT_STRUCTURE_TYPE_LABELS,
  S3_CONFIG_KEY,
  S3_PROVIDERS,
  SHAREPOINT_CONFIG_KEY,
  SHAREPOINT_PROVIDERS,
  STORAGE_OUTPUT_ATTRIBUTE as ATTR,
  STORAGE_OUTPUT_LABELS as LABEL,
  WRITE_MODE_LABELS,
  type ContentFormat,
  type OutputStructureType,
  type WriteMode,
} from './constants';
import common from '../../CommonPropertiesPanel.module.scss';
import { useProviderConfigDefaults } from '@/hooks/useProviderConfigDefaults';

interface StorageOutputPanelBodyProps {
  controller: any;
}

/* eslint-disable @typescript-eslint/no-unsafe-call */
export function StorageOutputPanelBody({
  controller,
}: StorageOutputPanelBodyProps): React.JSX.Element {

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
            {LABEL.MODE}
          </RequiredParamTooltip>
        </div>
        <Dropdown
          id="mode"
          titleText={LABEL.MODE}
          hideLabel
          label="Select mode"
          items={modeItems}
          selectedItem={mode ?? null}
          itemToString={(item: WriteMode | null) => (item ? WRITE_MODE_LABELS[item] : '')}
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
        <AccordionItem title="Destination configuration" open>
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
            {LABEL.PROVIDER}
          </RequiredParamTooltip>
        </div>
        <Dropdown
          id="destination_provider"
          titleText={LABEL.PROVIDER}
          hideLabel
          label="Select provider"
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
                {LABEL.ROOT_PATH}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="fs_root_path"
              labelText={LABEL.ROOT_PATH}
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
                {LABEL.CREATE_DIRS}
              </RequiredParamTooltip>
            </div>
            <Toggle
              id="fs_create_dirs"
              labelText={LABEL.CREATE_DIRS}
              hideLabel
              labelA="Off"
              labelB="On"
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
                {LABEL.ACCESS_KEY}
              </RequiredParamTooltip>
            </div>
            <VaultInput
              id="s3_access_key"
              labelText={LABEL.ACCESS_KEY}
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
                {LABEL.SECRET_KEY}
              </RequiredParamTooltip>
            </div>
            <VaultInput
              id="s3_secret_key"
              labelText={LABEL.SECRET_KEY}
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
                {LABEL.BUCKET}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="s3_bucket"
              labelText={LABEL.BUCKET}
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
                {LABEL.KEY_PREFIX}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="s3_key_prefix"
              labelText={LABEL.KEY_PREFIX}
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
                {LABEL.ENDPOINT_URL}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="s3_endpoint_url"
              labelText={LABEL.ENDPOINT_URL}
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
                {LABEL.REGION}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="s3_region"
              labelText={LABEL.REGION}
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
                {LABEL.VERIFY_EXPECTED_BUCKET_OWNER}
              </RequiredParamTooltip>
            </div>
            <Toggle
              id="s3_verify_bucket_owner"
              labelText={LABEL.VERIFY_EXPECTED_BUCKET_OWNER}
              hideLabel
              labelA="Off"
              labelB="On"
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
                {LABEL.CREATE_DIRS}
              </RequiredParamTooltip>
            </div>
            <Toggle
              id="s3_create_dirs"
              labelText={LABEL.CREATE_DIRS}
              hideLabel
              labelA="Off"
              labelB="On"
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
                {LABEL.CONTENT_TYPE_MAP}
              </RequiredParamTooltip>
            </div>
            <JsonTextArea
              id="s3_content_type_map"
              labelText={LABEL.CONTENT_TYPE_MAP}
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
                {LABEL.BOX_CREDENTIALS_PATH}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="box_credentials_path"
              labelText={LABEL.BOX_CREDENTIALS_PATH}
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
                {LABEL.BOX_FOLDER_ID}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="box_folder_id"
              labelText={LABEL.BOX_FOLDER_ID}
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
                {LABEL.CREATE_DIRS}
              </RequiredParamTooltip>
            </div>
            <Toggle
              id="box_create_dirs"
              labelText={LABEL.CREATE_DIRS}
              hideLabel
              labelA="Off"
              labelB="On"
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
                {LABEL.CLIENT_ID}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="sp_client_id"
              labelText={LABEL.CLIENT_ID}
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
                {LABEL.CLIENT_SECRET}
              </RequiredParamTooltip>
            </div>
            <VaultInput
              id="sp_client_secret"
              labelText={LABEL.CLIENT_SECRET}
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
                {LABEL.TENANT_ID}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="sp_tenant_id"
              labelText={LABEL.TENANT_ID}
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
                {LABEL.SP_DRIVE_ID}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="sp_drive_id"
              labelText={LABEL.SP_DRIVE_ID}
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
                {LABEL.FOLDER_PATH}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="sp_folder_path"
              labelText={LABEL.FOLDER_PATH}
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
                {LABEL.GRAPH_API_VERSION}
              </RequiredParamTooltip>
            </div>
            <Dropdown
              id="sp_graph_api_version"
              titleText={LABEL.GRAPH_API_VERSION}
              hideLabel
              label="Select version"
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
                {LABEL.CREATE_DIRS}
              </RequiredParamTooltip>
            </div>
            <Toggle
              id="sp_create_dirs"
              labelText={LABEL.CREATE_DIRS}
              hideLabel
              labelA="Off"
              labelB="On"
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
                {LABEL.GD_FOLDER_ID}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="gd_folder_id"
              labelText={LABEL.GD_FOLDER_ID}
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
                {LABEL.GD_DRIVE_ID}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="gd_drive_id"
              labelText={LABEL.GD_DRIVE_ID}
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
                {LABEL.SERVICE_ACCOUNT_JSON_PATH}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="gd_service_account_path"
              labelText={LABEL.SERVICE_ACCOUNT_JSON_PATH}
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
                {LABEL.GD_CREDENTIALS_PATH}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="gd_credentials_path"
              labelText={LABEL.GD_CREDENTIALS_PATH}
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
                {LABEL.TOKEN_PATH}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="gd_token_path"
              labelText={LABEL.TOKEN_PATH}
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
                {LABEL.SCOPES}
              </RequiredParamTooltip>
            </div>
            <TagInput
              id="gd_scopes"
              tags={gdScopes}
              labelText={LABEL.SCOPES}
              hideLabel
              helperText="Press Enter or comma to add a scope."
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
                {LABEL.CHUNK_SIZE_MB}
              </RequiredParamTooltip>
            </div>
            <NumberInput
              id="gd_chunk_size_mb"
              label={LABEL.CHUNK_SIZE_MB}
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
                {LABEL.CREATE_DIRS}
              </RequiredParamTooltip>
            </div>
            <Toggle
              id="gd_create_dirs"
              labelText={LABEL.CREATE_DIRS}
              hideLabel
              labelA="Off"
              labelB="On"
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
            labelText={LABEL.CREDENTIALS}
            labelComponent={
              <RequiredParamTooltip
                paramId={DESTINATION_CONFIG_KEY.CREDENTIALS}
                nodeAttributes={destAttrs}
                definition={destAttrs[DESTINATION_CONFIG_KEY.CREDENTIALS]?.description ?? ''}
              >
                {LABEL.CREDENTIALS}
              </RequiredParamTooltip>
            }
            multiline
            rows={4}
            value={credentialsStored}
            invalid={
              credentialsStored.trim() !== '' &&
              !isVaultReference(credentialsStored) &&
              !isValidJsonObject(credentialsStored)
            }
            invalidText="Credentials must be a valid JSON object or a vault:// reference."
            onChange={(val: string) => {
              let parsedValue: unknown = val;
              if (val.trim() === '') {
                parsedValue = {};
              } else if (isVaultReference(val)) {
                parsedValue = val;
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
        <AccordionItem title="Output format">
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
                {LABEL.CONTENT_FORMAT}
              </RequiredParamTooltip>
            </div>
            <Dropdown
              id="content_format"
              titleText={LABEL.CONTENT_FORMAT}
              hideLabel
              label="Select format"
              items={contentFormatItems}
              selectedItem={contentFormat}
              itemToString={(item: ContentFormat | null) => (item ? CONTENT_FORMAT_LABELS[item] : '')}
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
                {LABEL.INCLUDE_METADATA_SIDECAR}
              </RequiredParamTooltip>
            </div>
            <Toggle
              id="include_metadata_sidecar"
              labelText={LABEL.INCLUDE_METADATA_SIDECAR}
              hideLabel
              labelA="Off"
              labelB="On"
              toggled={includeMetadataSidecar}
              onToggle={(checked: boolean) => { updateOutputFormat(OUTPUT_FORMAT_KEY.INCLUDE_METADATA_SIDECAR, checked); }}
            />
          </div>

          </div>
        </AccordionItem>

        {/* ══ OUTPUT STRUCTURE ══════════════════════════════════════════ */}
        <AccordionItem title="Output structure">
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
                {LABEL.STRUCTURE_TYPE}
              </RequiredParamTooltip>
            </div>
            <Dropdown
              id="structure_type"
              titleText={LABEL.STRUCTURE_TYPE}
              hideLabel
              label="Select structure"
              items={structureTypeItems}
              selectedItem={structureType}
              itemToString={(item: OutputStructureType | null) => (item ? OUTPUT_STRUCTURE_TYPE_LABELS[item] : '')}
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
                {LABEL.PATH_TEMPLATE}
              </RequiredParamTooltip>
            </div>
            <TextInput
              id="path_template"
              labelText={LABEL.PATH_TEMPLATE}
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
                {LABEL.OVERWRITE_EXISTING}
              </RequiredParamTooltip>
            </div>
            <Toggle
              id="overwrite_existing"
              labelText={LABEL.OVERWRITE_EXISTING}
              hideLabel
              labelA="Off"
              labelB="On"
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
