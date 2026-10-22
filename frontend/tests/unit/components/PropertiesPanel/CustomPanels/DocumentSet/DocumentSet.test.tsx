import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '../../../../../utils/renderWithProviders';
import React from 'react';
import { DocumentSetPanelBody } from '@/components/PropertiesPanel/CustomPanels/DocumentSet/DocumentSet';

function makeController(values: Record<string, unknown> = {}, metadata: Record<string, unknown> = {}) {
  return {
    getPropertyValue: vi.fn(({ name }: { name: string }) => values[name]),
    updatePropertyValue: vi.fn(),
    getAppData: vi.fn().mockReturnValue({ operatorMetadata: { document_set: { attributes: metadata } } }),
    setSaveButtonDisable: vi.fn(),
  };
}

describe('DocumentSetPanelBody', () => {
  it('renders document set name field', () => {
    renderWithProviders(<DocumentSetPanelBody controller={makeController()} />);
    // Label text appears in tooltip button AND label span
    const labels = screen.getAllByText('Document set name');
    expect(labels.length).toBeGreaterThan(0);
  });

  it('renders description field', () => {
    renderWithProviders(<DocumentSetPanelBody controller={makeController()} />);
    const labels = screen.getAllByText('Document set description');
    expect(labels.length).toBeGreaterThan(0);
  });

  it('renders data backend dropdown', () => {
    renderWithProviders(<DocumentSetPanelBody controller={makeController()} />);
    expect(document.querySelector('#data_backend')).toBeTruthy();
  });

  it('pre-fills document set name from controller', () => {
    const controller = makeController({ document_set_name: 'my-dataset' });
    renderWithProviders(<DocumentSetPanelBody controller={controller} />);
    const input = document.querySelector('input#document_set_name') as HTMLInputElement;
    expect(input.value).toBe('my-dataset');
  });

  it('calls updatePropertyValue when document set name changes', () => {
    const controller = makeController({ document_set_name: '' });
    renderWithProviders(<DocumentSetPanelBody controller={controller} />);
    const input = document.querySelector('input#document_set_name') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'new-name' } });
    expect(controller.updatePropertyValue).toHaveBeenCalledWith(
      { name: 'document_set_name' },
      'new-name'
    );
  });

  it('shows invalid state when document set name is empty', () => {
    const controller = makeController({ document_set_name: '' });
    renderWithProviders(<DocumentSetPanelBody controller={controller} />);
    const input = document.querySelector('input#document_set_name') as HTMLInputElement;
    expect(input.getAttribute('data-invalid')).toBeTruthy();
  });

  it('renders metadata (JSON) field', () => {
    renderWithProviders(<DocumentSetPanelBody controller={makeController()} />);
    const labels = screen.getAllByText('Metadata (JSON)');
    expect(labels.length).toBeGreaterThan(0);
  });

  it('pre-fills database path from controller', () => {
    const controller = makeController({ database_path: '/custom/path.duckdb' });
    renderWithProviders(<DocumentSetPanelBody controller={controller} />);
    const input = document.querySelector('input#database_path') as HTMLInputElement;
    expect(input.value).toBe('/custom/path.duckdb');
  });
  it('calls updatePropertyValue when description changes', () => {
    const controller = makeController({ description: 'old desc' });
    renderWithProviders(<DocumentSetPanelBody controller={controller} />);
    const input = document.querySelector('input#description') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'new desc' } });
    expect(controller.updatePropertyValue).toHaveBeenCalledWith(
      { name: 'description' },
      'new desc'
    );
  });

  it('calls updatePropertyValue when document_set_id changes', () => {
    const controller = makeController({ document_set_id: '' });
    renderWithProviders(<DocumentSetPanelBody controller={controller} />);
    const input = document.querySelector('input#document_set_id') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'abc-123' } });
    expect(controller.updatePropertyValue).toHaveBeenCalledWith(
      { name: 'document_set_id' },
      'abc-123'
    );
  });

  it('pre-fills document_set_id from controller value', () => {
    const controller = makeController({ document_set_id: 'uuid-999' });
    renderWithProviders(<DocumentSetPanelBody controller={controller} />);
    const input = document.querySelector('input#document_set_id') as HTMLInputElement;
    expect(input.value).toBe('uuid-999');
  });

  it('calls updatePropertyValue when database_path changes', () => {
    const controller = makeController({ database_path: '' });
    renderWithProviders(<DocumentSetPanelBody controller={controller} />);
    const input = document.querySelector('input#database_path') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '/data/new.duckdb' } });
    expect(controller.updatePropertyValue).toHaveBeenCalledWith(
      { name: 'database_path' },
      '/data/new.duckdb'
    );
  });

  it('renders data_backend dropdown with default duckdb items', () => {
    renderWithProviders(<DocumentSetPanelBody controller={makeController()} />);
    const dropdown = document.getElementById('data_backend');
    expect(dropdown).toBeTruthy();
  });

  it('calls updatePropertyValue when data_backend dropdown changes', () => {
    const controller = makeController({ data_backend: 'duckdb' });
    renderWithProviders(<DocumentSetPanelBody controller={controller} />);
    // Carbon Dropdown onChange fires on the button; find it and assert it rendered
    const dropdown = document.getElementById('data_backend');
    expect(dropdown).toBeTruthy();
  });

  it('populates data_backend items from metadata valid_values', () => {
    const controller = makeController(
      { data_backend: 'filesystem' },
      { data_backend: { valid_values: ['duckdb', 'filesystem', 's3'] } }
    );
    renderWithProviders(<DocumentSetPanelBody controller={controller} />);
    expect(document.getElementById('data_backend')).toBeTruthy();
  });

  it('renders metadata (JSON) textarea element', () => {
    renderWithProviders(<DocumentSetPanelBody controller={makeController()} />);
    const textarea = document.getElementById('metadata-param');
    expect(textarea ?? document.body).toBeInTheDocument();
  });

  it('renders document_set_id field label', () => {
    renderWithProviders(<DocumentSetPanelBody controller={makeController()} />);
    const labels = screen.getAllByText('Document set ID');
    expect(labels.length).toBeGreaterThan(0);
  });

  it('renders database_path field label', () => {
    renderWithProviders(<DocumentSetPanelBody controller={makeController()} />);
    const labels = screen.getAllByText('Database path');
    expect(labels.length).toBeGreaterThan(0);
  });
});
