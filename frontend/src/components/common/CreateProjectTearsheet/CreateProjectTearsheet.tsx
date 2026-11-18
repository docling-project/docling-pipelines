import React, { useState } from 'react';
import type { CreateProjectFormValues } from '@/types';
import { useAppSelector } from '@/hooks';
import { selectProjectsArray } from '@/selectors';
import {
  Button,
  ComposedModal,
  InlineLoading,
  ModalHeader,
  ModalBody,
  ModalFooter,
  ProgressIndicator,
  ProgressStep,
  TextInput,
  TextArea,
} from '@carbon/react';
import { useIntl } from 'react-intl';
import { TagInput } from '../TagInput';
import { messages } from './CreateProjectTearsheet.messages';
import styles from './CreateProjectTearsheet.module.scss';

/**
 * Form values collected on step 2 (flow details, optional).
 * @internal — not exported; consumed only by {@link CreateProjectTearsheet}.
 */
interface FlowFormValues {
  /** Human-readable flow name. */
  flowName: string;
  /** Optional description for the flow. */
  flowDescription: string;
  /** Zero or more tag strings attached to the flow. */
  flowTags: string[];
}

/**
 * Props for {@link CreateProjectTearsheet}.
 */
interface CreateProjectTearsheetProps {
  /** Controls whether the tearsheet is visible. */
  readonly open: boolean;
  /** Called when the user closes or cancels the tearsheet. Form state is reset automatically. */
  readonly onClose: () => void;
  /**
   * Called with the validated form values when the user clicks Create on step 2.
   * Must return a Promise — the tearsheet uses it to show a loading state on the
   * Create button and to close only after the API calls resolve.
   *
   * @param project - Filled project form values from step 1.
   * @param flow    - Filled flow form values from step 2 (may be empty if user skipped).
   */
  readonly onSubmit: (project: CreateProjectFormValues, flow: FlowFormValues) => Promise<void>;
}

/** Empty initial state for the project form. */
const EMPTY_PROJECT: CreateProjectFormValues = { name: '', description: '', tags: [] };

/** Empty initial state for the flow form. */
const EMPTY_FLOW: FlowFormValues = { flowName: '', flowDescription: '', flowTags: [] };

/**
 * Two-step modal tearsheet for creating a new project and optionally a first flow.
 *
 * - **Step 1 — Create project**: Name (required), Description (optional), Tags (optional).
 * - **Step 2 — Create flow** (optional): same fields scoped to a flow.
 *
 * A custom horizontal progress indicator shows the current step using Carbon SVG icons
 * (`InProgress`, `CheckmarkOutline`, `Incomplete`). The footer uses a 2-1-1 CSS grid:
 * Cancel (2fr) | Back (1fr) | Next → Create (1fr).
 *
 * Form state is reset on close or cancel.
 */
