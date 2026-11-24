/**
 * Migration of the legacy `credentials` block.
 *
 * Older flows may have stored provider credentials in `destination_config.credentials`. The
 * panel now exposes every credential field inside `provider_config`, so the
 * separate Credentials field was removed. The backend still merges both blocks
 * (`credentials` wins on conflicts), so this migration keeps the flow behaviour
 * unchanged while moving the values into the visible provider fields.
 */

import { DESTINATION_CONFIG_KEY } from './constants';

/**
 * Legacy credential keys that map onto the key the panel renders, per provider.
 * The Box adapter accepts `credentials_json_path` as an alias of `credentials_path`.
 */
const LEGACY_KEY_ALIASES: Record<string, Record<string, string>> = {
  box: { credentials_json_path: 'credentials_path' },
};

/** True when the value carries information (not null, undefined or blank text). */
function hasValue(value: unknown): boolean {
  if (value === null || value === undefined) { return false; }
  if (typeof value === 'string') { return value.trim() !== ''; }
  return true;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * Moves `destination_config.credentials` into `destination_config.provider_config`.
 *
 * Rules:
 * - Keys with a real value in `credentials` override the same key in `provider_config`.
 * - Blank (`null`, `undefined`, empty string) values never override anything.
 * - For Box, the legacy `credentials_json_path` is renamed to `credentials_path`, the key that the
 *   panel and the operator metadata use.
 * - The `credentials` key is removed from the result. The backend treats it as optional.
 *
 * @returns the updated destination config, or `null` when there is nothing to migrate
 *          (no credentials block, empty block, or a non-object value such as a string).
 */
export function migrateLegacyCredentials(
  destinationConfig: Record<string, unknown> | null | undefined
): Record<string, unknown> | null {
  const credentials = destinationConfig?.[DESTINATION_CONFIG_KEY.CREDENTIALS];
  if (!destinationConfig || !isPlainObject(credentials) || Object.keys(credentials).length === 0) {
    return null;
  }

  const provider = destinationConfig[DESTINATION_CONFIG_KEY.PROVIDER];
  const aliases = (typeof provider === 'string' ? LEGACY_KEY_ALIASES[provider] : undefined) ?? {};

  const existing = destinationConfig[DESTINATION_CONFIG_KEY.PROVIDER_CONFIG];
  const providerConfig: Record<string, unknown> = isPlainObject(existing) ? { ...existing } : {};

  for (const [key, value] of Object.entries(credentials)) {
    if (!hasValue(value)) { continue; }
    providerConfig[aliases[key] ?? key] = value;
  }

  const { [DESTINATION_CONFIG_KEY.CREDENTIALS]: _legacyCredentials, ...rest } = destinationConfig;

  return {
    ...rest,
    [DESTINATION_CONFIG_KEY.PROVIDER_CONFIG]: providerConfig,
  };
}
