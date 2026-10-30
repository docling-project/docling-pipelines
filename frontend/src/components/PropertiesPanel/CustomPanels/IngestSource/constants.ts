/**
 * Attribute key names for the `ingest_source` operator.
 *
 * These must match the backend attribute keys returned by
 * `IngestSourceOperator.get_metadata()["attributes"]`.
 * Used as the `name` argument to `controller.getPropertyValue()` /
 * `controller.updatePropertyValue()` throughout the panel.
 */
export const INGEST_SOURCE_ATTRIBUTE = {
  /** Storage provider identifier — e.g. "s3", "ibm_cos", "sharepoint" */
  PROVIDER: 'provider',
  /** Provider-specific configuration */
  PROVIDER_CONFIG: 'provider_config',
  /** Maximum number of files to ingest */
  MAX_FILES: 'max_files',
  /** Comma-separated file extensions to include */
  INCLUDE_FILTER: 'include_filter',
  /** Comma-separated file extensions to exclude */
  EXCLUDE_FILTER: 'exclude_filter',
  /** Skip files starting with '.' (hidden files) */
  IGNORE_HIDDEN_FILES: 'ignore_hidden_files',
} as const;

/**
 * Custom loader provider value.
 * UI falls back to the generic JSON TextArea for connection parameters.
 */
export const CUSTOM_PROVIDER = 'custom';

/**
 * Brand-name display labels for third-party providers, keyed by backend
 * provider value. Brand names are intentionally not translated; generic
 * providers (filesystem, web, custom) use message descriptors instead.
 */
export const PROVIDER_BRAND_LABELS: Record<string, string> = {
  s3: 'Amazon S3',
  ibm_cos: 'IBM Cloud Object Storage',
  sharepoint: 'Microsoft SharePoint',
  onedrive: 'Microsoft OneDrive',
  google_drive: 'Google Drive',
  box_driver: 'Box',
};

/**
 * Union type of all valid `ingest_source` attribute key strings.
 */
export type IngestSourceAttributeKey =
  typeof INGEST_SOURCE_ATTRIBUTE[keyof typeof INGEST_SOURCE_ATTRIBUTE];

/**
 * Supported file extensions for `include_filter` and `exclude_filter`.
 * Matches OperatorConstants.FileExtensions from backend.
 */
export const SUPPORTED_FILE_EXTENSIONS = [
  // Documents
  'pdf',
  'docx',
  'pptx',
  'xlsx',
  // Text & Markup
  'txt',
  'md',
  'html',
  // Images
  'png',
  'jpeg',
  'jpg',
  'tiff',
  'tif',
  'bmp',
  'webp',
  'gif',
  'jfif',
  // Audio
  'wav',
  'mp3',
  'm4a',
  'aac',
  'ogg',
  'flac',
  // Video
  'mp4',
  'avi',
  'mov',
] as const;
