import React, { useEffect, useState } from 'react';
import {
  ComposedModal,
  ModalHeader,
  ModalBody,
  ModalFooter,
  Button,
  InlineLoading,
  InlineNotification,
} from '@carbon/react';
import { CheckmarkFilled, ErrorFilled } from '@carbon/icons-react';
import { useIntl } from 'react-intl';
import { useAppDispatch } from '@/hooks/useAppDispatch';
import type { Project } from '@/types';
import { createProject, createFlow, getProjects } from '@/services/api';
import * as projectMapper from '@/services/api/mappers/project-mapper';
import * as flowMapper from '@/services/api/mappers/flow-mapper';
import { setProject } from '@/slices/projectsSlice';
import { setFlow } from '@/slices/flowSlice';
import { buildFlowDefinition } from '@/lib/helpers/flow';
import { generateRoute } from '@/config';
import { messages } from './SampleProjectModal.messages';
import styles from './SampleProjectModal.module.scss';

const PROJECT_NAME = 'Default_Docling_Pipeline_Project';
const FLOW_NAME = 'Sample_Ingestion_Flow';

type StepStatus = 'idle' | 'loading' | 'done' | 'error';

interface Step {
  label: string;
  status: StepStatus;
}

interface SampleProjectModalProps {
  /** Controls whether the modal is visible. */
  readonly open: boolean;
  /** Called when the user cancels or closes on error. */
  readonly onClose: () => void;
  /** Called automatically after both steps succeed — receives the canvas URL. */
  readonly onSuccess: (canvasUrl: string) => void;
}

/**
 * Progress overlay for the "Get started with sample data" tile.
 *
 * Runs project + flow creation in sequence, showing per-step status.
 * Redirects to the canvas automatically on success — no user confirmation needed.
 * On error, shows an inline notification and a Close button.
 */
