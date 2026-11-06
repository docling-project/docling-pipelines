import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import { CommonProperties, CanvasController } from '@elyra/canvas';
import { CommonPropertiesWrapper } from '@/components/PropertiesPanel/CommonPropertiesWrapper';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import type { OperatorMetadata } from '@/types';

/**
 * Simplified view of the callbacks the wrapper passes to Elyra's CommonProperties.
 * Elyra's typings declare the full multi-argument signatures; the wrapper only uses
 * the ones below.
 */
interface WrapperCallbacks {
  applyPropertyChanges: (propertySet: Record<string, unknown>, appData?: Record<string, unknown>) => void;
  closePropertiesDialog: () => void;
  controllerHandler: (controller: unknown) => void;
  propertyListener: (data?: unknown) => void;
}

/** Returns the callbacks from the first CommonProperties render. */
function getCallbacks(): WrapperCallbacks {
  const props = vi.mocked(CommonProperties).mock.calls[0]?.[0];
  if (!props) {
    throw new Error('CommonProperties was not rendered');
  }
  return props.callbacks as unknown as WrapperCallbacks;
}

describe('CommonPropertiesWrapper', () => {
  let mockCanvasController: any;
  let mockPropertiesInfo: Record<string, unknown>;
  let mockOperatorMetadata: Record<string, OperatorMetadata>;
  let mockSetIsDirty: any;
  let mockOnClose: any;

  const renderWrapper = (): void => {
    renderWithProviders(
      <CommonPropertiesWrapper
        propertiesInfo={mockPropertiesInfo}
        canvasController={mockCanvasController}
        selectedOperator="chunker"
        operatorMetadata={mockOperatorMetadata}
        setIsDirty={mockSetIsDirty}
        onClose={mockOnClose}
      />
    );
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mockCanvasController = new (CanvasController as any)();
    mockPropertiesInfo = {
      parameterDef: { parameters: [] },
      appData: { nodeId: 'node-1' },
    };
    mockOperatorMetadata = {
      chunker: {
        label: 'Chunker',
        category: 'Functional',
        description: null,
        features: {},
        required_features: [],
        attributes: {
          chunk_size: {
            required: true,
            type: 'number',
          },
        },
      },
    };
    mockSetIsDirty = vi.fn();
    mockOnClose = vi.fn();
  });

  it('renders CommonProperties component with expected props and callbacks', () => {
    renderWrapper();

    expect(screen.getByTestId('common-properties')).toBeTruthy();
    expect(CommonProperties).toHaveBeenCalledWith(
      expect.objectContaining({
        propertiesInfo: mockPropertiesInfo,
        propertiesConfig: {
          containerType: 'Custom',
          rightFlyout: true,
          applyPropertiesWithoutEdit: true,
        },
        callbacks: expect.objectContaining({
          applyPropertyChanges: expect.any(Function),
          closePropertiesDialog: expect.any(Function),
          controllerHandler: expect.any(Function),
          propertyListener: expect.any(Function),
        }),
      }),
      expect.anything()
    );
  });

  it('uses the controller provided by controllerHandler when propertyListener fires', () => {
    renderWrapper();

    const callbacks = getCallbacks();
    const mockElyraPropsController = {
      getPropertyValues: vi.fn(() => ({ chunk_size: 500 })),
      setSaveButtonDisable: vi.fn(),
    };

    callbacks.controllerHandler(mockElyraPropsController);
    callbacks.propertyListener({});

    expect(mockElyraPropsController.getPropertyValues).toHaveBeenCalled();
    expect(mockElyraPropsController.setSaveButtonDisable).toHaveBeenCalledWith(false);
  });

  it('propertyListener is a no-op before controllerHandler has provided a controller', () => {
    renderWrapper();

    const callbacks = getCallbacks();

    expect(() => callbacks.propertyListener({})).not.toThrow();
  });

  it('handles applyPropertyChanges by calling canvasController.setNodeParameters and setIsDirty', () => {
    renderWrapper();

    const propertySet = { chunk_size: 500 };
    const appData = { nodeId: 'node-1' };

    getCallbacks().applyPropertyChanges(propertySet, appData);

    expect(mockCanvasController.setNodeParameters).toHaveBeenCalledWith('node-1', propertySet);
    expect(mockSetIsDirty).toHaveBeenCalledWith(true);
  });

  it('handles closePropertiesDialog by dropping the controller and calling onClose', () => {
    renderWrapper();

    const callbacks = getCallbacks();
    const mockElyraPropsController = {
      getPropertyValues: vi.fn(() => ({ chunk_size: 500 })),
      setSaveButtonDisable: vi.fn(),
    };

    callbacks.controllerHandler(mockElyraPropsController);
    callbacks.closePropertiesDialog();
    callbacks.propertyListener({});

    expect(mockOnClose).toHaveBeenCalled();
    expect(mockElyraPropsController.setSaveButtonDisable).not.toHaveBeenCalled();
  });

  it('handles propertyListener and calls setSaveButtonDisable based on required param validation', () => {
    renderWrapper();

    const callbacks = getCallbacks();
    const mockElyraPropsController = {
      getPropertyValues: vi.fn<() => Record<string, unknown>>(() => ({ chunk_size: undefined })),
      setSaveButtonDisable: vi.fn(),
    };

    callbacks.controllerHandler(mockElyraPropsController);
    callbacks.propertyListener({});

    expect(mockElyraPropsController.setSaveButtonDisable).toHaveBeenCalledWith(true);

    mockElyraPropsController.getPropertyValues.mockReturnValue({ chunk_size: 500 });
    callbacks.propertyListener({});
    expect(mockElyraPropsController.setSaveButtonDisable).toHaveBeenCalledWith(false);
  });
});
