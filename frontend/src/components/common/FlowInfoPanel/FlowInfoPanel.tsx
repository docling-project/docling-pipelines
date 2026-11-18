import React from 'react';
import { Button, Tag } from '@carbon/react';
import { Close, Edit } from '@carbon/icons-react';
import { useIntl } from 'react-intl';
import { messages } from './FlowInfoPanel.messages';
import styles from './FlowInfoPanel.module.scss';

/**
 * Display-only subset of flow metadata shown in the "About flow" side panel.
 * Derived from {@link FlowRow} in `FlowDetail` — already formatted for display
 * (timestamps are locale strings, not raw ISO 8601).
 */
export interface FlowPanelData {
  /** Flow UUID. */
  flow_id: string;
  /** Human-readable flow name. */
  name: string;
  /** Free-text description, or empty string. */
  description: string;
  /** Tag strings attached to the flow. */
  tags: string[];
  /** Locale-formatted creation date string. */
  created_on: string;
  /** Locale-formatted last-modified date string. */
  modified_on: string;
  /** Project name slug used to navigate back to the project detail page. */
  project_name: string;
}

interface FlowInfoPanelProps {
  /** Flow metadata to display. */
  readonly flow: FlowPanelData;
  /** Called when the user clicks the × close button. */
  readonly onClose: () => void;
  /** Called when the user clicks the flow name link — navigates to Canvas. */
  readonly onViewFlow: () => void;
  /** Called when the user clicks the project name link — navigates to ProjectDetail. */
  readonly onViewProject: () => void;
  /** Called when the user clicks the Edit (pencil) icon — opens EditDetailsModal. */
  readonly onEdit: () => void;
}

/**
 * "About flow" side panel that slides in from the right of the FlowDetail page.
 *
 * Pure display component — receives {@link FlowPanelData} and callbacks from
 * {@link FlowDetail}. Has no internal state, makes no API calls.
 *
 * Rendered when the ⓘ button in the breadcrumb bar is clicked. Closes via
 * `onClose`, which also causes the ⓘ button to re-appear.
 */
export function FlowInfoPanel({
  flow,
  onClose,
  onViewFlow,
  onViewProject,
  onEdit,
}: FlowInfoPanelProps): React.JSX.Element {
  const intl = useIntl();
  return (
    <div className={styles.sidePanel}>
      <div className={styles.sidePanelHeader}>
        <h2 className={styles.sidePanelTitle}>{intl.formatMessage(messages.panelTitle)}</h2>
        <button
          type="button"
          className={styles.sidePanelClose}
          aria-label={intl.formatMessage(messages.closePanel)}
          onClick={onClose}
        >
          <Close size={16} />
        </button>
      </div>

      <div className={styles.sidePanelBody}>

        {/* Details section — bordered block */}
        <div className={styles.detailsBlock}>
          <div className={styles.sidePanelSectionHeader}>
            <h3 className={styles.sidePanelSectionTitle}>{intl.formatMessage(messages.detailsSection)}</h3>
            <Button
              kind="ghost"
              size="sm"
              renderIcon={Edit}
              iconDescription={intl.formatMessage(messages.editDescription)}
              hasIconOnly
              tooltipPosition="left"
              onClick={onEdit}
            />
          </div>

          <div className={styles.detailItem}>
            <span className={styles.detailLabel}>{intl.formatMessage(messages.flowNameLabel)}</span>
            <button type="button" className={styles.detailLink} onClick={onViewFlow}>
              {flow.name}
            </button>
          </div>
          <div className={styles.detailItem}>
            <span className={styles.detailLabel}>{intl.formatMessage(messages.descriptionLabel)}</span>
            <span className={styles.detailValue}>{flow.description}</span>
          </div>
          <div className={styles.detailItem}>
            <span className={styles.detailLabel}>{intl.formatMessage(messages.tagsLabel)}</span>
            <div className={styles.tagsRow}>
              {flow.tags.map((tag) => (
                <Tag key={tag} type="blue" size="sm">{tag}</Tag>
              ))}
            </div>
          </div>
        </div>

        <hr className={styles.divider} />

        <div className={styles.detailItem}>
          <span className={styles.detailLabel}>{intl.formatMessage(messages.createdOnLabel)}</span>
          <span className={styles.detailValue}>{flow.created_on}</span>
        </div>
        <div className={styles.detailItem}>
          <span className={styles.detailLabel}>{intl.formatMessage(messages.lastModifiedLabel)}</span>
          <span className={styles.detailValue}>{flow.modified_on}</span>
        </div>

        <hr className={styles.divider} />

        <div className={styles.detailItem}>
          <span className={styles.detailLabel}>{intl.formatMessage(messages.projectLabel)}</span>
          <button type="button" className={styles.detailLink} onClick={onViewProject}>
            {flow.project_name}
          </button>
        </div>

      </div>
    </div>
  );
}
