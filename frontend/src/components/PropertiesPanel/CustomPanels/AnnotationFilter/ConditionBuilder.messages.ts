import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  // Field labels
  variable: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilder.variable',
    defaultMessage: 'Variable',
  },
  operator: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilder.operator',
    defaultMessage: 'Operator',
  },
  value: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilder.value',
    defaultMessage: 'Value',
  },
  startValue: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilder.startValue',
    defaultMessage: 'Start value',
  },
  endValue: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilder.endValue',
    defaultMessage: 'End value',
  },
  logicalOperator: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilder.logicalOperator',
    defaultMessage: 'Logical operator',
  },
  and: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilder.and',
    defaultMessage: 'AND',
  },
  or: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilder.or',
    defaultMessage: 'OR',
  },
  valueTrue: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilder.valueTrue',
    defaultMessage: 'True',
  },
  valueFalse: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilder.valueFalse',
    defaultMessage: 'False',
  },

  // Placeholders
  chooseVariable: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilder.chooseVariable',
    defaultMessage: 'Choose a variable',
  },
  chooseOperator: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilder.chooseOperator',
    defaultMessage: 'Choose an operator',
  },
  enterValue: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilder.enterValue',
    defaultMessage: 'Enter value',
  },
  enterMultipleValues: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilder.enterMultipleValues',
    defaultMessage: 'Enter comma-separated values',
  },
  enterJsonValue: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilder.enterJsonValue',
    defaultMessage: 'Enter JSON value',
  },

  // Helper texts
  datetimeHelper: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilder.datetimeHelper',
    defaultMessage: 'Format: YYYY-MM-DD HH:MM:SS (e.g., 2024-01-15 14:30:00)',
  },
  commaSeparatedHelper: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilder.commaSeparatedHelper',
    defaultMessage: 'Separate multiple values with commas (e.g., A,B,C)',
  },
  jsonHelper: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilder.jsonHelper',
    defaultMessage: 'Enter valid JSON format',
  },

  // Validation errors
  errorInvalidTimestamp: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilder.errorInvalidTimestamp',
    defaultMessage: 'Please enter a valid timestamp in YYYY-MM-DD HH:MM:SS format',
  },
  errorInvalidTimestampRange: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilder.errorInvalidTimestampRange',
    defaultMessage:
      'Please enter valid timestamps for both start and end values (YYYY-MM-DD HH:MM:SS)',
  },
  errorInvalidJson: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilder.errorInvalidJson',
    defaultMessage: 'Invalid JSON format',
  },

  // Tooltips / icon descriptions
  logicalOperatorTooltip: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilder.logicalOperatorTooltip',
    defaultMessage:
      'Select either the AND or OR conditional operator for processing your criteria list of SQL queries',
  },
  deleteCondition: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilder.deleteCondition',
    defaultMessage: 'Delete condition',
  },
  addCondition: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilder.addCondition',
    defaultMessage: 'Add condition',
  },

  // Loading / empty states
  loadingFeatures: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilder.loadingFeatures',
    defaultMessage: 'Loading features…',
  },
  noFeatures: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.ConditionBuilder.noFeatures',
    defaultMessage: 'No features available — connect an upstream node.',
  },
});
