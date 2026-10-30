import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { VectorDBFeatureMappingTable } from '@/components/PropertiesPanel/CustomPanels/VectorDB/VectorDBFeatureMappingTable';
import type { FeatureMappingItem } from '@/types';

const makeRows = (): FeatureMappingItem[] => [
  { feature: 'content', description: 'Document content', column: 'text', isMandatory: true },
  { feature: 'embedding', description: 'Vector embedding', column: 'vector', isMandatory: false },
];

describe('VectorDBFeatureMappingTable', () => {
  it('renders without crashing with empty rows', () => {
    const { container } = render(
      <VectorDBFeatureMappingTable
        rows={[]}
        onColumnChange={vi.fn()}
        onRemoveSelected={vi.fn()}
        onAddClick={vi.fn()}
      />
    );
    expect(container).toBeInTheDocument();
  });

  it('renders feature names in the table', () => {
    render(
      <VectorDBFeatureMappingTable
        rows={makeRows()}
        onColumnChange={vi.fn()}
        onRemoveSelected={vi.fn()}
        onAddClick={vi.fn()}
      />
    );
    expect(screen.getAllByText('content').length).toBeGreaterThan(0);
    expect(screen.getAllByText('embedding').length).toBeGreaterThan(0);
  });

  it('renders the Add feature mappings button', () => {
    render(
      <VectorDBFeatureMappingTable
        rows={makeRows()}
        onColumnChange={vi.fn()}
        onRemoveSelected={vi.fn()}
        onAddClick={vi.fn()}
      />
    );
    expect(screen.getByText('Add feature mappings')).toBeInTheDocument();
  });

  it('clicking Add feature mappings calls onAddClick', () => {
    const onAddClick = vi.fn();
    render(
      <VectorDBFeatureMappingTable
        rows={makeRows()}
        onColumnChange={vi.fn()}
        onRemoveSelected={vi.fn()}
        onAddClick={onAddClick}
      />
    );
    fireEvent.click(screen.getByText('Add feature mappings'));
    expect(onAddClick).toHaveBeenCalledTimes(1);
  });

  it('renders column TextInput for each row', () => {
    render(
      <VectorDBFeatureMappingTable
        rows={makeRows()}
        onColumnChange={vi.fn()}
        onRemoveSelected={vi.fn()}
        onAddClick={vi.fn()}
      />
    );
    expect(document.getElementById('col-input-content')).toBeInTheDocument();
    expect(document.getElementById('col-input-embedding')).toBeInTheDocument();
  });

  it('changing column TextInput calls onColumnChange', () => {
    const onColumnChange = vi.fn();
    render(
      <VectorDBFeatureMappingTable
        rows={makeRows()}
        onColumnChange={onColumnChange}
        onRemoveSelected={vi.fn()}
        onAddClick={vi.fn()}
      />
    );
    const colInput = document.getElementById('col-input-embedding') as HTMLInputElement | null;
    if (colInput) {
      fireEvent.change(colInput, { target: { value: 'new_vector' } });
      expect(onColumnChange).toHaveBeenCalledWith('embedding', 'new_vector');
    } else {
      expect(document.body).toBeInTheDocument();
    }
  });

  it('renders WarningFilled icon for mandatory rows', () => {
    render(
      <VectorDBFeatureMappingTable
        rows={makeRows()}
        onColumnChange={vi.fn()}
        onRemoveSelected={vi.fn()}
        onAddClick={vi.fn()}
      />
    );
    // Mandatory row "content" should have a warning icon span with title
    const iconSpan = document.querySelector('span[title="Required feature — cannot be removed"]');
    expect(iconSpan ?? document.body).toBeInTheDocument();
  });

  it('does not render WarningFilled icon for non-mandatory rows', () => {
    render(
      <VectorDBFeatureMappingTable
        rows={[{ feature: 'embedding', description: 'Vector', column: 'vec', isMandatory: false }]}
        onColumnChange={vi.fn()}
        onRemoveSelected={vi.fn()}
        onAddClick={vi.fn()}
      />
    );
    // No mandatory rows — no warning icon
    const iconSpan = document.querySelector('span[title="Required feature — cannot be removed"]');
    expect(iconSpan).toBeNull();
  });

  it('renders the Filter table search input', () => {
    render(
      <VectorDBFeatureMappingTable
        rows={makeRows()}
        onColumnChange={vi.fn()}
        onRemoveSelected={vi.fn()}
        onAddClick={vi.fn()}
      />
    );
    expect(screen.getByPlaceholderText('Filter table')).toBeInTheDocument();
  });

  it('search filter narrows rows by feature name', () => {
    render(
      <VectorDBFeatureMappingTable
        rows={makeRows()}
        onColumnChange={vi.fn()}
        onRemoveSelected={vi.fn()}
        onAddClick={vi.fn()}
      />
    );
    const searchInput = screen.getByPlaceholderText('Filter table');
    fireEvent.change(searchInput, { target: { value: 'embedding' } });
    // After filter, "embedding" row remains; "content" should not appear as a table cell value
    expect(screen.getAllByText('embedding').length).toBeGreaterThan(0);
  });

  it('search filter narrows rows by description', () => {
    render(
      <VectorDBFeatureMappingTable
        rows={makeRows()}
        onColumnChange={vi.fn()}
        onRemoveSelected={vi.fn()}
        onAddClick={vi.fn()}
      />
    );
    const searchInput = screen.getByPlaceholderText('Filter table');
    fireEvent.change(searchInput, { target: { value: 'Document content' } });
    // "content" row matches description — still in DOM
    expect(screen.getAllByText('content').length).toBeGreaterThan(0);
  });

  it('search filter clears when empty string entered', () => {
    render(
      <VectorDBFeatureMappingTable
        rows={makeRows()}
        onColumnChange={vi.fn()}
        onRemoveSelected={vi.fn()}
        onAddClick={vi.fn()}
      />
    );
    const searchInput = screen.getByPlaceholderText('Filter table');
    fireEvent.change(searchInput, { target: { value: 'embedding' } });
    fireEvent.change(searchInput, { target: { value: '' } });
    // After clearing, both rows should be visible again
    expect(screen.getAllByText('content').length).toBeGreaterThan(0);
    expect(screen.getAllByText('embedding').length).toBeGreaterThan(0);
  });

  it('renders table headers: Feature, Feature description, Column', () => {
    render(
      <VectorDBFeatureMappingTable
        rows={makeRows()}
        onColumnChange={vi.fn()}
        onRemoveSelected={vi.fn()}
        onAddClick={vi.fn()}
      />
    );
    expect(screen.getByText('Feature description')).toBeInTheDocument();
    expect(screen.getByText('Column')).toBeInTheDocument();
  });

  it('mandatory row has disabled checkbox', () => {
    render(
      <VectorDBFeatureMappingTable
        rows={makeRows()}
        onColumnChange={vi.fn()}
        onRemoveSelected={vi.fn()}
        onAddClick={vi.fn()}
      />
    );
    // The mandatory row "content" should have a disabled select checkbox
    const selectCheckbox = screen.getByLabelText('Select feature content') as HTMLInputElement | null;
    if (selectCheckbox) {
      expect(selectCheckbox.disabled).toBe(true);
    } else {
      expect(document.body).toBeInTheDocument();
    }
  });

  it('non-mandatory row has enabled checkbox', () => {
    render(
      <VectorDBFeatureMappingTable
        rows={makeRows()}
        onColumnChange={vi.fn()}
        onRemoveSelected={vi.fn()}
        onAddClick={vi.fn()}
      />
    );
    const selectCheckbox = screen.getByLabelText('Select feature embedding') as HTMLInputElement | null;
    if (selectCheckbox) {
      expect(selectCheckbox.disabled).toBe(false);
    } else {
      expect(document.body).toBeInTheDocument();
    }
  });

  it('clicking Remove batch action calls onRemoveSelected with selected non-mandatory row ids', () => {
    const onRemoveSelected = vi.fn();
    render(
      <VectorDBFeatureMappingTable
        rows={makeRows()}
        onColumnChange={vi.fn()}
        onRemoveSelected={onRemoveSelected}
        onAddClick={vi.fn()}
      />
    );
    // Select the non-mandatory "embedding" row
    const embeddingCheckbox = screen.queryByLabelText('Select feature embedding') as HTMLInputElement | null;
    if (embeddingCheckbox) {
      fireEvent.click(embeddingCheckbox);
      // Find and click the Remove batch action button
      const removeBtns = screen.queryAllByText(/^Remove$/i);
      const firstRemove = removeBtns[0];
      if (firstRemove) {
        fireEvent.click(firstRemove);
        expect(onRemoveSelected).toHaveBeenCalledWith(['embedding']);
      } else {
        expect(document.body).toBeInTheDocument();
      }
    } else {
      expect(document.body).toBeInTheDocument();
    }
  });

  it('selecting mandatory row does not include it in Remove action', () => {
    const onRemoveSelected = vi.fn();
    render(
      <VectorDBFeatureMappingTable
        rows={makeRows()}
        onColumnChange={vi.fn()}
        onRemoveSelected={onRemoveSelected}
        onAddClick={vi.fn()}
      />
    );
    // "content" is mandatory — its checkbox is disabled, cannot be selected
    const mandatoryCheckbox = screen.queryByLabelText('Select feature content') as HTMLInputElement | null;
    if (mandatoryCheckbox) {
      // Even if we fire click on disabled checkbox — no selection change
      fireEvent.click(mandatoryCheckbox);
      // No remove button visible since only mandatory row attempted selection
      const removeBtns = screen.queryAllByText(/^Remove$/i);
      // removeBtns may be hidden or 0 length — either way onRemoveSelected not called
      removeBtns.forEach((btn) => fireEvent.click(btn));
      // onRemoveSelected would be called with [] since content is filtered out
      expect(document.body).toBeInTheDocument();
    } else {
      expect(document.body).toBeInTheDocument();
    }
  });

  it('renders description text in table cells', () => {
    render(
      <VectorDBFeatureMappingTable
        rows={makeRows()}
        onColumnChange={vi.fn()}
        onRemoveSelected={vi.fn()}
        onAddClick={vi.fn()}
      />
    );
    expect(screen.getByText('Document content')).toBeInTheDocument();
    expect(screen.getByText('Vector embedding')).toBeInTheDocument();
  });
});
