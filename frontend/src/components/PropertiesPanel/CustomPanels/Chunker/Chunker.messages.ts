import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  useDoclingServe: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.useDoclingServe',
    defaultMessage: 'Use Docling Serve (remote)',
  },
  useDoclingServeDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.useDoclingServeDescription',
    defaultMessage:
      'Route chunking to a remote Docling Serve API. When enabled, Chunk type is set to \'hybrid\' '
      + '(recommended) but can still be changed. Provider configuration must include at minimum an api_base URL.',
  },
  off: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.off',
    defaultMessage: 'Off',
  },
  on: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.on',
    defaultMessage: 'On',
  },
  providerConfig: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.providerConfig',
    defaultMessage: 'Docling Serve configuration (JSON)',
  },
  providerConfigDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.providerConfigDescription',
    defaultMessage:
      'Docling Serve connection settings as a JSON object. At minimum provide api_base. E.g. {example}',
  },
  chunkType: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.chunkType',
    defaultMessage: 'Chunk type',
  },
  chunkTypeDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.chunkTypeDescription',
    defaultMessage: 'The strategy used to split document text into chunks.',
  },
  selectChunkType: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.selectChunkType',
    defaultMessage: 'Select chunk type',
  },
  chunkTypeSimple: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.chunkTypeSimple',
    defaultMessage: 'Simple',
  },
  chunkTypeSemantic: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.chunkTypeSemantic',
    defaultMessage: 'Semantic',
  },
  chunkTypeHybrid: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.chunkTypeHybrid',
    defaultMessage: 'Hybrid (Docling)',
  },
  chunkSize: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.chunkSize',
    defaultMessage: 'Chunk size',
  },
  chunkSizeTokensDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.chunkSizeTokensDescription',
    defaultMessage: 'Chunk size in tokens (100–2048).',
  },
  chunkSizeCharsDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.chunkSizeCharsDescription',
    defaultMessage: 'Chunk size in characters (500–5000).',
  },
  chunkOverlap: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.chunkOverlap',
    defaultMessage: 'Chunk overlap',
  },
  chunkOverlapDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.chunkOverlapDescription',
    defaultMessage: 'Number of characters/tokens shared between consecutive chunks (0–512).',
  },
  chunkOverlapPercentage: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.chunkOverlapPercentage',
    defaultMessage: 'Chunk overlap percentage',
  },
  chunkOverlapPercentageDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.chunkOverlapPercentageDescription',
    defaultMessage:
      'Overlap expressed as a percentage of Chunk size (0–40). Values above 20 produce a warning.',
  },
  doclingTokenizer: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.doclingTokenizer',
    defaultMessage: 'Docling tokenizer',
  },
  doclingTokenizerDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.doclingTokenizerDescription',
    defaultMessage: 'HuggingFace tokenizer model used for Docling chunking.',
  },
  semanticEmbeddingsModel: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.semanticEmbeddingsModel',
    defaultMessage: 'Semantic embeddings model',
  },
  semanticEmbeddingsModelDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.semanticEmbeddingsModelDescription',
    defaultMessage: 'Ollama model used to generate embeddings in semantic chunking.',
  },
  semanticEmbeddingsModelPlaceholder: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.semanticEmbeddingsModelPlaceholder',
    defaultMessage: 'e.g. nomic-embed-text',
  },
  semanticEmbeddingsModelRequired: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.semanticEmbeddingsModelRequired',
    defaultMessage: 'Embeddings model is required for semantic chunking.',
  },
  breakpointThresholdType: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.breakpointThresholdType',
    defaultMessage: 'Breakpoint threshold type',
  },
  breakpointThresholdTypeDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.breakpointThresholdTypeDescription',
    defaultMessage: 'Method used to determine semantic chunk boundaries.',
  },
  selectThresholdType: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.selectThresholdType',
    defaultMessage: 'Select threshold type',
  },
  thresholdTypePercentile: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.thresholdTypePercentile',
    defaultMessage: 'Percentile',
  },
  thresholdTypeStandardDeviation: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.thresholdTypeStandardDeviation',
    defaultMessage: 'Standard Deviation',
  },
  thresholdTypeInterquartile: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.thresholdTypeInterquartile',
    defaultMessage: 'Interquartile',
  },
  thresholdTypeGradient: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.thresholdTypeGradient',
    defaultMessage: 'Gradient',
  },
  breakpointThresholdAmount: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.breakpointThresholdAmount',
    defaultMessage: 'Breakpoint threshold amount',
  },
  breakpointThresholdAmountDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.breakpointThresholdAmountDescription',
    defaultMessage:
      'Threshold value for the selected breakpoint type (e.g., 95.0 for 95th percentile).',
  },
  retainOriginalContent: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.retainOriginalContent',
    defaultMessage: 'Retain original content',
  },
  retainOriginalContentDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.retainOriginalContentDescription',
    defaultMessage: 'Keep the original content column after chunking.',
  },
  summarizationAccordion: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.summarizationAccordion',
    defaultMessage: 'Summarization',
  },
  summarizationAccordionDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.summarizationAccordionDescription',
    defaultMessage:
      'When enabled, an LLM generates a concise summary for each chunk after splitting. '
      + 'Select a provider and configure its connection settings below.',
  },
  summarization: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.summarization',
    defaultMessage: 'Enable summarization',
  },
  summarizationDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.summarizationDescription',
    defaultMessage: 'Generate a summary for each chunk using LiteLLM or watsonx.',
  },
  provider: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.provider',
    defaultMessage: 'Provider',
  },
  selectProvider: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.selectProvider',
    defaultMessage: 'Select provider',
  },
  summarizationConfig: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.summarizationConfig',
    defaultMessage: 'Summarization configuration (JSON)',
  },
  summarizationConfigDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Chunker.summarizationConfigDescription',
    defaultMessage: 'Summarization configuration as a JSON object. E.g. {example}',
  },
});
