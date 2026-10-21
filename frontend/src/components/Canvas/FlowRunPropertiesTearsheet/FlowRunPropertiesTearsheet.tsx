/**
 * Flow Run Properties Tearsheet Component
 *
 * A tearsheet component for configuring flow execution properties including
 * incremental processing, validation, and storage options.
 * Uses the SharedTearsheet component for consistent modal behavior.
 * Connected to Redux store for state persistence.
 */
import React, { useState, useEffect } from 'react';
import { Toggle, Dropdown } from '@carbon/react';
import { useIntl } from 'react-intl';
import { useAppDispatch, useAppSelector } from '@/hooks';
import { setFlowRunProperties } from '@/slices/flowSlice';
import type { FlowRunProperties } from '@/types';
import { SharedTearsheet } from '@/components/common';
import { FLOW_PROPERTY_KEYS } from '@/constants/flowRunProperties';
import type { StorageOption } from '@/constants/flowRunProperties';
import { messages } from './FlowRunPropertiesTearsheet.messages';
import styles from './FlowRunPropertiesTearsheet.module.scss';

/**
 * Props for the FlowRunPropertiesTearsheet component.
 */
interface FlowRunPropertiesTearsheetProps {
  open: boolean;
  onClose: () => void;
  onSave?: (properties: FlowRunProperties) => void;
}

/**
 * FlowRunPropertiesTearsheet component for configuring flow execution properties.
 *
 * Provides a user interface for configuring:
 * - Incremental processing with nested option for retaining deleted document records
 * - Flow validation toggle
 * - Intermediate data storage selection (Container file system or Memory)
 *
 * @param props - Component props
 * @returns React component displaying the flow run properties configuration tearsheet
 */
export function FlowRunPropertiesTearsheet({
  open,
  onClose,
  onSave,
}: FlowRunPropertiesTearsheetProps): React.JSX.Element {
  const intl = useIntl();
  const storageOptions: StorageOption[] = [
    { id: 'container', text: intl.formatMessage(messages.storageContainer) },
    { id: 'memory',    text: intl.formatMessage(messages.storageMemory)    },
  ];
  const dispatch = useAppDispatch();
  const reduxProperties = useAppSelector((state) => state.flow.flowRunProperties);

  // Local state for editing (syncs to Redux on save)
  const [localProperties, setLocalProperties] = useState<FlowRunProperties>(reduxProperties);

  // Sync local state with Redux when tearsheet opens
  useEffect(() => {
    if (open) {
      setLocalProperties(reduxProperties);
    }
  }, [open, reduxProperties]);

  const handleSave = () => {
    // Save to Redux store
    dispatch(setFlowRunProperties(localProperties));

    // Call optional callback
    if (onSave) {
      onSave(localProperties);
    }

    onClose();
  };

  const handleCancel = () => {
    // Discard local changes
    setLocalProperties(reduxProperties);
    onClose();
  };

  const updateLocalProperty = <K extends keyof FlowRunProperties>(
    key: K,
    value: FlowRunProperties[K]
  ) => {
    setLocalProperties((prev) => ({ ...prev, [key]: value }));
  };

  return (
    <SharedTearsheet
      open={open}
      onClose={onClose}
      title={intl.formatMessage(messages.title)}
      size="md"
      primaryActionLabel={intl.formatMessage(messages.primaryAction)}
      secondaryActionLabel={intl.formatMessage(messages.secondaryAction)}
      onPrimaryAction={handleSave}
      onSecondaryAction={handleCancel}
    >
      <div className={styles.propertiesContainer}>
        <p className={styles.description}>
          {intl.formatMessage(messages.description)}
        </p>

        <div className={styles.propertySection}>
          <div className={styles.toggleWrapper}>
            <Toggle
              id="incremental-processing"
              labelText={intl.formatMessage(messages.toggleIncrementalProcessing)}
              labelA={intl.formatMessage(messages.toggleOff)}
              labelB={intl.formatMessage(messages.toggleOn)}
              toggled={localProperties.enableIncrementalProcessing}
              onToggle={(checked) => {
                updateLocalProperty(FLOW_PROPERTY_KEYS.ENABLE_INCREMENTAL_PROCESSING as keyof FlowRunProperties, checked);
              }}
            />
          </div>

          {localProperties.enableIncrementalProcessing && (
            <div className={styles.nestedProperty}>
              <Toggle
                id="retain-records"
                labelText={intl.formatMessage(messages.toggleRetainRecords)}
                labelA={intl.formatMessage(messages.toggleOff)}
                labelB={intl.formatMessage(messages.toggleOn)}
                toggled={localProperties.retainRecordsForDeletedDocuments}
                onToggle={(checked) => {
                  updateLocalProperty(FLOW_PROPERTY_KEYS.RETAIN_RECORDS_FOR_DELETED_DOCUMENTS as keyof FlowRunProperties, checked);
                }}
              />
            </div>
          )}
        </div>

        <div className={styles.propertySection}>
          <div className={styles.toggleWrapper}>
            <Toggle
              id="validate-flow"
              labelText={intl.formatMessage(messages.toggleValidateFlow)}
              labelA={intl.formatMessage(messages.toggleOff)}
              labelB={intl.formatMessage(messages.toggleOn)}
              toggled={localProperties.validateFlow}
              onToggle={(checked) => {
                updateLocalProperty(FLOW_PROPERTY_KEYS.VALIDATE_FLOW as keyof FlowRunProperties, checked);
              }}
            />
          </div>
        </div>

        <div className={styles.dropdownSection}>
          <Dropdown
            id="intermediate-storage"
            titleText={intl.formatMessage(messages.intermediateStorageTitle)}
            label={intl.formatMessage(messages.intermediateStorageLabel)}
            items={storageOptions}
            selectedItem={storageOptions.find(
              (opt) => opt.id === localProperties.intermediateDataStorage
            )}
            itemToString={(item) => (item ? item.text : '')}
            onChange={({ selectedItem }) => {
              if (selectedItem) {
                updateLocalProperty(
                  FLOW_PROPERTY_KEYS.INTERMEDIATE_DATA_STORAGE as keyof FlowRunProperties,
                  selectedItem.id
                );
              }
            }}
          />
        </div>
      </div>
    </SharedTearsheet>
  );
}
