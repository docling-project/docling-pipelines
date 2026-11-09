import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  mergeType: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.mergeType',
    defaultMessage: 'Merge type',
  },
  mergeTypeHint: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.mergeTypeHint',
    defaultMessage: 'Select how to merge data from multiple inputs',
  },
  mergeRowsLabel: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.mergeRowsLabel',
    defaultMessage: 'Combine rows: Merge rows from all tables, one after another',
  },
  mergeColumnsLabel: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.mergeColumnsLabel',
    defaultMessage: 'Combine columns: Merge columns from all tables row by row',
  },
  columnMergeOptionTitle: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.columnMergeOptionTitle',
    defaultMessage: 'Column merge option',
  },
  selectJoinType: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.selectJoinType',
    defaultMessage: 'Select join type',
  },
  columnOptionInnerJoin: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.columnOptionInnerJoin',
    defaultMessage: 'Inner join - combine all matching rows',
  },
  columnOptionFullOuter: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.columnOptionFullOuter',
    defaultMessage: 'Full outer - includes all rows from all datasets',
  },
  columnNoteTitle: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.columnNoteTitle',
    defaultMessage: 'Note:',
  },
  columnNoteSubtitle: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.columnNoteSubtitle',
    defaultMessage: 'Combining columns requires a common key column across all input branches.',
  },
  previewButton: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.previewButton',
    defaultMessage: 'Preview with sample data',
  },
  close: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.close',
    defaultMessage: 'Close',
  },
  previewTearsheetTitle: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.previewTearsheetTitle',
    defaultMessage: 'Merge Preview',
  },
  previewTearsheetDesc: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.previewTearsheetDesc',
    defaultMessage: 'Preview of how the merge type works with sample data',
  },
  previewDropdownTitle: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.previewDropdownTitle',
    defaultMessage: 'Merge type',
  },
  previewDropdownLabel: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.previewDropdownLabel',
    defaultMessage: 'Merge type',
  },
  previewRows: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.previewRows',
    defaultMessage: 'Merges rows from all tables, one after another',
  },
  previewInnerJoin: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.previewInnerJoin',
    defaultMessage: 'Inner join - combine all matching rows',
  },
  previewFullOuter: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.previewFullOuter',
    defaultMessage: 'Full outer - includes all rows from all datasets',
  },
  previewRowsNote: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.previewRowsNote',
    defaultMessage: 'When combining rows, columns that only exist in one branch will appear as Null in the merged result.',
  },
  previewDisclaimer: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.previewDisclaimer',
    defaultMessage: 'The preview uses sample data to illustrate the merge behaviour. Actual results depend on your data.',
  },
  diagramAriaLabel: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.diagramAriaLabel',
    defaultMessage: 'Merge diagram',
  },
  inputFromBranch1: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.inputFromBranch1',
    defaultMessage: 'Input from Branch 1',
  },
  inputFromBranch2: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.inputFromBranch2',
    defaultMessage: 'Input from Branch 2',
  },
  mergedTableTitle: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.mergedTableTitle',
    defaultMessage: 'Merged Table',
  },
  headerDocId: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.headerDocId',
    defaultMessage: 'Doc ID',
  },
  headerName: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.headerName',
    defaultMessage: 'Name',
  },
  headerAuthor: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.headerAuthor',
    defaultMessage: 'Author',
  },
  headerLanguage: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.headerLanguage',
    defaultMessage: 'Language',
  },
  headerQuality: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.headerQuality',
    defaultMessage: 'Quality',
  },
  headerNameLinkname: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.headerNameLinkname',
    defaultMessage: 'Name_linkname',
  },
  outputFeaturesCount: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.outputFeaturesCount',
    defaultMessage: 'Output: {count, plural, one {# feature} other {# features}}',
  },
  incomingLinks: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.incomingLinks',
    defaultMessage: 'Incoming links',
  },
  sourceNode: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.sourceNode',
    defaultMessage: 'Source Node',
  },
  linkName: {
    id: 'src.components.PropertiesPanel.CustomPanels.Merging.linkName',
    defaultMessage: 'Link Name',
  },
});
