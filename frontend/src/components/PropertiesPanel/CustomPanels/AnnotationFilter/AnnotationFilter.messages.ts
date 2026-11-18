import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  criteriaList: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.criteriaList',
    defaultMessage: 'Criteria list',
  },
  criteriaDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.criteriaDescription',
    defaultMessage:
      "List of SQL queries (not including the where clause). Examples: pii_bank_account >= 1, lang_score > 0.3, lang_name='en'",
  },
  availableFeatures: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.availableFeatures',
    defaultMessage: 'Available features',
  },
  featureName: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.featureName',
    defaultMessage: 'Feature name',
  },
  type: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.type',
    defaultMessage: 'Type',
  },
  condition: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.condition',
    defaultMessage: 'Condition',
  },
  addCriteria: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.addCriteria',
    defaultMessage: 'Add Criteria',
  },
  updateCriteria: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.updateCriteria',
    defaultMessage: 'Update Criteria',
  },
  expandView: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.expandView',
    defaultMessage: 'Expand view',
  },
  delete: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.delete',
    defaultMessage: 'Delete',
  },
  searchCriteria: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.searchCriteria',
    defaultMessage: 'Search criteria',
  },
  noFeaturesMessage: {
    id: 'src.components.PropertiesPanel.CustomPanels.AnnotationFilter.noFeaturesMessage',
    defaultMessage: 'No features available — connect an upstream node.',
  },
});
