/**
 * Flow Run Properties Constants
 *
 * Constants used in the Flow Run Properties Tearsheet component.
 */

import type { IntermediateDataStorageType } from '@/types';

/**
 * Flow property attribute names for flow_def global config.
 * These constants ensure consistency between frontend and backend property names.
 */
export const FLOW_PROPERTY_KEYS = {
  ENABLE_INCREMENTAL_PROCESSING: 'enableIncrementalProcessing',
  RETAIN_RECORDS_FOR_DELETED_DOCUMENTS: 'retainRecordsForDeletedDocuments',
  VALIDATE_FLOW: 'validateFlow',
  INTERMEDIATE_DATA_STORAGE: 'intermediateDataStorage',
} as const;

export interface StorageOption {
  id: IntermediateDataStorageType;
  text: string;
}
