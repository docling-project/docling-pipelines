/**
 * @file VectorDB provider-config helpers for properties panels.
 */

/**
 * True when provider_config selects Milvus GPU mode: `vector_mode` is "gpu", or
 * `vector_mode` is unset and `index_type` starts with "GPU_" (the backend infers the
 * mode from the index type the same way).
 */
export function isMilvusGpuMode(providerConfig: Record<string, unknown>): boolean {
  const { vector_mode: vectorMode, index_type: indexType } = providerConfig;
  if (vectorMode) { return vectorMode === 'gpu'; }
  return typeof indexType === 'string' && indexType.startsWith('GPU_');
}
