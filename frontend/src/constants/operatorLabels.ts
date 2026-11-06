/**
 * Operator labels and descriptions
 * Used in the properties panel for display
 */

import { NodeOperator } from './operators';

export interface OperatorLabel {
  label: string;
  description: string;
}

/**
 * Labels and descriptions for each operator type
 * Provides user-friendly display text for the properties panel
 */
export const OPERATOR_LABELS: Record<string, OperatorLabel> = {
  [NodeOperator.INGEST_SOURCE]: {
    label: 'Ingest data',
    description:
      'Ingest documents from local and remote storage sources, such as S3, IBM COS, SharePoint, OneDrive, Google Drive.',
  },
  [NodeOperator.EXTRACT]: {
    label: 'Extract Content',
    description:
      'Extract text, tables, and entities from documents using Docling. Supports PDF, DOCX, PPTX, and other document formats.',
  },
  [NodeOperator.CHUNKER]: {
    label: 'Chunk Text',
    description:
      'Split documents into smaller chunks for processing. Supports various chunking strategies including token-based and semantic chunking.',
  },
  [NodeOperator.EMBEDDINGS]: {
    label: 'Generate Embeddings',
    description:
      'Generate vector embeddings for text chunks using various embedding models. Supports OpenAI, Ollama, and other providers.',
  },
  [NodeOperator.DEDUPLICATION]: {
    label: 'De-duplicator',
    description:
      'Exact deduplication operator that removes duplicate documents based on content hash.',
  },
  [NodeOperator.VECTORDB]: {
    label: 'Store in Vector Database',
    description:
      'Store document embeddings in a vector database for similarity search. Supports OpenSearch, Milvus, Weaviate, and other vector stores.',
  },
  [NodeOperator.DOCUMENT_SET]: {
    label: 'Document Set',
    description:
      'Manage and organize documents into logical sets for processing and retrieval.',
  },
  [NodeOperator.DOCUMENT_CLASSIFIER]: {
    label: 'Document Classifier',
    description:
      'Classify documents into predefined types using an LLM (litellm or watsonx providers). Default provider is litellm configured for Ollama.',
  },
  [NodeOperator.LANG_DETECT]: {
    label: 'Language Annotator',
    description:
      'Detect the language of each document and annotate with ISO 639-1 language code and confidence score.',
  },
  [NodeOperator.SQL_FILTER]: {
    label: 'Annotation filter',
    description:
      'Filter documents based on added annotations to streamline processing and ensure relevant content is ingested into the language model.',
  },
  [NodeOperator.REDACTION]: {
    label: 'Redaction',
    description:
      'Redact text matching a word or regex pattern from document content and report the number of redactions made.',
  },
  [NodeOperator.READABILITY]: {
    label: 'Readability',
    description:
      'Compute readability scores for document content (Flesch-Kincaid, Gunning Fog, SMOG, Coleman-Liau, and more).',
  },
  [NodeOperator.ENTITY_CURATION]: {
    label: 'Entity Curation',
    description:
      'Transform extracted entities into structured, curated data using document class schemas.',
  },
  [NodeOperator.ML_ENRICHMENT]: {
    label: 'ML Text Enrichment',
    description:
      'Computes 30+ text quality features including word counts, character ratios, duplication metrics, and special pattern detection for data quality assessment.',
  },
  [NodeOperator.DOC_QUALITY]: {
    label: 'Document Quality',
    description:
      'Compute text quality metrics per document, such as word counts, symbol ratios, formatting patterns, and content quality indicators',
  },
  [NodeOperator.ACL_OPERATOR]: {
    label: 'ACL Extraction',
    description:
      'Extract access control lists (ACLs) from documents. Uses credentials and provider information from the upstream Ingest node. Adds an allowed_users column with effective permissions.',
  },
  [NodeOperator.NOOP]: {
    label: 'No-op',
    description:
      'Pass-through operator that forwards input data unchanged. Use it to test flow structure, introduce timing delays, or isolate problems between operators.',
  },
  [NodeOperator.PII_AND_HAP]: {
    label: 'PII and HAP Annotator',
    description:
      'Detect and optionally redact Personally Identifiable Information (PII) and Hate, Abuse, and Profanity (HAP) content using LLM-based detection.',
  },
  [NodeOperator.BRANCHING]: {
    label: 'Branching',
    description:
      'Branch the flow into multiple streams so documents undergo different processing steps based on conditions you define. Connect output links and set a condition on each.',
  },
  [NodeOperator.MERGING]: {
    label: 'Merging',
    description:
      'Merge two or more branched streams back into a single stream. Connect input links from upstream branches into this node.',
  },
  [NodeOperator.STORAGE_OUTPUT]: {
    label: 'Storage Output',
    description:
      'Write pipeline documents to a storage destination. Supports processed content, original binary re-fetch, and comprehensive export modes.',
  },
};

/**
 * Get label and description for an operator.
 * Returns defaults if the operator is not found.
 */
export function getOperatorLabel(operatorName: string): OperatorLabel {
  return (
    OPERATOR_LABELS[operatorName] ?? {
      label: operatorName,
      description: `Configure ${operatorName} operator parameters`,
    }
  );
}
