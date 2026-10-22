import { API_STATUS_MAP } from './flowStatus';

export const DEFAULT_TABLE_PAGE_SIZES = [10, 25, 50] as const;
export const DEFAULT_TABLE_PAGE_SIZE = 50;

/**
 * Set of API status strings for which the Logs download button is enabled
 * in the run history tearsheet.
 *
 * Derived from `API_STATUS_MAP` so it stays in sync with every known status
 * automatically — no manual list to maintain.
 */
export const DOWNLOAD_ENABLED_STATUSES = new Set(Object.keys(API_STATUS_MAP));
