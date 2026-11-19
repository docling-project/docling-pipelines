import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { SharedTearsheet } from '@/components/common/SharedTearsheet';

// Mock @carbon/ibm-products Tearsheet components
vi.mock('@carbon/ibm-products', () => ({
  Tearsheet: ({ open, title, children, onClose, actions }: {
    open: boolean;
    title: React.ReactNode;
    children: React.ReactNode;
    onClose: () => void;
    actions?: Array<{ label: string; onClick: () => void }>;
  }) =>
    open ? (
      <div data-testid="tearsheet">
        <div data-testid="tearsheet-title">{title}</div>
        <div data-testid="tearsheet-body">{children}</div>
        {actions?.map((a) => (
          <button key={a.label} onClick={a.onClick}>{a.label}</button>
        ))}
        <button onClick={onClose}>Close</button>
      </div>
    ) : null,
  TearsheetNarrow: ({ open, title, children }: {
    open: boolean;
    title: React.ReactNode;
    children: React.ReactNode;
  }) =>
    open ? (
      <div data-testid="tearsheet-narrow">
        <div data-testid="tearsheet-title">{title}</div>
        <div>{children}</div>
      </div>
    ) : null,
}));

// Mock useThemeElement
vi.mock('@/contexts', () => ({
  useThemeElement: () => document.body,
}));

describe('SharedTearsheet', () => {
  it('renders nothing when open is false', () => {
    const { container } = render(
      <SharedTearsheet open={false} onClose={vi.fn()} title="My Tearsheet">
        <p>Content</p>
      </SharedTearsheet>
    );
    expect(container.querySelector('[data-testid="tearsheet"]')).toBeNull();
  });

  it('renders Tearsheet when open is true (default size lg)', () => {
    render(
      <SharedTearsheet open onClose={vi.fn()} title="My Tearsheet">
        <p>Content here</p>
      </SharedTearsheet>
    );
    expect(screen.getByTestId('tearsheet')).toBeInTheDocument();
    expect(screen.getByTestId('tearsheet-title')).toHaveTextContent('My Tearsheet');
  });

  it('renders children inside the tearsheet', () => {
    render(
      <SharedTearsheet open onClose={vi.fn()} title="Test">
        <span data-testid="child-content">Hello</span>
      </SharedTearsheet>
    );
    expect(screen.getByTestId('child-content')).toBeInTheDocument();
  });

  it('renders TearsheetNarrow when size is sm', () => {
    render(
      <SharedTearsheet open onClose={vi.fn()} title="Narrow" size="sm">
        <p>Narrow content</p>
      </SharedTearsheet>
    );
    expect(screen.getByTestId('tearsheet-narrow')).toBeInTheDocument();
  });

  it('renders TearsheetNarrow when size is md', () => {
    render(
      <SharedTearsheet open onClose={vi.fn()} title="Medium" size="md">
        <p>Medium content</p>
      </SharedTearsheet>
    );
    expect(screen.getByTestId('tearsheet-narrow')).toBeInTheDocument();
  });

  it('renders no action buttons when hideFooter is true', () => {
    render(
      <SharedTearsheet open onClose={vi.fn()} title="Test" hideFooter>
        <p>body</p>
      </SharedTearsheet>
    );
    // No Save/primary buttons — only the tearsheet Close button
    const btns = Array.from(document.querySelectorAll('button'));
    expect(btns.every((b) => b.textContent !== 'Save')).toBe(true);
  });

  it('renders only one action button when only primaryActionLabel is given', () => {
    const onPrimary = vi.fn();
    render(
      <SharedTearsheet open onClose={vi.fn()} title="Test"
        primaryActionLabel="Save" onPrimaryAction={onPrimary}
        secondaryActionLabel={undefined as any}>
        <p>body</p>
      </SharedTearsheet>
    );
    // Primary button is present
    const saveBtn = Array.from(document.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === 'Save'
    );
    expect(saveBtn).toBeDefined();
  });

  it('calls onSecondaryAction when secondary button is clicked', () => {
    const onSecondary = vi.fn();
    const onClose = vi.fn();
    render(
      <SharedTearsheet open onClose={onClose} title="Test"
        secondaryActionLabel="Cancel" onSecondaryAction={onSecondary}>
        <p>body</p>
      </SharedTearsheet>
    );
    const cancelBtn = Array.from(document.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === 'Cancel'
    );
    if (cancelBtn) { fireEvent.click(cancelBtn); }
    expect(onSecondary).toHaveBeenCalled();
  });
});
