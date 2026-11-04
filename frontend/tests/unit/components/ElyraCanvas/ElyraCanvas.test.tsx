import { describe, it, expect, vi } from 'vitest';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import { ElyraCanvas } from '@/components/ElyraCanvas/ElyraCanvas';
import type { CanvasConfig } from '@elyra/canvas';

const BASE_CONFIG: CanvasConfig = {
  enableInternalObjectModel: true,
  enablePaletteLayout: 'None',
  enableNodeFormatType: 'Horizontal',
  enableToolbarLayout: 'Top',
};

describe('ElyraCanvas', () => {
  it('renders the canvas container without crashing', () => {
    const { container } = renderWithProviders(
      <ElyraCanvas canvasConfig={BASE_CONFIG} />
    );
    expect(container).toBeTruthy();
  });

  it('renders an empty container when pipelineFlow is undefined', () => {
    const { container } = renderWithProviders(
      <ElyraCanvas canvasConfig={BASE_CONFIG} pipelineFlow={undefined} />
    );
    // No pipeline means the canvas renders the empty container div
    expect(container.firstChild).toBeTruthy();
  });

  it('calls onCanvasControllerReady when provided', () => {
    const onReady = vi.fn();
    renderWithProviders(
      <ElyraCanvas canvasConfig={BASE_CONFIG} onCanvasControllerReady={onReady} />
    );
    expect(onReady).toHaveBeenCalledOnce();
  });
});
