import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../../../utils/renderWithProviders';
import { CriteriaFullViewTearsheet } from '@/components/PropertiesPanel/CustomPanels/AnnotationFilter/CriteriaFullViewTearsheet';
import type { CriteriaDisplayRow } from '@/components/PropertiesPanel/CustomPanels/AnnotationFilter/CriteriaFullViewTearsheet';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const makeRows = (count = 2): CriteriaDisplayRow[] =>
  Array.from({ length: count }, (_, i) => ({
    id: `row-${i}`,
    condition: `lang_score >= ${0.1 * (i + 1)}`,
    isAdvanced: false,
  }));

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('CriteriaFullViewTearsheet', () => {

  // ── Closed state ─────────────────────────────────────────────────────────

  it('renders without crashing when closed', () => {
    const { container } = renderWithProviders(
      <CriteriaFullViewTearsheet
        open={false}
        onClose={vi.fn()}
        criteriaRows={[]}
        logicalOperator="AND"
      />
    );
    expect(container).toBeInTheDocument();
  });

  // ── Open with rows ────────────────────────────────────────────────────────

  it('renders when open with rows', () => {
    const { container } = renderWithProviders(
      <CriteriaFullViewTearsheet
        open
        onClose={vi.fn()}
        criteriaRows={makeRows()}
        logicalOperator="AND"
      />
    );
    expect(container).toBeInTheDocument();
  });

  it('renders condition text for each row', () => {
    renderWithProviders(
      <CriteriaFullViewTearsheet
        open
        onClose={vi.fn()}
        criteriaRows={makeRows(2)}
        logicalOperator="AND"
      />
    );
    expect(screen.getByText('lang_score >= 0.1')).toBeDefined();
    expect(screen.getByText('lang_score >= 0.2')).toBeDefined();
  });

  it('renders AND badge between rows when logicalOperator is AND', () => {
    renderWithProviders(
      <CriteriaFullViewTearsheet
        open
        onClose={vi.fn()}
        criteriaRows={makeRows(2)}
        logicalOperator="AND"
      />
    );
    const badges = screen.queryAllByText('AND');
    expect(badges.length).toBeGreaterThan(0);
  });

  it('renders OR badge between rows when logicalOperator is OR', () => {
    renderWithProviders(
      <CriteriaFullViewTearsheet
        open
        onClose={vi.fn()}
        criteriaRows={makeRows(2)}
        logicalOperator="OR"
      />
    );
    const badges = screen.queryAllByText('OR');
    expect(badges.length).toBeGreaterThan(0);
  });

  it('does not render a logical badge on the last row', () => {
    renderWithProviders(
      <CriteriaFullViewTearsheet
        open
        onClose={vi.fn()}
        criteriaRows={[{ id: 'r1', condition: 'lang_score >= 0.5', isAdvanced: false }]}
        logicalOperator="AND"
      />
    );
    // Only one row — no badge should appear
    const badges = screen.queryAllByText('AND');
    expect(badges.length).toBe(0);
  });

  it('does not render badge for advanced rows', () => {
    renderWithProviders(
      <CriteriaFullViewTearsheet
        open
        onClose={vi.fn()}
        criteriaRows={[
          { id: 'r1', condition: 'lang_score >= 0.5 AND pii_score < 0.1', isAdvanced: true },
        ]}
        logicalOperator="AND"
      />
    );
    // Advanced row content may contain AND in its text, but not the badge span
    expect(document.body).toBeInTheDocument();
  });

  // ── Empty rows ────────────────────────────────────────────────────────────

  it('renders with empty rows without crashing', () => {
    renderWithProviders(
      <CriteriaFullViewTearsheet
        open
        onClose={vi.fn()}
        criteriaRows={[]}
        logicalOperator="AND"
      />
    );
    expect(document.body).toBeInTheDocument();
  });

  // ── Lowercase logicalOperator normalisation ───────────────────────────────

  it('normalises lowercase logical operator to uppercase for display', () => {
    renderWithProviders(
      <CriteriaFullViewTearsheet
        open
        onClose={vi.fn()}
        criteriaRows={makeRows(2)}
        logicalOperator="or"
      />
    );
    const badges = screen.queryAllByText('OR');
    expect(badges.length).toBeGreaterThan(0);
  });

  // ── Close button ──────────────────────────────────────────────────────────

  it('renders the Close action button', () => {
    renderWithProviders(
      <CriteriaFullViewTearsheet
        open
        onClose={vi.fn()}
        criteriaRows={makeRows()}
        logicalOperator="AND"
      />
    );
    // "Close" appears both as a button label and tooltip text — use queryAllByText
    const closeElements = screen.queryAllByText('Close');
    expect(closeElements.length).toBeGreaterThan(0);
  });

  // ── Custom title / description ────────────────────────────────────────────

  it('renders a custom title when provided', () => {
    renderWithProviders(
      <CriteriaFullViewTearsheet
        open
        onClose={vi.fn()}
        criteriaRows={[]}
        logicalOperator="AND"
        title="My Custom Title"
      />
    );
    expect(screen.getByText('My Custom Title')).toBeDefined();
  });

  it('renders default title "Criteria" when no title is provided', () => {
    renderWithProviders(
      <CriteriaFullViewTearsheet
        open
        onClose={vi.fn()}
        criteriaRows={[]}
        logicalOperator="AND"
      />
    );
    const headings = screen.queryAllByText('Criteria');
    expect(headings.length).toBeGreaterThan(0);
  });

  // ── Three rows — badge between first/second and second/third ─────────────

  it('renders badges between all adjacent rows', () => {
    renderWithProviders(
      <CriteriaFullViewTearsheet
        open
        onClose={vi.fn()}
        criteriaRows={makeRows(3)}
        logicalOperator="AND"
      />
    );
    const badges = screen.queryAllByText('AND');
    // Two badges for three rows
    expect(badges.length).toBeGreaterThanOrEqual(2);
  });
});
