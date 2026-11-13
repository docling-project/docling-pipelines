/**
 * Node Suggestion feature constants.
 *
 * OPERATOR_SUCCESSORS maps each operator op-code to the set of op-codes that
 * are valid next steps. The NodeSuggestion overlay filters the palette to only
 * these ops before showing it to the user.
 *
 * Source of truth: the operator pipeline design spec — successor lists reflect
 * actual feature dependencies (requires / produces) between operators.
 *
 * Operators covered:
 *   ingest_source, extract_operator, lang_detect, doc_quality, ededup,
 *   redaction, pii_and_hap, sql_filter, chunker, embeddings, vectordb,
 *   document_set
 *
 * Operators not in this map (custom / unknown ops) fall back to ALL_OPS.
 */

import { NodeOperator } from './operators';

/**
 * Horizontal canvas-space offset (logical px) from a source node's right edge
 * to the left edge of the NodeSuggestion card. Applied before the zoom transform
 * in getNodeSuggestionLayout() so the card always sits a consistent distance away
 * regardless of the current zoom level.
 */
export const NODE_SUGGESTION_STEP_X = 200;

/** All op-codes present in operatorPalette.json — used as fallback for
 *  custom / unknown operators so the panel is always useful. */
const ALL_OPS = new Set([
  NodeOperator.INGEST_SOURCE,
  NodeOperator.EXTRACT,
  NodeOperator.ACL_OPERATOR,
  NodeOperator.DEDUPLICATION,
  NodeOperator.REDACTION,
  NodeOperator.READABILITY,
  NodeOperator.ML_ENRICHMENT,
  NodeOperator.LANG_DETECT,
  NodeOperator.DOC_QUALITY,
  NodeOperator.SQL_FILTER,
  NodeOperator.PII_AND_HAP,
  NodeOperator.CHUNKER,
  NodeOperator.EMBEDDINGS,
  NodeOperator.DOCUMENT_CLASSIFIER,
  NodeOperator.ENTITY_CURATION,
  NodeOperator.NOOP,
  NodeOperator.BRANCHING,
  NodeOperator.MERGING,
  NodeOperator.VECTORDB,
  NodeOperator.DOCUMENT_SET,
]);

export const OPERATOR_SUCCESSORS: Record<string, string[]> = {

  // ── Ingest ────────────────────────────────────────────────────────────────
  // Always the first operator. binary_content is consumed by extract_operator.
  [NodeOperator.INGEST_SOURCE]: [
    NodeOperator.EXTRACT,
  ],

  // ── Extract ───────────────────────────────────────────────────────────────
  // Requires: binary_content. Produces: content.
  [NodeOperator.EXTRACT]: [
    NodeOperator.LANG_DETECT,
    NodeOperator.DOC_QUALITY,
    NodeOperator.DEDUPLICATION,
    NodeOperator.REDACTION,
    NodeOperator.PII_AND_HAP,
    NodeOperator.SQL_FILTER,
    NodeOperator.CHUNKER,
  ],

  // ── Quality ───────────────────────────────────────────────────────────────

  // Requires: content. Produces: lang_name, lang_score.
  [NodeOperator.LANG_DETECT]: [
    NodeOperator.DOC_QUALITY,
    NodeOperator.DEDUPLICATION,
    NodeOperator.REDACTION,
    NodeOperator.PII_AND_HAP,
    NodeOperator.SQL_FILTER,
    NodeOperator.CHUNKER,
  ],

  // Requires: content. Produces: quality score columns.
  [NodeOperator.DOC_QUALITY]: [
    NodeOperator.LANG_DETECT,
    NodeOperator.DEDUPLICATION,
    NodeOperator.REDACTION,
    NodeOperator.PII_AND_HAP,
    NodeOperator.SQL_FILTER,
    NodeOperator.CHUNKER,
  ],

  // Deduplicates on content hash; no formal column requirement.
  [NodeOperator.DEDUPLICATION]: [
    NodeOperator.LANG_DETECT,
    NodeOperator.DOC_QUALITY,
    NodeOperator.REDACTION,
    NodeOperator.PII_AND_HAP,
    NodeOperator.SQL_FILTER,
    NodeOperator.CHUNKER,
  ],

  // Requires: content. Overwrites content in place.
  [NodeOperator.REDACTION]: [
    NodeOperator.CHUNKER,
    NodeOperator.DOC_QUALITY,
    NodeOperator.DEDUPLICATION,
    NodeOperator.SQL_FILTER,
  ],

  // Requires: content. Produces: pii_annotations, hap_annotations.
  [NodeOperator.PII_AND_HAP]: [
    NodeOperator.REDACTION,
    NodeOperator.SQL_FILTER,
    NodeOperator.CHUNKER,
  ],

  // No formal column requirement — rows removed based on SQL condition.
  [NodeOperator.SQL_FILTER]: [
    NodeOperator.CHUNKER,
    NodeOperator.REDACTION,
    NodeOperator.DOCUMENT_SET,
  ],

  // ── Functional ────────────────────────────────────────────────────────────

  // Requires: content. Produces: chunked_content, chunk_sequence_number.
  [NodeOperator.CHUNKER]: [
    NodeOperator.EMBEDDINGS,
  ],

  // Produces: embeddings, sparse_embeddings, doc_id_hash.
  [NodeOperator.EMBEDDINGS]: [
    NodeOperator.VECTORDB,
    NodeOperator.DOCUMENT_SET,
  ],

  // ── Terminal — no successors ──────────────────────────────────────────────

  // Requires: embeddings, doc_id_hash. Indexes in OpenSearch / Milvus / Weaviate.
  [NodeOperator.VECTORDB]: [],

  // Requires: id. Saves to document set.
  [NodeOperator.DOCUMENT_SET]: [],
};

/**
 * Returns the set of successor op-codes for a given source operator.
 * Falls back to ALL_OPS for custom / unknown operators not in the map.
 */
export function getSuccessorOps(sourceOp: string): Set<string> {
  const successors = OPERATOR_SUCCESSORS[sourceOp];
  if (successors === undefined) {return ALL_OPS;}
  return new Set(successors);
}
