import { describe, it, expect } from 'vitest';
import { filterModelsForEmbeddingsPanel } from '@/utils/providerModels';
import { EMBEDDINGS_PROVIDER } from '@/components/PropertiesPanel/CustomPanels/Embeddings';
import type { ModelInfo } from '@/types';

const embeddingModel: ModelInfo = {
  model_id: 'ibm/slate-125m-english-rtrvr',
  description: 'Embedding model',
  functions: ['embedding'],
  embedding_dimension: 768,
};

const generationModel: ModelInfo = {
  model_id: 'meta-llama/llama-3-70b',
  description: 'Generation model',
  functions: ['text_generation'],
  embedding_dimension: null,
};

const models: ModelInfo[] = [embeddingModel, generationModel];

describe('filterModelsForEmbeddingsPanel', () => {
  it('non-watsonx provider returns full list unchanged', () => {
    const result = filterModelsForEmbeddingsPanel(EMBEDDINGS_PROVIDER.LITELLM, models);
    expect(result).toEqual(models);
  });

  it('watsonx with models having embedding function returns filtered list', () => {
    const result = filterModelsForEmbeddingsPanel(EMBEDDINGS_PROVIDER.WATSONX, models);
    expect(result).toHaveLength(1);
    expect(result[0]?.model_id).toBe('ibm/slate-125m-english-rtrvr');
  });

  it('watsonx with no embedding models returns empty list', () => {
    const result = filterModelsForEmbeddingsPanel(EMBEDDINGS_PROVIDER.WATSONX, [generationModel]);
    expect(result).toHaveLength(0);
  });
});
