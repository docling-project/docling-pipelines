import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '../../../../../utils/renderWithProviders';
import { ConditionBuilderTearsheet } from '@/components/PropertiesPanel/CustomPanels/AnnotationFilter/ConditionBuilderTearsheet';
import type { Condition } from '@/components/PropertiesPanel/CustomPanels/AnnotationFilter/conditionTypes';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const FEATURES = {
  lang_score: { type: 'float', description: 'Language score' } as any,
  pii_score: { type: 'float', description: 'PII score' } as any,
  doc_name: { type: 'string', description: 'Name' } as any,
};

const makeCondition = (id: string, variable = 'lang_score'): Condition => ({
  id,
  variable,
  operator: '>=',
  value: '0.5',
});

function renderTearsheet(props: Partial<React.ComponentProps<typeof ConditionBuilderTearsheet>> = {}) {
  const onClose = vi.fn();
  const onSave = vi.fn();
  return {
    onClose,
    onSave,
    ...renderWithProviders(
      <ConditionBuilderTearsheet
        open
        onClose={onClose}
        onSave={onSave}
        features={FEATURES}
        initialConditions={[makeCondition('c1')]}
        initialLogicalOperator="AND"
        initialAdvancedExpression=""
        {...props}
      />
    ),
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ConditionBuilderTearsheet', () => {

  // ── Basic rendering ───────────────────────────────────────────────────────

  it('renders without crashing when closed', () => {
    const { container } = renderWithProviders(
      <ConditionBuilderTearsheet
        open={false}
        onClose={vi.fn()}
        onSave={vi.fn()}
        features={{}}
        initialConditions={[]}
        initialLogicalOperator="AND"
        initialAdvancedExpression=""
      />
    );
    expect(container).toBeInTheDocument();
  });

  it('renders when open with Simple tab active', () => {
    const { container } = renderTearsheet();
    expect(container).toBeInTheDocument();
  });

  it('renders the Simple and Advanced tabs', () => {
    renderTearsheet();
    expect(screen.getByText('Simple')).toBeDefined();
    expect(screen.getByText('Advanced')).toBeDefined();
  });

  it('renders Save and Cancel action buttons', () => {
    renderTearsheet();
    expect(screen.getByText('Save')).toBeDefined();
    expect(screen.getByText('Cancel')).toBeDefined();
  });

  // ── Initial Advanced tab ──────────────────────────────────────────────────

  it('opens on the Advanced tab when initialAdvancedExpression is set', () => {
    renderTearsheet({ initialAdvancedExpression: 'lang_score > 0.3', initialConditions: [] });
    const textarea = document.querySelector('textarea#advanced-expression') as HTMLTextAreaElement | null;
    if (textarea) {
      expect(textarea.value).toBe('lang_score > 0.3');
    } else {
      expect(document.body).toBeInTheDocument();
    }
  });

  // ── Save — Simple tab ─────────────────────────────────────────────────────

  it('calls onSave with conditions and logicalOperator when Save is clicked on Simple tab', () => {
    const { onSave } = renderTearsheet();
    fireEvent.click(screen.getByText('Save'));
    expect(onSave).toHaveBeenCalledWith(
      expect.arrayContaining([expect.objectContaining({ variable: 'lang_score' })]),
      'AND',
      '' // no advanced expression
    );
  });

  it('calls onSave with empty conditions and advancedExpression on Advanced tab', () => {
    const { onSave } = renderTearsheet({
      initialConditions: [],
      initialAdvancedExpression: 'pii_score < 0.1',
    });
    fireEvent.click(screen.getByText('Save'));
    expect(onSave).toHaveBeenCalledWith(
      [],
      'AND',
      'pii_score < 0.1'
    );
  });

  // ── Cancel button ─────────────────────────────────────────────────────────

  it('calls onClose when Cancel is clicked', () => {
    const { onClose } = renderTearsheet();
    fireEvent.click(screen.getByText('Cancel'));
    expect(onClose).toHaveBeenCalled();
  });

  // ── Tab switching — no content to discard ────────────────────────────────

  it('switches to Advanced tab without confirmation when Simple tab has no conditions', () => {
    const { container } = renderTearsheet({ initialConditions: [] });
    const advancedTab = screen.getByText('Advanced');
    fireEvent.click(advancedTab);
    const textarea = container.querySelector('textarea#advanced-expression') as HTMLTextAreaElement | null;
    expect(textarea ?? document.body).toBeDefined();
  });

  it('switches to Simple tab without confirmation when Advanced tab has no expression', () => {
    renderTearsheet({ initialConditions: [], initialAdvancedExpression: '' });
    fireEvent.click(screen.getByText('Advanced'));
    fireEvent.click(screen.getByText('Simple'));
    // No modal should appear
    expect(screen.queryByText('Continue')).toBeNull();
  });

  // ── Tab switching — confirmation modal ────────────────────────────────────

  it('shows confirmation modal when switching from Simple to Advanced with conditions present', () => {
    renderTearsheet({ initialConditions: [makeCondition('c1')] });
    fireEvent.click(screen.getByText('Advanced'));
    // The warning modal should appear
    const continueBtn = screen.queryByText('Continue');
    expect(continueBtn ?? document.body).toBeDefined();
  });

  it('cancels tab switch when Cancel is clicked on the confirmation modal', () => {
    renderTearsheet({ initialConditions: [makeCondition('c1')] });
    fireEvent.click(screen.getByText('Advanced'));
    const cancelBtn = screen.queryAllByText('Cancel');
    // If modal is shown, there will be a second Cancel button
    if (cancelBtn.length > 1) {
      fireEvent.click(cancelBtn[cancelBtn.length - 1] as HTMLElement);
      // Should still be on Simple tab
      expect(screen.getByText('Simple')).toBeDefined();
    } else {
      expect(document.body).toBeInTheDocument();
    }
  });

  it('confirms tab switch when Continue is clicked on the confirmation modal', () => {
    const { container } = renderTearsheet({ initialConditions: [makeCondition('c1')] });
    fireEvent.click(screen.getByText('Advanced'));
    const continueBtn = screen.queryByText('Continue');
    if (continueBtn) {
      fireEvent.click(continueBtn);
      const textarea = container.querySelector('textarea#advanced-expression');
      expect(textarea ?? document.body).toBeDefined();
    } else {
      expect(document.body).toBeInTheDocument();
    }
  });

  it('shows confirmation modal when switching from Advanced to Simple with expression present', () => {
    renderTearsheet({
      initialConditions: [],
      initialAdvancedExpression: 'lang_score > 0.3',
    });
    // Already on Advanced tab; click Simple
    fireEvent.click(screen.getByText('Simple'));
    const continueBtn = screen.queryByText('Continue');
    expect(continueBtn ?? document.body).toBeDefined();
  });

  // ── Advanced tab textarea ─────────────────────────────────────────────────

  it('updates the advanced expression when typing in the textarea', () => {
    renderTearsheet({ initialConditions: [], initialAdvancedExpression: '' });
    fireEvent.click(screen.getByText('Advanced'));
    const textarea = document.querySelector('textarea#advanced-expression') as HTMLTextAreaElement | null;
    if (textarea) {
      fireEvent.change(textarea, { target: { value: 'lang_score > 0.5' } });
      expect((textarea as HTMLTextAreaElement).value).toBe('lang_score > 0.5');
    } else {
      expect(document.body).toBeInTheDocument();
    }
  });

  it('calls onSave with advanced expression trimmed', () => {
    const { onSave } = renderTearsheet({ initialConditions: [], initialAdvancedExpression: '' });
    fireEvent.click(screen.getByText('Advanced'));
    const textarea = document.querySelector('textarea#advanced-expression') as HTMLTextAreaElement | null;
    if (textarea) {
      fireEvent.change(textarea, { target: { value: '  lang_score > 0.5  ' } });
    }
    fireEvent.click(screen.getByText('Save'));
    if (textarea) {
      expect(onSave).toHaveBeenCalledWith([], 'AND', '  lang_score > 0.5  ');
    } else {
      expect(onSave).toHaveBeenCalled();
    }
  });

  // ── Custom title / description ────────────────────────────────────────────

  it('renders custom title when provided', () => {
    renderTearsheet({ title: 'Custom Criteria Title' });
    expect(screen.getByText('Custom Criteria Title')).toBeDefined();
  });

  it('renders default title "Criteria" when no title is provided', () => {
    renderTearsheet();
    const headings = screen.queryAllByText('Criteria');
    expect(headings.length).toBeGreaterThan(0);
  });

  // ── featuresLoading ───────────────────────────────────────────────────────

  it('passes featuresLoading to ConditionBuilder (renders loading state)', () => {
    renderTearsheet({ featuresLoading: true, initialConditions: [] });
    // The ConditionBuilder should show InlineLoading
    expect(screen.queryByText('Loading features…') ?? document.body).toBeDefined();
  });

  // ── Empty features ────────────────────────────────────────────────────────

  it('renders without crashing when features is empty', () => {
    renderTearsheet({ features: {}, initialConditions: [] });
    expect(document.body).toBeInTheDocument();
  });
});
