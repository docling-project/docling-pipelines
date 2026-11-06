import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  expectedRedactions: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.expectedRedactions',
    defaultMessage: 'Redaction targets',
  },
  expectedRedactionsDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.expectedRedactionsDescription',
    defaultMessage: 'List of redaction types to perform (PII, HAP).',
  },
  expectedRedactionsPlaceholder: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.expectedRedactionsPlaceholder',
    defaultMessage: 'Select redaction targets',
  },
  piiList: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.piiList',
    defaultMessage: 'PII types to detect',
  },
  piiListDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.piiListDescription',
    defaultMessage: 'List of PII entity types to detect.',
  },
  piiListPlaceholder: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.piiListPlaceholder',
    defaultMessage: 'Select PII types',
  },
  redaction: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.redaction',
    defaultMessage: 'Enable PII redaction',
  },
  redactionDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.redactionDescription',
    defaultMessage: 'Enable PII redaction in document content.',
  },
  redactionCharacter: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.redactionCharacter',
    defaultMessage: 'PII masking character',
  },
  redactionCharacterDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.redactionCharacterDescription',
    defaultMessage: 'Character used to mask PII.',
  },
  piiThreshold: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.piiThreshold',
    defaultMessage: 'PII confidence threshold',
  },
  piiThresholdDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.piiThresholdDescription',
    defaultMessage: 'Confidence threshold for PII detection (0.0 - 1.0).',
  },
  displayPii: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.displayPii',
    defaultMessage: 'Display PII values',
  },
  displayPiiDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.displayPiiDescription',
    defaultMessage: 'Include actual PII values in output columns for debugging.',
  },
  hapRedaction: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.hapRedaction',
    defaultMessage: 'Enable HAP redaction',
  },
  hapRedactionDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.hapRedactionDescription',
    defaultMessage: 'Enable HAP redaction in document content.',
  },
  hapRedactionCharacter: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.hapRedactionCharacter',
    defaultMessage: 'HAP masking character',
  },
  hapRedactionCharacterDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.hapRedactionCharacterDescription',
    defaultMessage: 'Character used to mask HAP.',
  },
  hapThreshold: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.hapThreshold',
    defaultMessage: 'HAP confidence threshold',
  },
  hapThresholdDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.hapThresholdDescription',
    defaultMessage: 'Confidence threshold for HAP detection (0.0 - 1.0).',
  },
  off: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.off',
    defaultMessage: 'Off',
  },
  on: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.on',
    defaultMessage: 'On',
  },
  provider: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.provider',
    defaultMessage: 'Provider',
  },
  providerDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.providerDescription',
    defaultMessage: 'Detection provider (watsonx, litellm).',
  },
  selectProvider: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.selectProvider',
    defaultMessage: 'Select provider',
  },
  providerConfigAccordion: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.providerConfigAccordion',
    defaultMessage: 'Provider configuration',
  },
  providerConfigAccordionDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.providerConfigAccordionDescription',
    defaultMessage:
      'Select the LLM provider used for detection and configure its connection settings.',
  },
  providerConfig: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.providerConfig',
    defaultMessage: 'Provider configuration (JSON)',
  },
  providerConfigDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.PiiAndHap.providerConfigDescription',
    defaultMessage: 'Provider-specific configuration JSON.',
  },
});
