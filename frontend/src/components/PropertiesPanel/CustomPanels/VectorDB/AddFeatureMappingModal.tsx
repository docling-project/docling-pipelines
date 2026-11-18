/**
 * @file Add feature mapping modal for the VectorDB operator tearsheet.
 *
 * Allows the user to add an additional feature-to-column mapping row that is not
 * already present in the mapping table. The user selects a feature from the list
 * of unmapped available features, optionally edits the target column name
 * (pre-filled from default mappings), and confirms to add the row.
 */

import React, { useState } from 'react';
import { useIntl } from 'react-intl';
import {
  Dropdown,
  Modal,
  TextInput,
} from '@carbon/react';
import type { FeatureAttributes } from '@/types';
import { DEFAULT_COLUMN_MAPPINGS } from './constants';
import { messages } from './AddFeatureMappingModal.messages';
import styles from './VectorDB.module.scss';

interface AddFeatureMappingModalProps {
  open: boolean;
  /** Features available to map — those not yet in the table */
  availableFeatures: Record<string, FeatureAttributes>;
  /** Feature names already in the table */
  alreadyMapped: string[];
  onClose: () => void;
  onAdd: (feature: string, column: string) => void;
}

export function AddFeatureMappingModal({
  open,
  availableFeatures,
  alreadyMapped,
  onClose,
  onAdd,
}: AddFeatureMappingModalProps): React.JSX.Element {
  const intl = useIntl();
  const [selectedFeature, setSelectedFeature] = useState<string>('');
  const [columnName, setColumnName] = useState<string>('');
  const [submitted, setSubmitted] = useState(false);

  // Features not yet mapped
  const unmappedFeatures = Object.keys(availableFeatures).filter(
    (f) => !alreadyMapped.includes(f)
  );

  const handleFeatureChange = ({ selectedItem }: { selectedItem?: string | null }): void => {
    const f = selectedItem ?? '';
    setSelectedFeature(f);
    // Pre-fill column name from defaults when a feature is picked
    setColumnName(DEFAULT_COLUMN_MAPPINGS[f] ?? f);
  };

  const handleAdd = (): void => {
    setSubmitted(true);
    if (!selectedFeature || !columnName.trim()) { return; }
    onAdd(selectedFeature, columnName.trim());
    // Reset for next open
    setSelectedFeature('');
    setColumnName('');
    setSubmitted(false);
    onClose();
  };

  const handleClose = (): void => {
    setSelectedFeature('');
    setColumnName('');
    setSubmitted(false);
    onClose();
  };

  const isFeatureInvalid = submitted && !selectedFeature;
  const isColumnInvalid = submitted && !columnName.trim();

  return (
    <Modal
      open={open}
      modalHeading={intl.formatMessage(messages.modalHeading)}
      primaryButtonText={intl.formatMessage(messages.primaryButton)}
      secondaryButtonText={intl.formatMessage(messages.secondaryButton)}
      primaryButtonDisabled={!selectedFeature || !columnName.trim()}
      onRequestSubmit={handleAdd}
      onRequestClose={handleClose}
      size="sm"
    >
      <Dropdown
        id="add-mapping-feature-select"
        titleText={intl.formatMessage(messages.featureTitle)}
        label={intl.formatMessage(messages.selectFeatureLabel)}
        items={unmappedFeatures}
        selectedItem={selectedFeature || null}
        onChange={handleFeatureChange}
        invalid={isFeatureInvalid}
        invalidText={intl.formatMessage(messages.featureRequired)}
      />
      <div className={styles.modalColumnInput}>
        <TextInput
          id="add-mapping-column-input"
          labelText={intl.formatMessage(messages.columnName)}
          placeholder={intl.formatMessage(messages.columnNamePlaceholder)}
          value={columnName}
          invalid={isColumnInvalid}
          invalidText={intl.formatMessage(messages.columnNameRequired)}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
            setColumnName(e.target.value);
          }}
        />
      </div>
    </Modal>
  );
}
