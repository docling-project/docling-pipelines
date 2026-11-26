/**
 * @file Weaviate provider_config helpers for the VectorDB panel.
 *
 * Pure functions (no React, no I/O) that validate the Weaviate connection and
 * authentication settings, switch between connection types and authentication
 * methods, and prepare the configuration sent to flow enrichment. The rules mirror
 * the backend `WeaviateConfig` model so a configuration that would be rejected at
 * run time is reported before the feature-mapping tearsheet opens.
 *
 * Validation returns error codes, not text; the component maps each code to a
 * localized message.
 */

import { VAULT_PREFIX, isVaultReference } from '@/utils/vault';
import { VECTORDB_PROVIDERS, getProviderConfig } from './constants';

type ProviderConfigRecord = Record<string, unknown>;

export const WEAVIATE_CONNECTION_TYPES = {
  ON_PREM: 'on-prem',
  CLOUD: 'cloud',
} as const;

export const WEAVIATE_AUTH_TYPES = {
  NONE: 'none',
  API_KEY: 'api_key',
  BEARER_TOKEN: 'bearer_token',
  CLIENT_PASSWORD: 'client_password',
} as const;

export type WeaviateConnectionType =
  (typeof WEAVIATE_CONNECTION_TYPES)[keyof typeof WEAVIATE_CONNECTION_TYPES];
export type WeaviateAuthType = (typeof WEAVIATE_AUTH_TYPES)[keyof typeof WEAVIATE_AUTH_TYPES];

/** Values the backend applies when a key is absent; the panel displays the same defaults. */
export const WEAVIATE_DEFAULTS = {
  HOST: 'localhost',
  PORT: 8080,
  GRPC_PORT: 50051,
  SECURE: false,
} as const;

const MIN_PORT = 1;
const MAX_PORT = 65535;

/** Keys that only apply to an on-prem connection. */
const ON_PREM_KEYS = ['host', 'port', 'secure', 'grpc_host', 'grpc_port', 'grpc_secure'] as const;
/** Keys that only apply to a Weaviate Cloud connection. */
const CLOUD_KEYS = ['cluster_url'] as const;
/** Credential keys of every authentication method. */
const CREDENTIAL_KEYS = ['api_key', 'bearer_token', 'username', 'password'] as const;

/** Credential keys required by each authentication method. */
const REQUIRED_CREDENTIALS: Record<WeaviateAuthType, readonly string[]> = {
  [WEAVIATE_AUTH_TYPES.NONE]: [],
  [WEAVIATE_AUTH_TYPES.API_KEY]: ['api_key'],
  [WEAVIATE_AUTH_TYPES.BEARER_TOKEN]: ['bearer_token'],
  [WEAVIATE_AUTH_TYPES.CLIENT_PASSWORD]: ['username', 'password'],
};

/** Fields that can carry a validation error, in visual order. */
const WEAVIATE_FIELD_ORDER = [
  'host',
  'port',
  'secure',
  'grpc_port',
  'grpc_secure',
  'cluster_url',
  'api_key',
  'bearer_token',
  'username',
  'password',
] as const;

export type WeaviateField = (typeof WEAVIATE_FIELD_ORDER)[number];

/** DOM id of the control behind each field, so a blocked open can move focus to it. */
export const WEAVIATE_FIELD_IDS: Record<WeaviateField, string> = {
  host: 'weaviate-host',
  port: 'weaviate-port',
  secure: 'weaviate-secure',
  grpc_port: 'weaviate-grpc-port',
  grpc_secure: 'weaviate-grpc-secure',
  cluster_url: 'weaviate-cluster-url',
  api_key: 'weaviate-api-key',
  bearer_token: 'weaviate-bearer-token',
  username: 'weaviate-username',
  password: 'weaviate-password',
};

export type WeaviateFieldError =
  | 'required'
  | 'port_range'
  | 'vault_reference_incomplete'
  | 'tls_required';

export type WeaviateErrors = Partial<Record<WeaviateField, WeaviateFieldError>>;

const isBlank = (value: unknown): boolean =>
  value === undefined || value === null || (typeof value === 'string' && value.trim() === '');

export function getConnectionType(config: ProviderConfigRecord): WeaviateConnectionType {
  return config['connection_type'] === WEAVIATE_CONNECTION_TYPES.CLOUD
    ? WEAVIATE_CONNECTION_TYPES.CLOUD
    : WEAVIATE_CONNECTION_TYPES.ON_PREM;
}

