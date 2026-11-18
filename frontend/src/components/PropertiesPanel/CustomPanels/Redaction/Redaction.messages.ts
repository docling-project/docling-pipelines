import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  redactionRegex: {
    id: 'src.components.PropertiesPanel.CustomPanels.Redaction.redactionRegex',
    defaultMessage: 'Redaction pattern (regex or word)',
  },
  redactionRegexDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Redaction.redactionRegexDescription',
    defaultMessage: 'The pattern or word to be masked/redacted.',
  },
  redactionRegexPlaceholder: {
    id: 'src.components.PropertiesPanel.CustomPanels.Redaction.redactionRegexPlaceholder',
    defaultMessage: 'e.g. {pattern}',
  },
  maskingCharacter: {
    id: 'src.components.PropertiesPanel.CustomPanels.Redaction.maskingCharacter',
    defaultMessage: 'Masking character',
  },
  maskingCharacterDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Redaction.maskingCharacterDescription',
    defaultMessage: 'Single character used to replace each matched character.',
  },
});
