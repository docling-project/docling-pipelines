/**
 * @fileoverview Vault reference utility functions.
 */

/** Prefix of a vault reference string, as recognised by the backend. */
export const VAULT_PREFIX = 'vault://';

/**
 * Returns true when value is a vault:// reference string, as recognised by the backend.
 */
export const isVaultReference = (value: unknown): value is string =>
  typeof value === 'string' && value.startsWith(VAULT_PREFIX);