export function getAuthType(config: ProviderConfigRecord): WeaviateAuthType {
  const value = config['auth_type'];
  return Object.values(WEAVIATE_AUTH_TYPES).includes(value as WeaviateAuthType)
    ? (value as WeaviateAuthType)
    : WEAVIATE_AUTH_TYPES.NONE;
}

/** HTTP TLS setting with the backend default applied. */
export function getHttpSecure(config: ProviderConfigRecord): boolean {
  return typeof config['secure'] === 'boolean' ? config['secure'] : WEAVIATE_DEFAULTS.SECURE;
}

/** gRPC TLS setting: the explicit value, else the HTTP setting (backend inheritance). */
function getEffectiveGrpcSecure(config: ProviderConfigRecord): boolean {
  return typeof config['grpc_secure'] === 'boolean' ? config['grpc_secure'] : getHttpSecure(config);
}

function validatePort(config: ProviderConfigRecord, key: 'port' | 'grpc_port'): WeaviateFieldError | null {
  const value = config[key];
  if (value === undefined || value === null) { return null; }
  if (typeof value === 'number' && Number.isInteger(value) && value >= MIN_PORT && value <= MAX_PORT) {
    return null;
  }
  return isBlank(value) ? 'required' : 'port_range';
}

/** Whitespace or a control character anywhere in a reference (the backend rejects both). */
const UNSAFE_REFERENCE_CHAR = /[\s\p{Cc}]/u;

/**
 * A vault reference needs a non-empty `<provider>/<path>` after the prefix and, when a
 * `#<key>` fragment is present, a non-empty key. The path is validated separately from the
 * fragment and must have no empty, `.` or `..` segments. Whitespace and control characters
 * are rejected everywhere (mirrors the backend `parse_reference`).
 */
function isCompleteVaultReference(value: string): boolean {
  if (UNSAFE_REFERENCE_CHAR.test(value)) { return false; }
  const [body = '', ...fragments] = value.slice(VAULT_PREFIX.length).split('#');
  if (fragments.length > 1 || (fragments.length === 1 && fragments[0] === '')) { return false; }
  const separator = body.indexOf('/');
  if (separator <= 0) { return false; }
  return body
    .slice(separator + 1)
    .split('/')
    .every((segment) => segment !== '' && segment !== '.' && segment !== '..');
}

function validateCredential(config: ProviderConfigRecord, key: string): WeaviateFieldError | null {
  const value = config[key];
  if (isBlank(value)) { return 'required'; }
  if (isVaultReference(value) && !isCompleteVaultReference(value)) { return 'vault_reference_incomplete'; }
  return null;
}

/**
 * Validate a Weaviate `provider_config`.
 *
 * Absent connection keys are valid because the backend supplies defaults; a key that
 * is present but blank or out of range is not.
 */
export function validateWeaviateConfig(config: ProviderConfigRecord): WeaviateErrors {
  const errors: WeaviateErrors = {};
  const connectionType = getConnectionType(config);

  if (connectionType === WEAVIATE_CONNECTION_TYPES.ON_PREM) {
    if (config['host'] !== undefined && isBlank(config['host'])) { errors.host = 'required'; }
    const portError = validatePort(config, 'port');
    if (portError) { errors.port = portError; }
    const grpcPortError = validatePort(config, 'grpc_port');
    if (grpcPortError) { errors.grpc_port = grpcPortError; }
  } else if (isBlank(config['cluster_url'])) {
    errors.cluster_url = 'required';
  }

  const authType = getAuthType(config);
  for (const key of REQUIRED_CREDENTIALS[authType]) {
    const credentialError = validateCredential(config, key);
    if (credentialError) { errors[key as WeaviateField] = credentialError; }
  }

  // Cloud connections are always TLS.
  if (connectionType === WEAVIATE_CONNECTION_TYPES.ON_PREM && authType !== WEAVIATE_AUTH_TYPES.NONE) {
    if (!getHttpSecure(config)) { errors.secure = 'tls_required'; }
    if (!getEffectiveGrpcSecure(config)) { errors.grpc_secure = 'tls_required'; }
  }

  return errors;
}

/** The first field with an error, in visual order, or null when the configuration is valid. */
export function firstInvalidField(errors: WeaviateErrors): WeaviateField | null {
  return WEAVIATE_FIELD_ORDER.find((field) => errors[field] !== undefined) ?? null;
}

