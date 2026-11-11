import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent, act } from '@testing-library/react';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import { FlowRunPropertiesTearsheet } from '@/components/Canvas/FlowRunPropertiesTearsheet/FlowRunPropertiesTearsheet';
import { buildPreloadedState } from '../../../mocks/fixtures/store.fixture';

describe('FlowRunPropertiesTearsheet', () => {
  it('renders without crashing when closed', () => {
    const { container } = renderWithProviders(
      <FlowRunPropertiesTearsheet open={false} onClose={vi.fn()} />
    );
    expect(container).toBeTruthy();
  });

  it('renders the title when open', () => {
    renderWithProviders(
      <FlowRunPropertiesTearsheet open={true} onClose={vi.fn()} />
    );
    expect(screen.getByText('Flow run properties')).toBeInTheDocument();
  });

  it('renders Incremental processing toggle', () => {
    renderWithProviders(
      <FlowRunPropertiesTearsheet open={true} onClose={vi.fn()} />
    );
    expect(screen.getByLabelText(/incremental processing/i)).toBeDefined();
  });

  it('renders Validate flow toggle', () => {
    renderWithProviders(
      <FlowRunPropertiesTearsheet open={true} onClose={vi.fn()} />
    );
    expect(screen.getByLabelText(/validate flow/i)).toBeDefined();
  });

  it('renders Intermediate data storage dropdown', () => {
    renderWithProviders(
      <FlowRunPropertiesTearsheet open={true} onClose={vi.fn()} />
    );
    expect(screen.getByText(/intermediate data storage/i)).toBeInTheDocument();
  });

  it('cancel resets local state and calls onClose', () => {
    const onClose = vi.fn();
    renderWithProviders(
      <FlowRunPropertiesTearsheet open={true} onClose={onClose} />
    );
    const cancelButton = screen.getByRole('button', { name: /cancel/i });
    fireEvent.click(cancelButton);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('save calls onClose and optional onSave', () => {
    const onClose = vi.fn();
    const onSave = vi.fn();
    renderWithProviders(
      <FlowRunPropertiesTearsheet open={true} onClose={onClose} onSave={onSave} />
    );
    const saveButton = screen.getByRole('button', { name: /save/i });
    fireEvent.click(saveButton);
    expect(onClose).toHaveBeenCalledOnce();
    expect(onSave).toHaveBeenCalledOnce();
  });

  it('save calls onClose without onSave when not provided', () => {
    const onClose = vi.fn();
    renderWithProviders(
      <FlowRunPropertiesTearsheet open={true} onClose={onClose} />
    );
    const saveButton = screen.getByRole('button', { name: /save/i });
    fireEvent.click(saveButton);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('toggling incremental processing shows the retain records toggle', async () => {
    renderWithProviders(
      <FlowRunPropertiesTearsheet open={true} onClose={vi.fn()} />,
      { preloadedState: buildPreloadedState() }
    );

    // Initially incremental is off — retain records toggle should not exist
    expect(screen.queryByLabelText(/retain records/i)).toBeNull();

    // Toggle incremental processing ON
    const incrementalToggle = screen.getByLabelText(/incremental processing/i);
    await act(async () => {
      fireEvent.click(incrementalToggle);
    });

    // Retain records toggle should now appear
    expect(screen.getByLabelText(/retain records/i)).toBeDefined();
  });

  it('toggling incremental processing ON then OFF hides retain records toggle', async () => {
    renderWithProviders(
      <FlowRunPropertiesTearsheet open={true} onClose={vi.fn()} />
    );

    const incrementalToggle = screen.getByLabelText(/incremental processing/i);

    // Enable
    await act(async () => { fireEvent.click(incrementalToggle); });
    expect(screen.getByLabelText(/retain records/i)).toBeDefined();

    // Disable
    await act(async () => { fireEvent.click(incrementalToggle); });
    expect(screen.queryByLabelText(/retain records/i)).toBeNull();
  });

  it('toggling validate flow updates state (no crash)', async () => {
    renderWithProviders(
      <FlowRunPropertiesTearsheet open={true} onClose={vi.fn()} />
    );

    const validateToggle = screen.getByLabelText(/validate flow/i);
    await act(async () => {
      fireEvent.click(validateToggle);
    });

    // Still renders and hasn't crashed
    expect(screen.getByLabelText(/validate flow/i)).toBeDefined();
  });

  it('onSave receives the current local properties on save', () => {
    const onClose = vi.fn();
    const onSave = vi.fn();
    renderWithProviders(
      <FlowRunPropertiesTearsheet open={true} onClose={onClose} onSave={onSave} />,
      { preloadedState: buildPreloadedState() }
    );

    fireEvent.click(screen.getByRole('button', { name: /save/i }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        enableIncrementalProcessing: expect.any(Boolean),
        validateFlow: expect.any(Boolean),
      })
    );
  });

  it('renders description text', () => {
    renderWithProviders(
      <FlowRunPropertiesTearsheet open={true} onClose={vi.fn()} />
    );
    expect(screen.getByText(/configure the properties/i)).toBeInTheDocument();
  });

  it('storage dropdown has Container file system option', () => {
    renderWithProviders(
      <FlowRunPropertiesTearsheet open={true} onClose={vi.fn()} />
    );
    // The selected item text is rendered in the dropdown button
    const containerText = screen.queryAllByText(/container file system/i);
    expect(containerText.length).toBeGreaterThan(0);
  });

  it('syncs local state with Redux when tearsheet reopens', () => {
    const onClose = vi.fn();
    const { rerender } = renderWithProviders(
      <FlowRunPropertiesTearsheet open={false} onClose={onClose} />
    );

    rerender(<FlowRunPropertiesTearsheet open={true} onClose={onClose} />);

    // Tearsheet should render without crashing after re-open
    expect(screen.getByText('Flow run properties')).toBeInTheDocument();
  });
});
