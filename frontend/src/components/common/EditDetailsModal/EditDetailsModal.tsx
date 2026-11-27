import React, { useEffect, useState } from 'react';
import {
  Button,
  ComposedModal,
  InlineLoading,
  InlineNotification,
  ModalHeader,
  ModalBody,
  ModalFooter,
  TextInput,
  TextArea,
} from '@carbon/react';
import { useIntl } from 'react-intl';
import { isConflictError } from '@/utils/httpErrors';
import { TagInput } from '../TagInput';
import { messages } from './EditDetailsModal.messages';
import styles from './EditDetailsModal.module.scss';

interface EditDetailsModalProps {
  /** Controls whether the modal is visible. */
  readonly open: boolean;
  /** Modal heading — e.g. "Edit project details" or "Edit flow details". */
  readonly title: string;
  /** Initial field values seeded into the form when the modal opens. */
  readonly initialValues: { name: string; description: string; tags: string[] };
  /** Called when the user clicks Cancel or closes the modal. */
  readonly onCancel: () => void;
  /**
   * Called with the updated form values when the user clicks Save.
   * Must return a Promise — the modal uses it to show a loading state on the
   * Save button and close only after the operation resolves.
   *
   * The parent component already holds the entity ID and should close over it
   * in the callback — the modal does not need to receive or return it.
   *
   * @param updates - The edited name, description, and tags.
   */
  readonly onEdit: (updates: { name: string; description: string; tags: string[] }) => Promise<void>;
  /** Optional error message to show as an inline notification. */
  readonly error?: string | null;
  /**
   * Names already used by other entities of the same kind. Must NOT include the entity
   * being edited, so saving without renaming is never reported as a duplicate.
   * Compared trimmed and case-insensitively, like the create modals.
   */
  readonly existingNames?: string[];
  /**
   * Inline error shown under the name field for a duplicate name. Duplicate detection
   * (client-side and on a 409 from `onEdit`) is only active when this is provided.
   */
  readonly duplicateNameMessage?: string;
}

/**
 * Generic modal for editing an entity's name, description, and tags.
 *
 * Form is pre-seeded from `initialValues` on every open via `useEffect`.
 * Loading state is driven internally via the `onEdit` Promise — callers do not
 * need to thread an `isLoading` prop. An optional `error` prop surfaces API
 * errors as an inline notification inside the modal body.
 *
 * The caller is responsible for closing over the entity ID in `onEdit` —
 * this modal has no awareness of what is being edited.
 */
export function EditDetailsModal({
  open,
  title,
  initialValues,
  onCancel,
  onEdit,
  error = null,
  existingNames = [],
  duplicateNameMessage,
}: EditDetailsModalProps): React.JSX.Element {
  const intl = useIntl();
  const [name, setName] = useState(initialValues.name);
  const [description, setDescription] = useState(initialValues.description);
  const [tags, setTags] = useState<string[]>(initialValues.tags);
  const [nameInvalid, setNameInvalid] = useState(false);
  const [nameDuplicate, setNameDuplicate] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setName(initialValues.name);
      setDescription(initialValues.description);
      setTags([...initialValues.tags]);
      setNameInvalid(false);
      setNameDuplicate(false);
    }
  }, [open, initialValues.name, initialValues.description, initialValues.tags]);

  const handleCancel = (): void => {
    setNameInvalid(false);
    setNameDuplicate(false);
    onCancel();
  };

  const isDuplicate = (value: string): boolean => {
    const trimmed = value.trim().toLowerCase();
    if (!duplicateNameMessage || !trimmed) { return false; }
    return existingNames.some((n) => n.trim().toLowerCase() === trimmed);
  };

  const handleNameBlur = (): void => {
    if (isDuplicate(name)) { setNameDuplicate(true); }
  };

  const handleSave = (): void => {
    if (!name.trim()) {
      setNameInvalid(true);
      return;
    }
    if (isDuplicate(name)) {
      setNameDuplicate(true);
      return;
    }
    setSaving(true);
    onEdit({ name: name.trim(), description, tags })
      .then(() => {
        setSaving(false);
      })
      .catch((err: unknown) => {
        // parent surfaces the error; modal stays open on failure.
        // A 409 means the name is taken (e.g. the local list was stale) - show it inline.
        if (duplicateNameMessage && isConflictError(err)) { setNameDuplicate(true); }
        setSaving(false);
      });
  };

  return (
    <ComposedModal
      open={open}
      onClose={handleCancel}
      size="sm"
      preventCloseOnClickOutside
      containerClassName={styles.modal}
    >
      <ModalHeader title={title} buttonOnClick={handleCancel} className={styles.modalHeader} />

      <ModalBody className={styles.body}>
        <div className={styles.formContent}>
          {error && (
            <InlineNotification
                kind="error"
                title={intl.formatMessage(messages.errorTitle)}
                subtitle={error}
                hideCloseButton
                lowContrast
              />
          )}

          <TextInput
            id="edit-name"
            labelText={intl.formatMessage(messages.nameLabel)}
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              if (e.target.value.trim()) { setNameInvalid(false); }
              setNameDuplicate(false);
            }}
            onBlur={handleNameBlur}
            invalid={nameInvalid || nameDuplicate}
            invalidText={nameDuplicate ? duplicateNameMessage : intl.formatMessage(messages.nameRequired)}
            disabled={saving}
          />

          <TextArea
            id="edit-description"
            labelText={intl.formatMessage(messages.descriptionLabel)}
            value={description}
            onChange={(e) => { setDescription(e.target.value); }}
            rows={5}
            disabled={saving}
          />

          <TagInput
            id="edit-tags"
            tags={tags}
            onChange={setTags}
            labelText={intl.formatMessage(messages.tagsLabel)}
            disabled={saving}
          />
        </div>
      </ModalBody>

      <ModalFooter className={styles.footer}>
        <Button kind="secondary" onClick={handleCancel} disabled={saving} className={styles.footerBtn}>
          {intl.formatMessage(messages.cancel)}
        </Button>
        <Button kind="primary" onClick={handleSave} disabled={saving || nameDuplicate} className={styles.footerBtn}>
          {saving ? <InlineLoading description={intl.formatMessage(messages.saving)} /> : intl.formatMessage(messages.save)}
        </Button>
      </ModalFooter>
    </ComposedModal>
  );
}
