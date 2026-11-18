import React, { useState } from 'react';
import {
  ComposedModal,
  InlineLoading,
  ModalHeader,
  ModalBody,
  ModalFooter,
  Button,
} from '@carbon/react';
import { useIntl } from 'react-intl';
import { messages } from './DeleteModal.messages';
import styles from './DeleteModal.module.scss';

interface DeleteModalProps {
  /** Controls whether the modal is visible. */
  readonly open: boolean;
  /** The type of asset being deleted — used as the modal heading, e.g. "Delete flow". */
  readonly assetType: string;
  /** Display name of the asset to be deleted. Shown in bold in the confirmation body. */
  readonly assetName: string;
  /** Called when the user clicks Cancel or closes the modal. */
  readonly onCancel: () => void;
  /**
   * Called when the user clicks the danger Delete button.
   * Must return a Promise — the modal uses it to show a loading state on the
   * Delete button and close only after the operation resolves.
   */
  readonly onDelete: () => Promise<void>;
}

/**
 * Generic confirmation modal for destructive delete actions.
 *
 * The modal heading is composed as `"Delete <assetType>"` — callers pass only
 * the asset type label (e.g. `"Flow"`, `"Project"`, `"Run"`).
 * Renders the asset name in bold. The footer uses a 50/50 CSS grid:
 * Cancel | Delete (danger). Loading state is driven internally via the
 * `onDelete` Promise — callers do not need to thread an `isLoading` prop.
 */
export function DeleteModal({
  open,
  assetType,
  assetName,
  onCancel,
  onDelete,
}: DeleteModalProps): React.JSX.Element {
  const intl = useIntl();
  const [deleting, setDeleting] = useState(false);

  const handleConfirm = (): void => {
    setDeleting(true);
    onDelete()
      .then(() => {
        setDeleting(false);
      })
      .catch(() => {
        // parent surfaces the error; modal stays open on failure
        setDeleting(false);
      });
  };

  return (
    <ComposedModal
      open={open}
      onClose={onCancel}
      size="sm"
      preventCloseOnClickOutside
      containerClassName={styles.modal}
    >
      <ModalHeader title={intl.formatMessage(messages.title, { assetType })} buttonOnClick={onCancel} />
      <ModalBody className={styles.body}>
        <p>
          {intl.formatMessage(messages.body, {
            assetName: <strong>{assetName}</strong>,
          })}
        </p>
      </ModalBody>
      <ModalFooter className={styles.footer}>
        <Button kind="secondary" onClick={onCancel} disabled={deleting} className={styles.footerBtn}>
          {intl.formatMessage(messages.cancel)}
        </Button>
        <Button kind="danger" onClick={handleConfirm} disabled={deleting} className={styles.footerBtn}>
          {deleting ? <InlineLoading description={intl.formatMessage(messages.deleting)} /> : intl.formatMessage(messages.delete)}
        </Button>
      </ModalFooter>
    </ComposedModal>
  );
}
