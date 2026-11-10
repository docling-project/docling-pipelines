import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  // ── Notifications ──────────────────────────────────────────────────────────
  saveSuccess: {
    id: 'src.pages.Canvas.saveSuccess',
    defaultMessage: 'Flow saved successfully.',
  },
  saveError: {
    id: 'src.pages.Canvas.saveError',
    defaultMessage: 'Failed to save flow.',
  },
  runStartError: {
    id: 'src.pages.Canvas.runStartError',
    defaultMessage: 'Failed to start run.',
  },
  saveDetailsError: {
    id: 'src.pages.Canvas.saveDetailsError',
    defaultMessage: 'Failed to save flow details',
  },
  saveDetailsErrorSubtitle: {
    id: 'src.pages.Canvas.saveDetailsErrorSubtitle',
    defaultMessage: 'Please try again.',
  },

  // ── Breadcrumb actions ─────────────────────────────────────────────────────
  flowRunHistory: {
    id: 'src.pages.Canvas.flowRunHistory',
    defaultMessage: 'Flow run history',
  },
  aboutFlow: {
    id: 'src.pages.Canvas.aboutFlow',
    defaultMessage: 'About flow',
  },

  // ── Context menu ───────────────────────────────────────────────────────────
  edit: {
    id: 'src.pages.Canvas.edit',
    defaultMessage: 'Edit',
  },
  recommendNodes: {
    id: 'src.pages.Canvas.recommendNodes',
    defaultMessage: 'Recommend nodes',
  },
  delete: {
    id: 'src.pages.Canvas.delete',
    defaultMessage: 'Delete',
  },
  deleteLink: {
    id: 'src.pages.Canvas.deleteLink',
    defaultMessage: 'Delete link',
  },
  deleteCondition: {
    id: 'src.pages.Canvas.deleteCondition',
    defaultMessage: 'Delete condition',
  },
  editCondition: {
    id: 'src.pages.Canvas.editCondition',
    defaultMessage: 'Edit condition',
  },
  addCondition: {
    id: 'src.pages.Canvas.addCondition',
    defaultMessage: 'Add condition',
  },
  editLinkName: {
    id: 'src.pages.Canvas.editLinkName',
    defaultMessage: 'Edit link name',
  },

  // ── Toolbar: left bar ──────────────────────────────────────────────────────
  toolbarPalette: {
    id: 'src.pages.Canvas.toolbarPalette',
    defaultMessage: 'Palette',
  },
  toolbarPaletteTooltip: {
    id: 'src.pages.Canvas.toolbarPaletteTooltip',
    defaultMessage: 'Open palette to add operators',
  },
  toolbarUndo: {
    id: 'src.pages.Canvas.toolbarUndo',
    defaultMessage: 'Undo',
  },
  toolbarUndoTooltip: {
    id: 'src.pages.Canvas.toolbarUndoTooltip',
    defaultMessage: 'Undo last action',
  },
  toolbarRedo: {
    id: 'src.pages.Canvas.toolbarRedo',
    defaultMessage: 'Redo',
  },
  toolbarRedoTooltip: {
    id: 'src.pages.Canvas.toolbarRedoTooltip',
    defaultMessage: 'Redo last undone action',
  },
  toolbarCut: {
    id: 'src.pages.Canvas.toolbarCut',
    defaultMessage: 'Cut',
  },
  toolbarCutTooltip: {
    id: 'src.pages.Canvas.toolbarCutTooltip',
    defaultMessage: 'Cut selected nodes',
  },
  toolbarCopy: {
    id: 'src.pages.Canvas.toolbarCopy',
    defaultMessage: 'Copy',
  },
  toolbarCopyTooltip: {
    id: 'src.pages.Canvas.toolbarCopyTooltip',
    defaultMessage: 'Copy selected nodes',
  },
  toolbarPaste: {
    id: 'src.pages.Canvas.toolbarPaste',
    defaultMessage: 'Paste',
  },
  toolbarPasteTooltip: {
    id: 'src.pages.Canvas.toolbarPasteTooltip',
    defaultMessage: 'Paste copied nodes',
  },
  toolbarDeleteTooltip: {
    id: 'src.pages.Canvas.toolbarDeleteTooltip',
    defaultMessage: 'Delete selected nodes',
  },
  toolbarComment: {
    id: 'src.pages.Canvas.toolbarComment',
    defaultMessage: 'Comment',
  },
  toolbarCommentTooltip: {
    id: 'src.pages.Canvas.toolbarCommentTooltip',
    defaultMessage: 'Add comment',
  },
  toolbarFlowRunProperties: {
    id: 'src.pages.Canvas.toolbarFlowRunProperties',
    defaultMessage: 'Flow run properties',
  },
  toolbarFlowRunPropertiesTooltip: {
    id: 'src.pages.Canvas.toolbarFlowRunPropertiesTooltip',
    defaultMessage: 'Configure flow run properties',
  },
  toolbarZoomIn: {
    id: 'src.pages.Canvas.toolbarZoomIn',
    defaultMessage: 'Zoom In',
  },
  toolbarZoomInTooltip: {
    id: 'src.pages.Canvas.toolbarZoomInTooltip',
    defaultMessage: 'Zoom in',
  },
  toolbarZoomOut: {
    id: 'src.pages.Canvas.toolbarZoomOut',
    defaultMessage: 'Zoom Out',
  },
  toolbarZoomOutTooltip: {
    id: 'src.pages.Canvas.toolbarZoomOutTooltip',
    defaultMessage: 'Zoom out',
  },
  toolbarZoomToFit: {
    id: 'src.pages.Canvas.toolbarZoomToFit',
    defaultMessage: 'Zoom To Fit',
  },
  toolbarZoomToFitTooltip: {
    id: 'src.pages.Canvas.toolbarZoomToFitTooltip',
    defaultMessage: 'Fit to window',
  },

  // ── Toolbar: right bar ─────────────────────────────────────────────────────
  saving: {
    id: 'src.pages.Canvas.saving',
    defaultMessage: 'Saving',
  },
  validating: {
    id: 'src.pages.Canvas.validating',
    defaultMessage: 'Validating',
  },
  lastSaved: {
    id: 'src.pages.Canvas.lastSaved',
    defaultMessage: 'Last saved {date}',
  },
  toolbarSave: {
    id: 'src.pages.Canvas.toolbarSave',
    defaultMessage: 'Save',
  },
  toolbarSaveTooltip: {
    id: 'src.pages.Canvas.toolbarSaveTooltip',
    defaultMessage: 'Save Flow',
  },
  viewRun: {
    id: 'src.pages.Canvas.viewRun',
    defaultMessage: 'View run',
  },
  runFlow: {
    id: 'src.pages.Canvas.runFlow',
    defaultMessage: 'Run flow',
  },
  viewRunTooltip: {
    id: 'src.pages.Canvas.viewRunTooltip',
    defaultMessage: 'Return to running job',
  },
  runFlowTooltip: {
    id: 'src.pages.Canvas.runFlowTooltip',
    defaultMessage: 'Run pipeline',
  },
  validationDisabled: {
    id: 'src.pages.Canvas.validationDisabled',
    defaultMessage: 'Validation is disabled',
  },
  validationProblems: {
    id: 'src.pages.Canvas.validationProblems',
    defaultMessage: 'Validation problems',
  },
  noValidationProblems: {
    id: 'src.pages.Canvas.noValidationProblems',
    defaultMessage: 'No validation problems',
  },

  // ── Page states ────────────────────────────────────────────────────────────
  loadingCanvas: {
    id: 'src.pages.Canvas.loadingCanvas',
    defaultMessage: 'Loading pipeline canvas...',
  },
  flowLoadErrorTitle: {
    id: 'src.pages.Canvas.flowLoadErrorTitle',
    defaultMessage: 'Failed to load flow',
  },
  goToProjects: {
    id: 'src.pages.Canvas.goToProjects',
    defaultMessage: 'Go to Projects',
  },
  pipelineLoadErrorTitle: {
    id: 'src.pages.Canvas.pipelineLoadErrorTitle',
    defaultMessage: 'Failed to load pipeline',
  },
  pipelineLoadErrorSubtitle: {
    id: 'src.pages.Canvas.pipelineLoadErrorSubtitle',
    defaultMessage:
      'The pipeline definition could not be read. Please refresh the page or go back to Projects.',
  },
  canvasInitError: {
    id: 'src.pages.Canvas.canvasInitError',
    defaultMessage: 'Failed to initialize canvas. Please refresh the page.',
  },
  editModalTitle: {
    id: 'src.pages.Canvas.editModalTitle',
    defaultMessage: 'Edit flow details',
  },
});
