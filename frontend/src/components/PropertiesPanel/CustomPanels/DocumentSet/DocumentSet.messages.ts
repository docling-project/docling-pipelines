import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  documentSetName: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentSet.documentSetName',
    defaultMessage: 'Document set name',
  },
  documentSetNameDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentSet.documentSetNameDescription',
    defaultMessage: 'Name of the document set to create or update.',
  },
  requiredParameter: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentSet.requiredParameter',
    defaultMessage: 'This is a required parameter.',
  },
  description: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentSet.description',
    defaultMessage: 'Document set description',
  },
  descriptionHelp: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentSet.descriptionHelp',
    defaultMessage: 'Human-readable description of the document set.',
  },
  descriptionPlaceholder: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentSet.descriptionPlaceholder',
    defaultMessage: 'Processed research papers',
  },
  metadata: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentSet.metadata',
    defaultMessage: 'Metadata (JSON)',
  },
  metadataDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentSet.metadataDescription',
    defaultMessage: 'Arbitrary JSON object stored as document set metadata.',
  },
  documentSetId: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentSet.documentSetId',
    defaultMessage: 'Document set ID',
  },
  documentSetIdDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentSet.documentSetIdDescription',
    defaultMessage: 'UUID of an existing document set to update instead of creating a new one.',
  },
  databasePath: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentSet.databasePath',
    defaultMessage: 'Database path',
  },
  databasePathDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentSet.databasePathDescription',
    defaultMessage: 'File path for the DuckDB database.',
  },
  dataBackend: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentSet.dataBackend',
    defaultMessage: 'Data backend',
  },
  dataBackendDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentSet.dataBackendDescription',
    defaultMessage: 'Data store backend for PyArrow table data.',
  },
  selectBackend: {
    id: 'src.components.PropertiesPanel.CustomPanels.DocumentSet.selectBackend',
    defaultMessage: 'Select backend',
  },
});