/** True when the field lives in the Authentication section rather than the Connection section. */
export function isAuthenticationField(field: WeaviateField): boolean {
  return (CREDENTIAL_KEYS as readonly string[]).includes(field);
}

/** True when the authenticated-plaintext rule is violated (the TLS alert is shown). */
export function hasTlsError(errors: WeaviateErrors): boolean {
  return errors.secure === 'tls_required' || errors.grpc_secure === 'tls_required';
}

/** Keys whose edit reveals a TLS error. */
const TLS_ERROR_TRIGGERS = ['secure', 'grpc_secure', 'auth_type'] as const;

/** Keys whose value differs between two configurations. */
export function changedKeys(previous: ProviderConfigRecord, next: ProviderConfigRecord): string[] {
  const keys = new Set([...Object.keys(previous), ...Object.keys(next)]);
  return [...keys].filter((key) => previous[key] !== next[key]);
}

/**
 * Errors to display: a field's error shows once the user has edited it (or, for the TLS
 * rule, the TLS or authentication setting), or once an open attempt has been blocked.
 */
export function visibleErrors(
  errors: WeaviateErrors,
  touched: ReadonlySet<string>,
  attempted: boolean
): WeaviateErrors {
  if (attempted) { return errors; }
  const visible: WeaviateErrors = {};
  for (const field of WEAVIATE_FIELD_ORDER) {
    const error = errors[field];
    if (error === undefined) { continue; }
    const triggers: readonly string[] = error === 'tls_required' ? TLS_ERROR_TRIGGERS : [field];
    if (triggers.some((key) => touched.has(key))) { visible[field] = error; }
  }
  return visible;
}

function omitKeys(config: ProviderConfigRecord, keys: readonly string[]): ProviderConfigRecord {
  const removed = new Set(keys);
  return Object.fromEntries(Object.entries(config).filter(([key]) => !removed.has(key)));
}

/** Switch connection type: drop the other mode's keys and write `connection_type` in one result. */
export function switchConnectionType(
  config: ProviderConfigRecord,
  type: WeaviateConnectionType
): ProviderConfigRecord {
  const inactive = type === WEAVIATE_CONNECTION_TYPES.CLOUD ? ON_PREM_KEYS : CLOUD_KEYS;
  return { ...omitKeys(config, inactive), connection_type: type };
}

/** Switch authentication method: drop every credential and write `auth_type` in one result. */
export function switchAuthType(
  config: ProviderConfigRecord,
  type: WeaviateAuthType
): ProviderConfigRecord {
  return { ...omitKeys(config, CREDENTIAL_KEYS), auth_type: type };
}

/**
 * Set or clear a gRPC override. An empty host, or a `null` TLS value ("Same as HTTP"),
 * deletes the key so the backend inherits the HTTP value instead of freezing it.
 */
export function applyGrpcOverride(
  config: ProviderConfigRecord,
  key: 'grpc_host' | 'grpc_secure',
  value: string | boolean | null
): ProviderConfigRecord {
  if (value === null || (typeof value === 'string' && value.trim() === '')) {
    return omitKeys(config, [key]);
  }
  return { ...config, [key]: value };
}

/**
 * Configuration sent to flow enrichment: the displayed defaults merged under the saved
 * values, without inherited gRPC fields that the user left unset and without the
 * index-creation settings (`advancedOnlyKeys`), which only matter when writing.
 */
export function buildEnrichmentConfig(saved: ProviderConfigRecord): ProviderConfigRecord {
  const connectionType = getConnectionType(saved);
  const defaults: ProviderConfigRecord =
    connectionType === WEAVIATE_CONNECTION_TYPES.ON_PREM
      ? {
          connection_type: connectionType,
          host: WEAVIATE_DEFAULTS.HOST,
          port: WEAVIATE_DEFAULTS.PORT,
          secure: WEAVIATE_DEFAULTS.SECURE,
        }
      : { connection_type: connectionType };

  const merged = { ...defaults, ...saved };
  const unsetInherited = ['grpc_host', 'grpc_secure'].filter((key) => isBlank(merged[key]));
  const { advancedOnlyKeys } = getProviderConfig(VECTORDB_PROVIDERS.WEAVIATE);
  return omitKeys(merged, [...unsetInherited, ...advancedOnlyKeys]);
}
