/**
 * Attribute key names for the `storage_output` operator.
 *
 * These must match the backend attribute keys returned by
 * `StorageOutputOperator.get_metadata()["attributes"]`.
 * Used as the `name` argument to `controller.getPropertyValue()` /
 * `controller.updatePropertyValue()` throughout the panel.
 */

export const STORAGE_OUTPUT_ATTRIBUTE = {
  /** Write mode */
  MODE: 'mode',
  /** Destination configuration object (provider, provider_config, credentials) */
  DESTINATION_CONFIG: 'destination_config',
  /** Output format object (content_format, include_metadata_sidecar) */
  OUTPUT_FORMAT: 'output_format',
  /** Output structure object (type, path_template, overwrite_existing) */
  OUTPUT_STRUCTURE: 'output_structure',
} as const;

/**
 * Keys inside the `destination_config` object.
 */
export const DESTINATION_CONFIG_KEY = {
  PROVIDER: 'provider',
  PROVIDER_CONFIG: 'provider_config',
  CREDENTIALS: 'credentials',
} as const;

/**
 * Keys inside the `output_format` object.
 */
export const OUTPUT_FORMAT_KEY = {
  CONTENT_FORMAT: 'content_format',
  INCLUDE_METADATA_SIDECAR: 'include_metadata_sidecar',
} as const;

/**
 * Keys inside the `output_structure` object.
 */
export const OUTPUT_STRUCTURE_KEY = {
  TYPE: 'type',
  PATH_TEMPLATE: 'path_template',
  OVERWRITE_EXISTING: 'overwrite_existing',
} as const;

/**
 * Valid write mode values.
 */
export type WriteMode = 'processed_content' | 'refetch_original' | 'comprehensive_export';

/**
 * Valid content format values.
 */
export type ContentFormat = 'md' | 'txt' | 'json';

/**
 * Valid output structure type values.
 */
export type OutputStructureType = 'flat' | 'hierarchical';

// ── Provider config field keys ────────────────────────────────────────────────

/** Fields shared by all providers */
export const PROVIDER_CONFIG_COMMON_KEY = {
  CREATE_DIRS: 'create_dirs',
} as const;

/** filesystem provider_config fields */
export const FILESYSTEM_CONFIG_KEY = {
  ROOT_PATH: 'root_path',
  CREATE_DIRS: 'create_dirs',
} as const;

/** s3 / ibm_cos provider_config fields */
export const S3_CONFIG_KEY = {
  ACCESS_KEY: 'access_key',
  SECRET_KEY: 'secret_key', // pragma: allowlist secret
  BUCKET: 'bucket',
  KEY_PREFIX: 'key_prefix',
  CREATE_DIRS: 'create_dirs',
  ENDPOINT_URL: 'endpoint_url',
  REGION: 'region',
  VERIFY_EXPECTED_BUCKET_OWNER: 'verify_expected_bucket_owner',
  CONTENT_TYPE_MAP: 'content_type_map',
} as const;

/** box provider_config fields */
export const BOX_CONFIG_KEY = {
  CREDENTIALS_PATH: 'credentials_path',
  FOLDER_ID: 'folder_id',
  CREATE_DIRS: 'create_dirs',
} as const;

/** sharepoint / onedrive provider_config fields */
export const SHAREPOINT_CONFIG_KEY = {
  CLIENT_ID: 'client_id',
  CLIENT_SECRET: 'client_secret', // pragma: allowlist secret
  TENANT_ID: 'tenant_id',
  DRIVE_ID: 'drive_id',
  FOLDER_PATH: 'folder_path',
  CREATE_DIRS: 'create_dirs',
  GRAPH_API_VERSION: 'graph_api_version',
} as const;

/** google_drive provider_config fields */
export const GOOGLE_DRIVE_CONFIG_KEY = {
  FOLDER_ID: 'folder_id',
  DRIVE_ID: 'drive_id',
  CREATE_DIRS: 'create_dirs',
  SERVICE_ACCOUNT_JSON_PATH: 'service_account_json_path',
  CREDENTIALS_PATH: 'credentials_path',
  TOKEN_PATH: 'token_path',
  SCOPES: 'scopes',
  CHUNK_SIZE_MB: 'chunk_size_mb',
} as const;

/**
 * Providers that share the S3 config shape. */
export const S3_PROVIDERS = new Set(['s3', 'ibm_cos']);

/** Providers that share the SharePoint config shape. */
export const SHAREPOINT_PROVIDERS = new Set(['sharepoint', 'onedrive']);
