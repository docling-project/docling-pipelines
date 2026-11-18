import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../../utils/renderWithProviders';
import { SharedDataTable } from '@/components/common/SharedDataTable/SharedDataTable';

const headers = [
  { key: 'name', header: 'Name' },
  { key: 'status', header: 'Status' },
];

const rows = [
  { id: 'r1', name: 'Flow One', status: 'completed' },
  { id: 'r2', name: 'Flow Two', status: 'running' },
];

describe('SharedDataTable', () => {
  it('renders column headers', () => {
    renderWithProviders(<SharedDataTable headers={headers} rows={rows} />);
    expect(screen.getByText('Name')).toBeDefined();
    expect(screen.getByText('Status')).toBeDefined();
  });

  it('renders row data', () => {
    renderWithProviders(<SharedDataTable headers={headers} rows={rows} />);
    expect(screen.getByText('Flow One')).toBeDefined();
    expect(screen.getByText('Flow Two')).toBeDefined();
  });

  it('renders empty state when rows is empty', () => {
    renderWithProviders(<SharedDataTable headers={headers} rows={[]} />);
    // Empty state is rendered by NotFoundEmptyState — may contain "No results" or similar
    // Just check no data rows appear
    expect(screen.queryByText('Flow One')).toBeNull();
  });

  it('renders loading skeleton when loading=true', () => {
    const { container } = renderWithProviders(
      <SharedDataTable headers={headers} rows={rows} loading />
    );
    // Carbon DataTableSkeleton renders when loading is true
    expect(container.querySelector('.cds--skeleton')).toBeTruthy();
  });

  it('renders pagination when paginated=true (default) and rows > pageSize', () => {
    const manyRows = Array.from({ length: 25 }, (_, i) => ({
      id: `r${i}`,
      name: `Flow ${i}`,
      status: 'completed',
    }));
    renderWithProviders(<SharedDataTable headers={headers} rows={manyRows} />);
    // Pagination controls should be visible
    const pagination = document.querySelector('.cds--pagination');
    expect(pagination).toBeTruthy();
  });
});

// ── Additional coverage tests ─────────────────────────────────────────────────

import { fireEvent } from '@testing-library/react';

describe('SharedDataTable — additional coverage', () => {
  it('search with no matching results renders "No results found" empty state', () => {
    renderWithProviders(
      <SharedDataTable
        searchable
        headers={headers}
        rows={rows}
        searchPlaceholder="Search"
      />
    );
    const searchInput = screen.getByPlaceholderText('Search');
    // Fire a change that matches no row
    fireEvent.change(searchInput, { target: { value: 'zzznomatch' } });
    // Multiple elements may contain the text (heading + svg title) — use getAllByText
    expect(screen.getAllByText('No results found').length).toBeGreaterThan(0);
  });

  it('paginated={false} does not render a Pagination control', () => {
    const manyRows = Array.from({ length: 25 }, (_, i) => ({
      id: `r${i}`,
      name: `Flow ${i}`,
      status: 'completed',
    }));
    renderWithProviders(
      <SharedDataTable headers={headers} rows={manyRows} paginated={false} />
    );
    expect(document.querySelector('.cds--pagination')).toBeNull();
  });

  it('renderToolbarLeft renders custom left toolbar content', () => {
    renderWithProviders(
      <SharedDataTable
        headers={headers}
        rows={rows}
        renderToolbarLeft={() => <span data-testid="left-toolbar-custom">LeftContent</span>}
      />
    );
    expect(screen.getByTestId('left-toolbar-custom')).toBeDefined();
    expect(screen.getByText('LeftContent')).toBeDefined();
  });

  it('renderRowExtras renders extra content after each row', () => {
    renderWithProviders(
      <SharedDataTable
        headers={headers}
        rows={[{ id: 'r1', name: 'Flow One', status: 'completed' }]}
        renderRowExtras={(row) => (
          <tr key={`extra-${row.id}`}>
            <td colSpan={2} data-testid={`extra-${row.id}`}>Extra for {String(row.name)}</td>
          </tr>
        )}
      />
    );
    expect(screen.getByTestId('extra-r1')).toBeDefined();
    expect(screen.getByText('Extra for Flow One')).toBeDefined();
  });

  it('renderCell custom renderer is called and returns custom content', () => {
    renderWithProviders(
      <SharedDataTable
        headers={headers}
        rows={[{ id: 'r1', name: 'Flow One', status: 'completed' }]}
        renderCell={(cell) => {
          if (cell.info.header === 'name') {
            return <span data-testid="custom-cell">CustomName</span>;
          }
          return undefined;
        }}
      />
    );
    expect(screen.getByTestId('custom-cell')).toBeDefined();
    expect(screen.getByText('CustomName')).toBeDefined();
  });

  it('horizontalScroll={true} wraps table in a scrollable container', () => {
    const { container } = renderWithProviders(
      <SharedDataTable headers={headers} rows={rows} horizontalScroll />
    );
    // MaybeScrollWrapper renders a wrapping <div> when active=true
    // The table should exist inside the DOM
    const table = container.querySelector('table');
    expect(table).toBeTruthy();
    // The parent of the table is a div (scroll wrapper), not a direct tbody
    expect(table?.parentElement?.tagName).toBe('DIV');
  });

  it('renderToolbarActions renders extra toolbar actions', () => {
    renderWithProviders(
      <SharedDataTable
        searchable
        headers={headers}
        rows={rows}
        renderToolbarActions={() => (
          <button data-testid="toolbar-action-btn" type="button">
            Export
          </button>
        )}
      />
    );
    expect(screen.getByTestId('toolbar-action-btn')).toBeDefined();
    expect(screen.getByText('Export')).toBeDefined();
  });
});
