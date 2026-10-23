import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  provider: {
    id: 'src.components.PropertiesPanel.CustomPanels.IngestSource.provider',
    defaultMessage: 'Provider',
  },
  selectProvider: {
    id: 'src.components.PropertiesPanel.CustomPanels.IngestSource.selectProvider',
    defaultMessage: 'Select provider',
  },
  providerConfig: {
    id: 'src.components.PropertiesPanel.CustomPanels.IngestSource.providerConfig',
    defaultMessage: 'Provider configuration',
  },
  ingestionSettings: {
    id: 'src.components.PropertiesPanel.CustomPanels.IngestSource.ingestionSettings',
    defaultMessage: 'Ingestion settings',
  },
  ingestionSettingsDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.IngestSource.ingestionSettingsDescription',
    defaultMessage: 'Control how many files are ingested and which file types are included or excluded.',
  },
  maxFiles: {
    id: 'src.components.PropertiesPanel.CustomPanels.IngestSource.maxFiles',
    defaultMessage: 'Maximum files',
  },
  includeFilter: {
    id: 'src.components.PropertiesPanel.CustomPanels.IngestSource.includeFilter',
    defaultMessage: 'Include file types',
  },
  includeFilterPlaceholder: {
    id: 'src.components.PropertiesPanel.CustomPanels.IngestSource.includeFilterPlaceholder',
    defaultMessage: 'Select file types to include',
  },
  excludeFilter: {
    id: 'src.components.PropertiesPanel.CustomPanels.IngestSource.excludeFilter',
    defaultMessage: 'Exclude file types',
  },
  excludeFilterPlaceholder: {
    id: 'src.components.PropertiesPanel.CustomPanels.IngestSource.excludeFilterPlaceholder',
    defaultMessage: 'Select file types to exclude',
  },
  ignoreHiddenFiles: {
    id: 'src.components.PropertiesPanel.CustomPanels.IngestSource.ignoreHiddenFiles',
    defaultMessage: 'Ignore hidden files',
  },
  off: {
    id: 'src.components.PropertiesPanel.CustomPanels.IngestSource.off',
    defaultMessage: 'Off',
  },
  on: {
    id: 'src.components.PropertiesPanel.CustomPanels.IngestSource.on',
    defaultMessage: 'On',
  },
  filterConflict: {
    id: 'src.components.PropertiesPanel.CustomPanels.IngestSource.filterConflict',
    defaultMessage:
      'Conflict: {extensions} {count, plural, one {is} other {are}} in both include and exclude. '
      + 'These file types will be skipped.',
  },
  filterConflictExtension: {
    id: 'src.components.PropertiesPanel.CustomPanels.IngestSource.filterConflictExtension',
    description: 'A single file extension wrapped in locale-appropriate quotation marks',
    defaultMessage: '"{extension}"',
  },
  providerLabelFilesystem: {
    id: 'src.components.PropertiesPanel.CustomPanels.IngestSource.providerLabelFilesystem',
    defaultMessage: 'Local filesystem',
  },
  providerLabelWeb: {
    id: 'src.components.PropertiesPanel.CustomPanels.IngestSource.providerLabelWeb',
    defaultMessage: 'Web',
  },
  providerLabelCustom: {
    id: 'src.components.PropertiesPanel.CustomPanels.IngestSource.providerLabelCustom',
    defaultMessage: 'Custom loader',
  },
  providerDescriptionS3: {
    id: 'src.components.PropertiesPanel.CustomPanels.IngestSource.providerDescriptionS3',
    defaultMessage: 'Connect to an Amazon S3 bucket or any S3-compatible storage such as MinIO.',
  },
  providerDescriptionIbmCos: {
    id: 'src.components.PropertiesPanel.CustomPanels.IngestSource.providerDescriptionIbmCos',
    defaultMessage: 'Connect to an IBM Cloud Object Storage bucket using S3-compatible credentials.',
  },
  providerDescriptionSharepoint: {
    id: 'src.components.PropertiesPanel.CustomPanels.IngestSource.providerDescriptionSharepoint',
    defaultMessage:
      'Ingest documents from a Microsoft SharePoint document library using Azure AD app authentication.',
  },
  providerDescriptionOnedrive: {
    id: 'src.components.PropertiesPanel.CustomPanels.IngestSource.providerDescriptionOnedrive',
    defaultMessage: 'Ingest documents from a Microsoft OneDrive drive using Azure AD app authentication.',
  },
  providerDescriptionGoogleDrive: {
    id: 'src.components.PropertiesPanel.CustomPanels.IngestSource.providerDescriptionGoogleDrive',
    defaultMessage:
      'Ingest documents from a Google Drive folder using a service account or OAuth credentials.',
  },
  providerDescriptionBoxDriver: {
    id: 'src.components.PropertiesPanel.CustomPanels.IngestSource.providerDescriptionBoxDriver',
    defaultMessage: 'Ingest documents from a Box folder using a Box JWT service account credentials file.',
  },
  providerDescriptionFilesystem: {
    id: 'src.components.PropertiesPanel.CustomPanels.IngestSource.providerDescriptionFilesystem',
    defaultMessage: 'Ingest documents from one or more paths on the local filesystem.',
  },
  providerDescriptionWeb: {
    id: 'src.components.PropertiesPanel.CustomPanels.IngestSource.providerDescriptionWeb',
    defaultMessage: 'Crawl and ingest documents from one or more web URLs.',
  },
  providerDescriptionCustom: {
    id: 'src.components.PropertiesPanel.CustomPanels.IngestSource.providerDescriptionCustom',
    defaultMessage:
      'Use a custom LangChain-compatible loader class. Provide the class path and any required parameters.',
  },
});
