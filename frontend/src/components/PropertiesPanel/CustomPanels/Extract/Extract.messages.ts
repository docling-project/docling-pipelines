import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  textExtractionTitle: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.textExtractionTitle',
    defaultMessage: 'Text Extraction',
  },
  entityExtractionTitle: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityExtractionTitle',
    defaultMessage: 'Entity Extraction',
  },
  advancedTitle: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.advancedTitle',
    defaultMessage: 'Advanced',
  },
  off: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.off',
    defaultMessage: 'Off',
  },
  on: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.on',
    defaultMessage: 'On',
  },
  selectProvider: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.selectProvider',
    defaultMessage: 'Select provider',
  },
  textProvider: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.textProvider',
    defaultMessage: 'Text extraction provider',
  },
  textProviderDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.textProviderDescription',
    defaultMessage: 'Choose between local Docling processing or a remote Docling Serve instance.',
  },
  textProviderDoclingLibrary: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.textProviderDoclingLibrary',
    defaultMessage: 'Docling Library',
  },
  textProviderDoclingServe: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.textProviderDoclingServe',
    defaultMessage: 'Docling Serve',
  },
  vlmPipeline: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.vlmPipeline',
    defaultMessage: 'VLM pipeline',
  },
  vlmPipelineDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.vlmPipelineDescription',
    defaultMessage: 'Enable the Vision-Language Model pipeline for enhanced document extraction.',
  },
  vlmPreset: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.vlmPreset',
    defaultMessage: 'Preset',
  },
  vlmPresetDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.vlmPresetDescription',
    defaultMessage: "VLM preset name (e.g., 'granite_docling', 'fast').",
  },
  vlmEngine: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.vlmEngine',
    defaultMessage: 'Engine',
  },
  vlmEngineDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.vlmEngineDescription',
    defaultMessage: 'VLM engine.',
  },
  selectEngine: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.selectEngine',
    defaultMessage: 'Select engine',
  },
  vlmEngineTransformers: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.vlmEngineTransformers',
    defaultMessage: 'Transformers',
  },
  vlmEngineMlx: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.vlmEngineMlx',
    defaultMessage: 'MLX',
  },
  vlmEngineApi: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.vlmEngineApi',
    defaultMessage: 'API',
  },
  vlmEngineApiOllama: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.vlmEngineApiOllama',
    defaultMessage: 'API (Ollama)',
  },
  vlmEngineApiOpenai: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.vlmEngineApiOpenai',
    defaultMessage: 'API (OpenAI)',
  },
  vlmEngineApiWatsonx: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.vlmEngineApiWatsonx',
    defaultMessage: 'API (watsonx)',
  },
  vlmEngineApiLmstudio: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.vlmEngineApiLmstudio',
    defaultMessage: 'API (LM Studio)',
  },
  vlmEngineOptions: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.vlmEngineOptions',
    defaultMessage: 'Engine options (JSON)',
  },
  vlmEngineOptionsDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.vlmEngineOptionsDescription',
    defaultMessage: 'Engine-specific configuration (e.g. api_base, model_id, api_key).',
  },
  vlmEngineOptionsInvalid: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.vlmEngineOptionsInvalid',
    defaultMessage: 'Engine options must be a valid JSON object.',
  },
  asrPipeline: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.asrPipeline',
    defaultMessage: 'ASR pipeline',
  },
  asrPipelineDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.asrPipelineDescription',
    defaultMessage: 'Enable ASR (Automatic Speech Recognition) pipeline for audio/video extraction.',
  },
  asrModelId: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.asrModelId',
    defaultMessage: 'Model ID',
  },
  asrModelIdDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.asrModelIdDescription',
    defaultMessage:
      'ASR model name (e.g., whisper_turbo, whisper_small, whisper_medium). Valid values: whisper_tiny, whisper_small, whisper_medium, whisper_base, whisper_large, whisper_turbo, and their _mlx/_native variants.',
  },
  additionalFormats: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.additionalFormats',
    defaultMessage: 'Additional output formats',
  },
  additionalFormatsDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.additionalFormatsDescription',
    defaultMessage: 'Additional output formats to generate beyond the mandatory markdown format.',
  },
  formatHtml: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.formatHtml',
    defaultMessage: 'HTML',
  },
  formatJson: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.formatJson',
    defaultMessage: 'JSON',
  },
  formatText: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.formatText',
    defaultMessage: 'Plain text',
  },
  formatDoctags: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.formatDoctags',
    defaultMessage: 'DocTags',
  },
  formatDoclang: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.formatDoclang',
    defaultMessage: 'DocLang',
  },
  standardPipeline: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.standardPipeline',
    defaultMessage: 'Standard pipeline (GPU acceleration)',
  },
  standardPipelineDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.standardPipelineDescription',
    defaultMessage:
      'Enable GPU acceleration for PDF and image processing. Requires Maximum workers = 1 and Use processes = false. Cannot be combined with VLM Pipeline.',
  },
  acceleratorDevice: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.acceleratorDevice',
    defaultMessage: 'Accelerator device',
  },
  acceleratorDeviceDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.acceleratorDeviceDescription',
    defaultMessage:
      "GPU device for acceleration. Accepted values: 'mps' (Apple Silicon), 'cuda' (NVIDIA), 'cuda:index' (e.g. 'cuda:0'), 'xpu' (Intel). When omitted, the best available device is auto-detected via torch (CUDA -> MPS -> XPU).",
  },
  acceleratorNumThreads: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.acceleratorNumThreads',
    defaultMessage: 'Number of threads',
  },
  acceleratorNumThreadsDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.acceleratorNumThreadsDescription',
    defaultMessage: 'Number of CPU-side pipeline threads. Must be a positive integer. Defaults to 4 when not set.',
  },
  serveBaseUrl: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.serveBaseUrl',
    defaultMessage: 'Base URL',
  },
  serveBaseUrlDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.serveBaseUrlDescription',
    defaultMessage: 'Base URL of the Docling Serve API (e.g., http://0.0.0.0:5001)',
  },
  serveApiKey: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.serveApiKey',
    defaultMessage: 'API key',
  },
  serveApiKeyDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.serveApiKeyDescription',
    defaultMessage: 'API key for authenticating with the Docling Serve endpoint (if required).',
  },
  serveVerifySsl: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.serveVerifySsl',
    defaultMessage: 'Verify SSL',
  },
  serveVerifySslDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.serveVerifySslDescription',
    defaultMessage: "Verify the server's SSL certificate.",
  },
  serveDoOcr: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.serveDoOcr',
    defaultMessage: 'Enable OCR',
  },
  serveDoOcrDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.serveDoOcrDescription',
    defaultMessage: 'Run OCR on document pages. When enabled, exposes OCR engine and language settings.',
  },
  serveOcrEngine: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.serveOcrEngine',
    defaultMessage: 'OCR engine',
  },
  serveOcrEngineDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.serveOcrEngineDescription',
    defaultMessage: 'OCR engine to use. Leave empty to use the server default.',
  },
  serveOcrLanguages: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.serveOcrLanguages',
    defaultMessage: 'OCR languages',
  },
  serveOcrLanguagesDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.serveOcrLanguagesDescription',
    defaultMessage: 'List of language codes for OCR (e.g., en, fr). Leave unset to use the server default.',
  },
  serveOcrLanguagesHelperText: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.serveOcrLanguagesHelperText',
    defaultMessage: 'Press Enter or comma to add. Leave empty to use the server default.',
  },
  servePdfBackend: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.servePdfBackend',
    defaultMessage: 'PDF backend',
  },
  servePdfBackendDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.servePdfBackendDescription',
    defaultMessage: 'PDF parsing backend.',
  },
  selectBackend: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.selectBackend',
    defaultMessage: 'Select backend',
  },
  pdfBackendDlparseV2: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.pdfBackendDlparseV2',
    defaultMessage: 'dlparse_v2',
  },
  pdfBackendPypdfium2: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.pdfBackendPypdfium2',
    defaultMessage: 'pypdfium2',
  },
  serveImageExportMode: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.serveImageExportMode',
    defaultMessage: 'Image export mode',
  },
  serveImageExportModeDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.serveImageExportModeDescription',
    defaultMessage: 'How to export images found in the document.',
  },
  selectMode: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.selectMode',
    defaultMessage: 'Select mode',
  },
  imageExportModePlaceholder: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.imageExportModePlaceholder',
    defaultMessage: 'Placeholder',
  },
  imageExportModeEmbedded: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.imageExportModeEmbedded',
    defaultMessage: 'Embedded',
  },
  serveTableMode: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.serveTableMode',
    defaultMessage: 'Table mode',
  },
  serveTableModeDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.serveTableModeDescription',
    defaultMessage: 'Table extraction strategy. Leave empty to use the server default.',
  },
  serveTimeout: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.serveTimeout',
    defaultMessage: 'Timeout (seconds)',
  },
  serveTimeoutDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.serveTimeoutDescription',
    defaultMessage: 'Request timeout in seconds when calling Docling Serve.',
  },
  servePollInterval: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.servePollInterval',
    defaultMessage: 'Poll interval (seconds)',
  },
  servePollIntervalDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.servePollIntervalDescription',
    defaultMessage: 'Polling interval in seconds when waiting for async extraction results.',
  },
  serveMaxRetries: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.serveMaxRetries',
    defaultMessage: 'Maximum retries',
  },
  serveMaxRetriesDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.serveMaxRetriesDescription',
    defaultMessage: 'Maximum number of retries on transient failures.',
  },
  textDocColumn: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.textDocColumn',
    defaultMessage: 'Document content column',
  },
  textDocColumnDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.textDocColumnDescription',
    defaultMessage: 'Column name to store the extracted document content.',
  },
  entityProvider: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityProvider',
    defaultMessage: 'Entity extraction provider',
  },
  entityProviderDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityProviderDescription',
    defaultMessage: "Choose the entity extraction strategy. Select 'None' to skip entity extraction.",
  },
  entityProviderNone: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityProviderNone',
    defaultMessage: 'None',
  },
  entityProviderLitellm: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityProviderLitellm',
    defaultMessage: 'LiteLLM',
  },
  entityProviderWatsonx: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityProviderWatsonx',
    defaultMessage: 'watsonx',
  },
  entityProviderDocling: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityProviderDocling',
    defaultMessage: 'Docling',
  },
  entityOutputColumn: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityOutputColumn',
    defaultMessage: 'Output column',
  },
  entityOutputColumnDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityOutputColumnDescription',
    defaultMessage: 'Column name to store the extracted entities.',
  },
  entityModelId: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityModelId',
    defaultMessage: 'Model ID',
  },
  entityModelIdDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityModelIdDescription',
    defaultMessage: "LLM model identifier (e.g., 'ollama/llama3.2', 'openai/gpt-4o', 'ibm/granite-3-8b-instruct').",
  },
  entityApiBase: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityApiBase',
    defaultMessage: 'API base URL',
  },
  entityApiBaseDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityApiBaseDescription',
    defaultMessage: "Base URL for the LLM API endpoint (e.g., 'http://localhost:11434/v1').",
  },
  entityApiKey: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityApiKey',
    defaultMessage: 'API key',
  },
  entityApiKeyDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityApiKeyDescription',
    defaultMessage: 'API key for authenticating with the LLM provider.',
  },
  entityTemperature: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityTemperature',
    defaultMessage: 'Temperature',
  },
  entityTemperatureDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityTemperatureDescription',
    defaultMessage: 'Sampling temperature (0.0-1.0). Lower values produce more deterministic output.',
  },
  entityMaxTokens: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityMaxTokens',
    defaultMessage: 'Maximum tokens',
  },
  entityMaxTokensDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityMaxTokensDescription',
    defaultMessage: 'Maximum number of tokens to generate in the LLM response.',
  },
  entityWatsonxUrl: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityWatsonxUrl',
    defaultMessage: 'watsonx URL',
  },
  entityWatsonxUrlDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityWatsonxUrlDescription',
    defaultMessage: "watsonx.ai API endpoint URL (e.g., 'https://us-south.ml.cloud.ibm.com').",
  },
  entityWatsonxApiKeyDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityWatsonxApiKeyDescription',
    defaultMessage: 'API key for authenticating with IBM watsonx.',
  },
  entityContainerKind: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityContainerKind',
    defaultMessage: 'Container type',
  },
  entityContainerKindDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityContainerKindDescription',
    defaultMessage: 'Container type for the watsonx project or space.',
  },
  selectContainerType: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.selectContainerType',
    defaultMessage: 'Select container type',
  },
  entityContainerId: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityContainerId',
    defaultMessage: 'Container ID',
  },
  entityContainerIdDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityContainerIdDescription',
    defaultMessage: 'Container ID for the watsonx project or space.',
  },
  entityProjectId: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityProjectId',
    defaultMessage: 'Project ID',
  },
  entityProjectIdDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityProjectIdDescription',
    defaultMessage: 'watsonx project ID.',
  },
  entityDoclingVlmPipeline: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityDoclingVlmPipeline',
    defaultMessage: 'VLM pipeline configuration (JSON)',
  },
  entityDoclingVlmPipelineDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityDoclingVlmPipelineDescription',
    defaultMessage:
      "Custom VLM model configuration for Docling entity extraction. Requires 'model_type': 'inline' and an 'inline_model' with a HuggingFace 'repo_id'.",
  },
  entityDoclingVlmPipelineInvalid: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityDoclingVlmPipelineInvalid',
    defaultMessage: 'VLM pipeline configuration must be a valid JSON object.',
  },
  entityMaxDocChars: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityMaxDocChars',
    defaultMessage: 'Maximum document characters',
  },
  entityMaxDocCharsDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityMaxDocCharsDescription',
    defaultMessage: 'Maximum characters of document content sent for entity extraction per document.',
  },
  entityCustomSchema: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityCustomSchema',
    defaultMessage: 'Custom schema (JSON)',
  },
  entityCustomSchemaDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityCustomSchemaDescription',
    defaultMessage: 'JSON object defining a schema dictionary for structured entity extraction.',
  },
  entityCustomSchemaInvalid: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityCustomSchemaInvalid',
    defaultMessage: 'Custom schema must be a valid JSON object.',
  },
  entityExpandData: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityExpandData',
    defaultMessage: 'Expand entities into columns',
  },
  entityExpandDataDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.entityExpandDataDescription',
    defaultMessage: 'Expand extracted entity data into individual columns in the output table.',
  },
  maxWorkers: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.maxWorkers',
    defaultMessage: 'Maximum workers',
  },
  maxWorkersDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.maxWorkersDescription',
    defaultMessage: 'Maximum number of parallel workers for extraction (auto-detects based on CPU count if not specified).',
  },
  useProcesses: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.useProcesses',
    defaultMessage: 'Use processes',
  },
  useProcessesDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Extract.useProcessesDescription',
    defaultMessage: 'Use separate processes instead of threads for CPU-intensive tasks.',
  },
});
