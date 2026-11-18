/**
 * Encapsulates Elyra's CommonProperties component and its associated callbacks,
 * validation listeners, and properties configuration.
 */

import React, { useCallback, useRef } from 'react';
import {
  type CanvasController,
  type CommonPropertiesController,
  CommonProperties,
} from '@elyra/canvas';
import CommonPropertiesPanelWrapper from './CommonPropertiesPanelWrapper';
import { hasAnyRequiredParamMissing } from '@/utils/requiredParamValidation';
import type { OperatorFeature, OperatorMetadata } from '@/types';

// Correcting Elyra's typing for getPropertyValues as it does not internally type `options` as optional
type PropertiesController = Omit<CommonPropertiesController, 'getPropertyValues'> & {
  getPropertyValues?(options?: {
    filterHiddenDisabled?: boolean;
    filterHiddenControls?: boolean;
    applyProperties?: boolean;
  }): unknown;
};

export interface CommonPropertiesWrapperProps {
  propertiesInfo: Record<string, unknown>;
  canvasController: CanvasController;
  selectedOperator: string;
  operatorMetadata: Record<string, OperatorMetadata>;
  setIsDirty: (dirty: boolean) => void;
  onClose: () => void;
}

export function CommonPropertiesWrapper({
  propertiesInfo,
  canvasController,
  selectedOperator,
  operatorMetadata,
  setIsDirty,
  onClose,
}: CommonPropertiesWrapperProps): React.JSX.Element {
  const controllerRef = useRef<PropertiesController | null>(null);

  const handleControllerHandler = useCallback(
    (propertiesController: CommonPropertiesController) => {
      controllerRef.current = propertiesController;
    },
    []
  );

  const handleApplyPropertyChanges = useCallback(
    (propertySet: Record<string, unknown>, appData?: Record<string, unknown>) => {
      const nodeId = (appData as { nodeId?: string } | undefined)?.nodeId;
      if (!nodeId || !canvasController) {
        return;
      }

      // Use setNodeParameters (targeted parameter update) rather than the broader
      // setNodeProperties(). The TS declaration is typed as array but the JS impl
      // dispatches the value as-is; a plain object works here.
      canvasController.setNodeParameters(
        nodeId,
        propertySet as unknown as Array<Record<string, unknown>>
      );

      setIsDirty(true);
    },
    [canvasController, setIsDirty]
  );

  const handleClosePropertiesDialog = useCallback(() => {
    controllerRef.current = null;
    onClose();
  }, [onClose]);

  const handlePropertyListener = useCallback(
    (_data: unknown): void => {
      const controller = controllerRef.current;
      if (!controller) {
        return;
      }

      const propertyValues = (controller.getPropertyValues?.() ?? {}) as Record<string, unknown>;
      const attrs: Record<string, OperatorFeature> =
        selectedOperator ? (operatorMetadata[selectedOperator]?.attributes ?? {}) : {};

      const shouldDisable = hasAnyRequiredParamMissing(attrs, propertyValues);

      controller.setSaveButtonDisable?.(shouldDisable);
    },
    [operatorMetadata, selectedOperator]
  );

  return (
    <CommonProperties
      propertiesInfo={propertiesInfo as any}
      propertiesConfig={{ containerType: 'Custom', rightFlyout: true, applyPropertiesWithoutEdit: true }}
      customPanels={[CommonPropertiesPanelWrapper]}
      callbacks={{
        applyPropertyChanges: handleApplyPropertyChanges,
        closePropertiesDialog: handleClosePropertiesDialog,
        controllerHandler: handleControllerHandler,
        propertyListener: handlePropertyListener,
      }}
    />
  );
}

export default CommonPropertiesWrapper;