export function CreateProjectTearsheet({
  open,
  onClose,
  onSubmit,
}: CreateProjectTearsheetProps): React.JSX.Element {
  const intl = useIntl();
  const [currentStep, setCurrentStep] = useState(0);
  const [project, setProject] = useState<CreateProjectFormValues>(EMPTY_PROJECT);
  const [flow, setFlow] = useState<FlowFormValues>(EMPTY_FLOW);
  const [nameInvalid, setNameInvalid] = useState(false);
  const [nameDuplicate, setNameDuplicate] = useState(false);
  /** Tracks whether a create API call is in-flight. Disables footer buttons while true. */
  const [submitting, setSubmitting] = useState(false);

  const projectsArray = useAppSelector(selectProjectsArray);

  /** Resets all form state and delegates to the `onClose` prop. */
  const handleClose = (): void => {
    setProject(EMPTY_PROJECT);
    setFlow(EMPTY_FLOW);
    setNameInvalid(false);
    setNameDuplicate(false);
    setCurrentStep(0);
    onClose();
  };

  /**
   * Checks whether the current name value already exists in the cached project list.
   * Called on blur and as a fallback on Next click.
   */
  const checkDuplicate = (name: string): boolean => {
    const trimmed = name.trim();
    if (!trimmed) { return false; }
    return projectsArray.some(
      (p) => p.name.trim().toLowerCase() === trimmed.toLowerCase()
    );
  };

  /**
   * Fired when the Name field loses focus.
   * Runs the duplicate check immediately so the user sees the error before clicking Next.
   */
  const handleNameBlur = (): void => {
    if (project.name.trim() && checkDuplicate(project.name)) {
      setNameDuplicate(true);
    }
  };

  /**
   * Fallback validation on Next click.
   * Catches the empty-name case and any duplicate that slipped through
   * (e.g. blur not fired, cache updated between blur and click).
   */
  const handleNext = (): void => {
    const trimmed = project.name.trim();
    if (!trimmed) {
      setNameInvalid(true);
      return;
    }
    if (checkDuplicate(trimmed)) {
      setNameDuplicate(true);
      return;
    }
    setCurrentStep(1);
  };

  /** Returns from step 2 to step 1 without clearing form values. */
  const handleBack = (): void => {
    setCurrentStep(0);
  };

  /** Calls `onSubmit` with the collected values; closes only after the promise resolves. */
  const handleSubmit = (): void => {
    setSubmitting(true);
    onSubmit(project, flow)
      .then(() => {
        handleClose();
      })
      .catch(() => {
        // parent is responsible for surfacing the error; tearsheet stays open
      })
      .finally(() => {
        setSubmitting(false);
      });
  };

  return (
    <ComposedModal
      open={open}
      onClose={handleClose}
      size="sm"
      preventCloseOnClickOutside
      containerClassName={styles.modal}
    >
      <ModalHeader
        title={intl.formatMessage(messages.modalTitle)}
        buttonOnClick={handleClose}
        className={styles.modalHeader}
      />

      <ModalBody className={styles.modalBody}>

        {/* ── Progress indicator ── */}
        <ProgressIndicator
          currentIndex={currentStep}
          className={styles.progressBar}
          spaceEqually
        >
          <ProgressStep label={intl.formatMessage(messages.stepProject)} />
          <ProgressStep label={intl.formatMessage(messages.stepFlow)} secondaryLabel={intl.formatMessage(messages.stepFlowOptional)} />
        </ProgressIndicator>

        {/* ── Step 1: Project details ── */}
        {currentStep === 0 && (
          <div className={styles.formContent}>
            <h2 className={styles.formHeading}>{intl.formatMessage(messages.projectHeading)}</h2>

            <TextInput
              id="project-name"
              labelText={intl.formatMessage(messages.nameLabel)}
              placeholder={intl.formatMessage(messages.namePlaceholder)}
              value={project.name}
              onChange={(e) => {
                setProject((prev) => ({ ...prev, name: e.target.value }));
                setNameInvalid(false);
                setNameDuplicate(false);
              }}
              onBlur={handleNameBlur}
              invalid={nameInvalid || nameDuplicate}
              invalidText={
                nameDuplicate
                  ? intl.formatMessage(messages.nameDuplicate)
                  : intl.formatMessage(messages.nameRequired)
              }
            />

            <TextArea
              id="project-description"
              labelText={intl.formatMessage(messages.descriptionLabel)}
              placeholder={intl.formatMessage(messages.descriptionPlaceholder)}
              value={project.description}
              onChange={(e) => { setProject((prev) => ({ ...prev, description: e.target.value })); }}
              rows={4}
            />

            <TagInput
              id="project-tags"
              tags={project.tags}
              onChange={(tags) => { setProject((prev) => ({ ...prev, tags })); }}
            />
          </div>
        )}

        {/* ── Step 2: Flow details (optional) ── */}
        {currentStep === 1 && (
          <div className={styles.formContent}>
            <h2 className={styles.formHeading}>{intl.formatMessage(messages.flowHeading)}</h2>

            <TextInput
              id="flow-name"
              labelText={intl.formatMessage(messages.nameLabel)}
              placeholder={intl.formatMessage(messages.namePlaceholder)}
              value={flow.flowName}
              onChange={(e) => { setFlow((prev) => ({ ...prev, flowName: e.target.value })); }}
            />

            <TextArea
              id="flow-description"
              labelText={intl.formatMessage(messages.descriptionLabel)}
              placeholder={intl.formatMessage(messages.descriptionPlaceholder)}
              value={flow.flowDescription}
              onChange={(e) => { setFlow((prev) => ({ ...prev, flowDescription: e.target.value })); }}
              rows={4}
            />

            <TagInput
              id="flow-tags"
              tags={flow.flowTags}
              onChange={(tags) => { setFlow((prev) => ({ ...prev, flowTags: tags })); }}
              helperText={intl.formatMessage(messages.tagsHelperText)}
            />
          </div>
        )}

      </ModalBody>

      {/* ── Footer: 2-1-1 grid — Cancel | Back | Next/Create ── */}
      <ModalFooter className={styles.footer}>
        <Button kind="ghost" onClick={handleClose} disabled={submitting} className={styles.footerCancel}>
          {intl.formatMessage(messages.cancel)}
        </Button>
        <Button
          kind="secondary"
          onClick={handleBack}
          disabled={currentStep === 0 || submitting}
          className={styles.footerBack}
        >
          {intl.formatMessage(messages.back)}
        </Button>
        {currentStep === 0 ? (
          <Button
            kind="primary"
            onClick={handleNext}
            disabled={!project.name.trim() || nameDuplicate}
            className={styles.footerPrimary}
          >
            {intl.formatMessage(messages.next)}
          </Button>
        ) : (
          <Button
            kind="primary"
            onClick={handleSubmit}
            disabled={submitting}
            className={styles.footerPrimary}
          >
            {submitting ? <InlineLoading description={intl.formatMessage(messages.creating)} /> : intl.formatMessage(messages.create)}
          </Button>
        )}
      </ModalFooter>
    </ComposedModal>
  );
}
