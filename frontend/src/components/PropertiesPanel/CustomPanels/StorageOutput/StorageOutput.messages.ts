import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  destinationConfigTitle: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.destinationConfigTitle',
    defaultMessage: 'Destination configuration',
  },
  outputFormatTitle: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.outputFormatTitle',
    defaultMessage: 'Output format',
  },
  outputStructureTitle: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.outputStructureTitle',
    defaultMessage: 'Output structure',
  },
  off: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.off',
    defaultMessage: 'Off',
  },
  on: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.on',
    defaultMessage: 'On',
  },
  mode: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.mode',
    defaultMessage: 'Mode',
  },
  selectMode: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.selectMode',
    defaultMessage: 'Select mode',
  },
  modeProcessedContent: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.modeProcessedContent',
    defaultMessage: 'Processed content',
  },
  modeRefetchOriginal: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.modeRefetchOriginal',
    defaultMessage: 'Refetch original',
  },
  modeComprehensiveExport: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.modeComprehensiveExport',
    defaultMessage: 'Comprehensive export',
  },
  provider: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.provider',
    defaultMessage: 'Provider',
  },
  selectProvider: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.selectProvider',
    defaultMessage: 'Select provider',
  },
  credentials: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.credentials',
    defaultMessage: 'Credentials',
  },
  credentialsInvalid: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.credentialsInvalid',
    defaultMessage: 'Credentials must be a valid JSON object or a vault:// reference.',
  },
  rootPath: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.rootPath',
    defaultMessage: 'Root path',
  },
  createDirs: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.createDirs',
    defaultMessage: 'Create intermediate directories',
  },
  accessKey: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.accessKey',
    defaultMessage: 'Access key',
  },
  secretKey: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.secretKey',
    defaultMessage: 'Secret key',
  },
  bucket: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.bucket',
    defaultMessage: 'Bucket',
  },
  keyPrefix: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.keyPrefix',
    defaultMessage: 'Key prefix',
  },
  endpointUrl: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.endpointUrl',
    defaultMessage: 'Endpoint URL',
  },
  region: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.region',
    defaultMessage: 'Region',
  },
  verifyExpectedBucketOwner: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.verifyExpectedBucketOwner',
    defaultMessage: 'Verify expected bucket owner',
  },
  contentTypeMap: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.contentTypeMap',
    defaultMessage: 'Content type map',
  },
  boxCredentialsPath: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.boxCredentialsPath',
    defaultMessage: 'Credentials file path',
  },
  boxFolderId: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.boxFolderId',
    defaultMessage: 'Folder ID',
  },
  clientId: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.clientId',
    defaultMessage: 'Client ID',
  },
  clientSecret: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.clientSecret',
    defaultMessage: 'Client secret',
  },
  tenantId: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.tenantId',
    defaultMessage: 'Tenant ID',
  },
  spDriveId: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.spDriveId',
    defaultMessage: 'Drive ID',
  },
  folderPath: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.folderPath',
    defaultMessage: 'Folder path',
  },
  graphApiVersion: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.graphApiVersion',
    defaultMessage: 'Graph API version',
  },
  selectVersion: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.selectVersion',
    defaultMessage: 'Select version',
  },
  gdFolderId: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.gdFolderId',
    defaultMessage: 'Folder ID',
  },
  gdDriveId: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.gdDriveId',
    defaultMessage: 'Shared drive ID',
  },
  serviceAccountJsonPath: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.serviceAccountJsonPath',
    defaultMessage: 'Service account JSON path',
  },
  gdCredentialsPath: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.gdCredentialsPath',
    defaultMessage: 'OAuth2 credentials path',
  },
  tokenPath: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.tokenPath',
    defaultMessage: 'Token cache path',
  },
  scopes: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.scopes',
    defaultMessage: 'OAuth2 scopes',
  },
  scopesHelperText: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.scopesHelperText',
    defaultMessage: 'Press Enter or comma to add a scope.',
  },
  chunkSizeMb: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.chunkSizeMb',
    defaultMessage: 'Upload chunk size (MB)',
  },
  contentFormat: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.contentFormat',
    defaultMessage: 'Content format',
  },
  selectFormat: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.selectFormat',
    defaultMessage: 'Select format',
  },
  formatMd: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.formatMd',
    defaultMessage: 'Markdown (.md)',
  },
  formatTxt: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.formatTxt',
    defaultMessage: 'Plain text (.txt)',
  },
  formatJson: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.formatJson',
    defaultMessage: 'JSON (.json)',
  },
  includeMetadataSidecar: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.includeMetadataSidecar',
    defaultMessage: 'Include metadata sidecar',
  },
  structureType: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.structureType',
    defaultMessage: 'Structure type',
  },
  selectStructure: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.selectStructure',
    defaultMessage: 'Select structure',
  },
  structureFlat: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.structureFlat',
    defaultMessage: 'Flat',
  },
  structureHierarchical: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.structureHierarchical',
    defaultMessage: 'Hierarchical',
  },
  pathTemplate: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.pathTemplate',
    defaultMessage: 'Path template',
  },
  overwriteExisting: {
    id: 'src.components.PropertiesPanel.CustomPanels.StorageOutput.overwriteExisting',
    defaultMessage: 'Overwrite existing files',
  },
});
