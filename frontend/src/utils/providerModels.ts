/**
 * @file Provider-model helpers for properties panels.
 *
 * Contains frontend-only transformations applied to raw provider model API
 * responses before those models are rendered in operator configuration UIs.
 */

import type { ModelInfo } from '@/types';
import { EMBEDDINGS_PROVIDER, type EmbeddingsProvider } from '@/components/PropertiesPanel';

/**
 * Filter raw provider models for use in the Embeddings properties panel.
 *
 * Watsonx can return models for multiple capabilities, so this narrows the list
 * to models advertising the `embedding` capability. Other providers are passed
 * through unchanged.
 */
export const filterModelsForEmbeddingsPanel = (
  provider: EmbeddingsProvider,
  models: ModelInfo[]
): ModelInfo[] => {
  if (provider !== EMBEDDINGS_PROVIDER.WATSONX) {
    return models;
  }

  return models.filter((model) => model.functions.includes('embedding'));
};