export function SampleProjectModal({
  open,
  onClose,
  onSuccess,
}: SampleProjectModalProps): React.JSX.Element {
  const intl = useIntl();
  const dispatch = useAppDispatch();

  const [steps, setSteps] = useState<Step[]>([
    { label: intl.formatMessage(messages.stepCreatingProject), status: 'idle' },
    { label: intl.formatMessage(messages.stepCreatingSampleFlow), status: 'idle' },
  ]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const isRunning = steps.some((s) => s.status === 'loading');
  const hasError = steps.some((s) => s.status === 'error');

  function setStepStatus(index: number, status: StepStatus): void {
    setSteps((prev) =>
      prev.map((s, i) => (i === index ? { ...s, status } : s))
    );
  }

  async function runSetup(): Promise<void> {
    try {
      // Step 1 — find existing project or create a new one
      setStepStatus(0, 'loading');
      let project: Project;

      const listRes = await getProjects({ name: PROJECT_NAME, limit: 1 });
      const existing = listRes.data.projects.find((p) => p.name === PROJECT_NAME);

      if (existing) {
        project = projectMapper.fromResponse(existing);
        setSteps((prev) =>
          prev.map((s, i) => (i === 0 ? { ...s, label: intl.formatMessage(messages.stepUsingExistingProject) } : s))
        );
      } else {
        const projectRes = await createProject(
          projectMapper.toCreateRequest({ name: PROJECT_NAME, description: '', tags: [] })
        );
        project = projectMapper.fromResponse(projectRes.data);
      }
      dispatch(setProject({ projectId: project.id, project }));
      setStepStatus(0, 'done');

      // Step 2 — build a unique flow name and index name from a single timestamp,
      // e.g. Sample_Ingestion_Flow_20250130_143022
      setStepStatus(1, 'loading');
      const now = new Date();
      const pad = (n: number): string => String(n).padStart(2, '0');
      const timestamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
      const flowName = `${FLOW_NAME}_${timestamp}`;
      const indexName = `sample_flow_index_${timestamp}`;

      setSteps((prev) =>
        prev.map((s, i) => (i === 1 ? { ...s, label: intl.formatMessage(messages.stepCreatingFlowNamed, { name: flowName }) } : s))
      );

      // Fetch sample nodes from the public asset and stamp the vectordb index_name
      // so each sample flow gets a unique OpenSearch index.
      const sampleRes = await fetch('/ui/samples/samplePipeline.json');
      const sampleFlowNodes = (await sampleRes.json()) as Array<Record<string, unknown>>;
      const stampedNodes = structuredClone(sampleFlowNodes);
      const vectordbNode = stampedNodes.find((n) => n['op'] === 'vectordb');
      if (vectordbNode) {
        ((vectordbNode['parameters'] as Record<string, unknown>)['provider_config'] as Record<string, unknown>)['index_name'] = indexName;
      }

      const definition = buildFlowDefinition(flowName, '', stampedNodes);
      const flowRes = await createFlow(
        flowMapper.toCreateRequest(
          { name: flowName, description: '', tags: [] },
          project.id,
          definition
        )
      );
      const flowRow = flowMapper.fromResponse(flowRes.data);
      dispatch(setFlow({ flowId: flowRow.flow_id, flow: flowRow }));
      dispatch(setProject({ projectId: project.id, project: { ...project, flowCount: project.flowCount + 1 } }));
      setStepStatus(1, 'done');

      // Auto-redirect — no button click needed
      onSuccess(generateRoute.canvas(flowRes.data.flow_id ?? '', project.id));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : intl.formatMessage(messages.genericError);
      setErrorMessage(msg);
      setSteps((prev) =>
        prev.map((s) => (s.status === 'loading' ? { ...s, status: 'error' } : s))
      );
    }
  }

  // Reset state and start setup every time the modal opens.
  // runSetup is intentionally excluded from deps — it reads only stable
  // references (dispatch, onSuccess) and must not re-run on re-renders.
  useEffect(() => {
    if (!open) {return;}
    setSteps([
      { label: intl.formatMessage(messages.stepCreatingProject), status: 'idle' },
      { label: intl.formatMessage(messages.stepCreatingSampleFlow), status: 'idle' },
    ]);
    setErrorMessage(null);
    void runSetup();
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <ComposedModal
      open={open}
      onClose={onClose}
      size="sm"
      preventCloseOnClickOutside={isRunning}
      containerClassName={styles.modal}
    >
      <ModalHeader
        title={intl.formatMessage(messages.modalTitle)}
        buttonOnClick={hasError ? onClose : undefined}
      />

      <ModalBody className={styles.body}>
        <p className={styles.description}>
          {intl.formatMessage(messages.description)}
        </p>

        <ul className={styles.stepList}>
          {steps.map((step, index) => (
            <li key={index} className={styles.stepItem}>
              <span className={styles.stepIcon}>
                {step.status === 'loading' && (
                  <InlineLoading className={styles.spinner} />
                )}
                {step.status === 'done' && (
                  <CheckmarkFilled size={20} className={styles.iconDone} />
                )}
                {step.status === 'error' && (
                  <ErrorFilled size={20} className={styles.iconError} />
                )}
                {step.status === 'idle' && (
                  <span className={styles.iconIdle} />
                )}
              </span>
              <span className={styles.stepLabel}>{step.label}</span>
            </li>
          ))}
        </ul>

        {hasError && errorMessage && (
          <InlineNotification
            kind="error"
            title={intl.formatMessage(messages.errorTitle)}
            subtitle={errorMessage}
            lowContrast
            hideCloseButton
            className={styles.notification}
          />
        )}
      </ModalBody>

      {/* Footer is only shown on error — during loading and on success there is nothing to click */}
      {hasError && (
        <ModalFooter className={styles.footer}>
          <Button kind="secondary" onClick={onClose} className={styles.footerBtn}>
            {intl.formatMessage(messages.close)}
          </Button>
        </ModalFooter>
      )}
    </ComposedModal>
  );
}
