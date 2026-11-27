/**
 * @file Chunk size range validation for the `chunker` operator.
 *
 * Pure helpers shared by the Chunker panel (inline message) and the Save-button
 * gating logic, so both always agree on what "invalid" means.
 */

import { isOutOfRange } from '../shared/rangeValidation';
import { CHUNK_SIZE_RANGE, CHUNKER_DEFAULTS, type ChunkSizeRange, type ChunkType } from './constants';

/** Returns the supported chunk_size range, or undefined when chunk size is not used (semantic). */
export function getChunkSizeRange(chunkType: ChunkType): ChunkSizeRange | undefined {
  return CHUNK_SIZE_RANGE[chunkType];
}

/**
 * True when `chunkSize` is outside the range supported by `chunkType`.
 * Always false for chunk types that do not use chunk_size.
 */
export function isChunkSizeOutOfRange(chunkType: ChunkType, chunkSize: unknown): boolean {
  const range = getChunkSizeRange(chunkType);
  if (!range || chunkSize === undefined || chunkSize === null) { return false; }
  return isOutOfRange(chunkSize as number | string, range.min, range.max);
}

/** Validates raw chunker property values (as returned by `controller.getPropertyValues()`). */
export function hasInvalidChunkSize(propertyValues: Record<string, unknown>): boolean {
  const chunkType = (propertyValues['chunk_type'] as ChunkType | undefined) ?? CHUNKER_DEFAULTS.CHUNK_TYPE;
  return isChunkSizeOutOfRange(chunkType, propertyValues['chunk_size']);
}
