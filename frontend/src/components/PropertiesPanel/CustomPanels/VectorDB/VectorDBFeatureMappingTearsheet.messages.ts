import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  editTitle: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.editTitle',
    defaultMessage: 'Edit feature mappings',
  },
  addTitle: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.addTitle',
    defaultMessage: 'Add feature mappings',
  },
  description: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.description',
    defaultMessage: 'Configure the target {resourceLabel} and map pipeline features to its columns',
  },
  save: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.save',
    defaultMessage: 'Save',
  },
  cancel: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.cancel',
    defaultMessage: 'Cancel',
  },
  errorTitle: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.errorTitle',
    defaultMessage: 'Error',
  },
  loadResourcesError: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.loadResourcesError',
    defaultMessage: 'Failed to load available resources. Check your connection settings and try again.',
  },
  loadResourceDetailsError: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.loadResourceDetailsError',
    defaultMessage: 'Failed to load details for the selected resource. Try again or choose a different one.',
  },
  loadNewResourceMappingsError: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.loadNewResourceMappingsError',
    defaultMessage: 'Failed to load feature mappings for new resource. Try again.',
  },
  reloadMappingsError: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.reloadMappingsError',
    defaultMessage: 'Failed to reload feature mappings. Try again.',
  },
  readOnlyNotice: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.readOnlyNotice',
    defaultMessage:
      '{similarityLabel}{hasEngine, select, true {, engine,} other {}} and dimension size are fixed by the existing {resourceLabel} and cannot be changed.',
  },
  searchOrSelectResource: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.searchOrSelectResource',
    defaultMessage: 'Search or select a {resourceLabel} name',
  },
  enterNewResourceName: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.enterNewResourceName',
    defaultMessage: 'Enter a new {resourceLabel} name',
  },
  newResourceNamePlaceholder: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.newResourceNamePlaceholder',
    defaultMessage: 'e.g. my_{resourceLabel}',
  },
  engine: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.engine',
    defaultMessage: 'Engine',
  },
  selectEngine: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.selectEngine',
    defaultMessage: 'Select engine',
  },
  dimensionSize: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.dimensionSize',
    defaultMessage: 'Dimension size',
  },
  selectSimilarity: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.selectSimilarity',
    defaultMessage: 'Select {similarityLabel}',
  },
  sparseVectorLabel: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.sparseVectorLabel',
    defaultMessage: 'Compute sparse vectors for hybrid search',
  },
  createNew: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.createNew',
    defaultMessage: 'Create new',
  },
  nameRequired: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.nameRequired',
    defaultMessage: 'Name is required',
  },
  nameMustStartWithLetter: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.nameMustStartWithLetter',
    defaultMessage: 'Name must start with a letter or underscore',
  },
  nameOnlyLettersNumbersUnderscores: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.nameOnlyLettersNumbersUnderscores',
    defaultMessage: 'Only letters, numbers, and underscores are allowed',
  },
  nameAlreadyExists: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.nameAlreadyExists',
    defaultMessage: '"{name}" already exists — choose a different name',
  },
  unsupportedTitle: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.unsupportedTitle',
    defaultMessage: 'Unsupported {resourceLabel}',
  },
  unsupportedCollectionSubtitle: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.unsupportedCollectionSubtitle',
    defaultMessage:
      'The selected {resourceLabel} is not compatible since it does not have a vector field configured. Select another {resourceLabel} or create a new one.',
  },
  unsupportedIndexSubtitle: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.unsupportedIndexSubtitle',
    defaultMessage:
      'The selected {resourceLabel} is not compatible since it does not have a dense vector field with indexing enabled on that field. Select another {resourceLabel} or create a new one.',
  },
  metricL2: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.metricL2',
    defaultMessage: 'Euclidean distance',
  },
  metricL2Milvus: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.metricL2Milvus',
    defaultMessage: 'Euclidean distance (L2)',
  },
  metricCosine: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.metricCosine',
    defaultMessage: 'Cosine similarity',
  },
  metricInnerProduct: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.metricInnerProduct',
    defaultMessage: 'Inner product',
  },
  metricIPMilvus: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.metricIPMilvus',
    defaultMessage: 'Inner product (IP)',
  },
  metricBM25: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.metricBM25',
    defaultMessage: 'BM25 (sparse)',
  },
  engineFaiss: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.engineFaiss',
    defaultMessage: 'Faiss',
  },
  engineLucene: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.engineLucene',
    defaultMessage: 'Lucene',
  },
  engineNmslib: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.engineNmslib',
    defaultMessage: 'NMSLIB',
  },
  engineJvector: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.engineJvector',
    defaultMessage: 'jVector',
  },
  spaceTypeLabel: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.spaceTypeLabel',
    defaultMessage: 'Space type',
  },
  metricTypeLabel: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.metricTypeLabel',
    defaultMessage: 'Metric type',
  },
  resourceIndex: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.resourceIndex',
    defaultMessage: 'index',
  },
  resourceCollection: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.VectorDBFeatureMappingTearsheet.resourceCollection',
    defaultMessage: 'collection',
  },
});
