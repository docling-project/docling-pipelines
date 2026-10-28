import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  provider: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentClassifier.provider',
    defaultMessage: 'Provider',
  },
  selectProvider: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentClassifier.selectProvider',
    defaultMessage: 'Select provider',
  },
  providerConfigAccordion: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentClassifier.providerConfigAccordion',
    defaultMessage: 'Provider configuration',
  },
  providerConfigAccordionDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentClassifier.providerConfigAccordionDescription',
    defaultMessage:
      'Select the LLM provider used for classification and configure its connection settings.',
  },
  providerConfig: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentClassifier.providerConfig',
    defaultMessage: 'Provider configuration (JSON)',
  },
  classificationConfigAccordion: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentClassifier.classificationConfigAccordion',
    defaultMessage: 'Classification configuration',
  },
  classificationConfigDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentClassifier.classificationConfigDescription',
    defaultMessage:
      'Define the document types the model can classify into and set the minimum confidence '
      + 'score required to accept a result.',
  },
  documentTypes: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentClassifier.documentTypes',
    defaultMessage: 'Document types',
  },
  loadingDocumentTypes: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentClassifier.loadingDocumentTypes',
    defaultMessage: 'Loading document types...',
  },
  loadDocumentTypesError: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentClassifier.loadDocumentTypesError',
    defaultMessage: 'Failed to load document types. You can type them manually below.',
  },
  documentTypesFallbackPlaceholder: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentClassifier.documentTypesFallbackPlaceholder',
    defaultMessage: 'invoice, contract, report, email',
  },
  documentTypesPlaceholder: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentClassifier.documentTypesPlaceholder',
    defaultMessage: 'Select document types',
  },
  confidenceThreshold: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentClassifier.confidenceThreshold',
    defaultMessage: 'Confidence threshold (1–10)',
  },
  outputColumn: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentClassifier.outputColumn',
    defaultMessage: 'Output column',
  },
  includeConfidence: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentClassifier.includeConfidence',
    defaultMessage: 'Include confidence score',
  },
  includeReasoning: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentClassifier.includeReasoning',
    defaultMessage: 'Include reasoning',
  },
  off: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentClassifier.off',
    defaultMessage: 'Off',
  },
  on: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentClassifier.on',
    defaultMessage: 'On',
  },
  docColumn: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentClassifier.docColumn',
    defaultMessage: 'Document content column',
  },
});
