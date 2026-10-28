import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  provider: {
    id: 'src.components.PropertiesPanel.CustomPanels.Embeddings.provider',
    defaultMessage: 'Provider',
  },
  selectProvider: {
    id: 'src.components.PropertiesPanel.CustomPanels.Embeddings.selectProvider',
    defaultMessage: 'Select provider',
  },
  apiBase: {
    id: 'src.components.PropertiesPanel.CustomPanels.Embeddings.apiBase',
    defaultMessage: 'API base URL',
  },
  apiKey: {
    id: 'src.components.PropertiesPanel.CustomPanels.Embeddings.apiKey',
    defaultMessage: 'API key',
  },
  modelId: {
    id: 'src.components.PropertiesPanel.CustomPanels.Embeddings.modelId',
    defaultMessage: 'Model ID',
  },
  modelIdWatsonxDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Embeddings.modelIdWatsonxDescription',
    defaultMessage: 'Model identifier for IBM watsonx.ai (e.g., \'ibm/slate-30m-english-rtrvr\').',
  },
  loadingModels: {
    id: 'src.components.PropertiesPanel.CustomPanels.Embeddings.loadingModels',
    defaultMessage: 'Loading provider models...',
  },
  loadModelsError: {
    id: 'src.components.PropertiesPanel.CustomPanels.Embeddings.loadModelsError',
    defaultMessage: 'Failed to load provider models. Enter a model ID manually.',
  },
  selectModel: {
    id: 'src.components.PropertiesPanel.CustomPanels.Embeddings.selectModel',
    defaultMessage: 'Select model',
  },
  watsonxUrl: {
    id: 'src.components.PropertiesPanel.CustomPanels.Embeddings.watsonxUrl',
    defaultMessage: 'Watsonx URL',
  },
  containerKind: {
    id: 'src.components.PropertiesPanel.CustomPanels.Embeddings.containerKind',
    defaultMessage: 'Container type',
  },
  selectContainerType: {
    id: 'src.components.PropertiesPanel.CustomPanels.Embeddings.selectContainerType',
    defaultMessage: 'Select container type',
  },
  containerId: {
    id: 'src.components.PropertiesPanel.CustomPanels.Embeddings.containerId',
    defaultMessage: 'Container ID',
  },
  advanced: {
    id: 'src.components.PropertiesPanel.CustomPanels.Embeddings.advanced',
    defaultMessage: 'Advanced',
  },
  overlapRatio: {
    id: 'src.components.PropertiesPanel.CustomPanels.Embeddings.overlapRatio',
    defaultMessage: 'Overlap ratio',
  },
  tokenLimit: {
    id: 'src.components.PropertiesPanel.CustomPanels.Embeddings.tokenLimit',
    defaultMessage: 'Token limit',
  },
});
