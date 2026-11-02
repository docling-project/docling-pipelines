import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  title: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilderTearsheet.title',
    defaultMessage: 'Criteria',
  },
  description: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilderTearsheet.description',
    defaultMessage:
      'Add list of SQL queries (not including the where clause). Examples: pii_bank_account >= 1, lang_score > 0.3',
  },
  close: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilderTearsheet.close',
    defaultMessage: 'Close',
  },
  cancel: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilderTearsheet.cancel',
    defaultMessage: 'Cancel',
  },
  save: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilderTearsheet.save',
    defaultMessage: 'Save',
  },
  criteriaMode: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilderTearsheet.criteriaMode',
    defaultMessage: 'Criteria mode',
  },
  simple: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilderTearsheet.simple',
    defaultMessage: 'Simple',
  },
  advanced: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilderTearsheet.advanced',
    defaultMessage: 'Advanced',
  },
  advancedPlaceholder: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilderTearsheet.advancedPlaceholder',
    defaultMessage: 'Enter SQL expression (e.g. pii_bank_account >= 1 AND lang_score > 0.3)',
  },
  switchToAdvancedConfirm: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilderTearsheet.switchToAdvancedConfirm',
    defaultMessage:
      'Switching to Advanced will overwrite the previously saved Simple condition. Do you want to continue?',
  },
  switchToSimpleConfirm: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilderTearsheet.switchToSimpleConfirm',
    defaultMessage: 'Switching to Simple will overwrite the Advanced expression. Do you want to continue?',
  },
  continue: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilderTearsheet.continue',
    defaultMessage: 'Continue',
  },
});
