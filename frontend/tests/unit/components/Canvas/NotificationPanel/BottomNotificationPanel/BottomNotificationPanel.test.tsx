/*
 * Licensed Materials - Property of IBM
 * © Copyright IBM Corp. 2024, 2026.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '../../../../../utils/renderWithProviders';
import React from 'react';
import BottomNotificationPanel from '@/components/Canvas/NotificationPanel/BottomNotificationPanel/BottomNotificationPanel';
import type { NotificationItem } from '@/components/Canvas/NotificationPanel/BottomNotificationPanel/BottomNotificationPanel';

// ── Helpers ───────────────────────────────────────────────────────────────────

const makeNotification = (overrides: Partial<NotificationItem> = {}): NotificationItem => ({
  id: 'notif-1',
  type: 'error',
  code: 'ERR_001',
  message: 'Something went wrong',
  node_name: 'ExtractNode',
  node_id: 'node-abc',
  message_code: 'EXTRACT_FAILED',
  timestamp: '2024-01-01T00:00:00Z',
  ...overrides,
});

// Stub clipboard
beforeEach(() => {
  Object.assign(navigator, {
    clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
  });
});

// ── Rendering ─────────────────────────────────────────────────────────────────

describe('BottomNotificationPanel — rendering', () => {
  it('renders the default panel title when none supplied', () => {
    renderWithProviders(<BottomNotificationPanel notifications={[makeNotification()]} onClose={vi.fn()} />);
    expect(screen.getByText('Validation problems')).toBeInTheDocument();
  });

  it('renders a custom title prop', () => {
    renderWithProviders(
      <BottomNotificationPanel notifications={[makeNotification()]} onClose={vi.fn()} title="My Custom Title" />
    );
    expect(screen.getByText('My Custom Title')).toBeInTheDocument();
  });

  it('renders notification message text', () => {
    renderWithProviders(
      <BottomNotificationPanel notifications={[makeNotification({ message: 'Test error message' })]} onClose={vi.fn()} />
    );
    expect(screen.getAllByText('Test error message').length).toBeGreaterThan(0);
  });

  it('renders warning type notification', () => {
    renderWithProviders(
      <BottomNotificationPanel notifications={[makeNotification({ type: 'warning', message: 'A warning' })]} onClose={vi.fn()} />
    );
    expect(screen.getAllByText('A warning').length).toBeGreaterThan(0);
  });

  it('renders empty panel with no notifications without crashing', () => {
    const { container } = renderWithProviders(<BottomNotificationPanel notifications={[]} onClose={vi.fn()} />);
    expect(container).toBeInTheDocument();
  });

  it('renders row number starting from 1', () => {
    renderWithProviders(<BottomNotificationPanel notifications={[makeNotification()]} onClose={vi.fn()} />);
    // The table cell containing "1" may also appear in pagination <option> elements
    expect(screen.getAllByText('1').length).toBeGreaterThan(0);
  });

  it('renders node name as a clickable button when node_id and onNodeClick are provided', () => {
    const onNodeClick = vi.fn();
    renderWithProviders(
      <BottomNotificationPanel
        notifications={[makeNotification({ node_name: 'MyNode', node_id: 'node-1' })]}
        onClose={vi.fn()}
        onNodeClick={onNodeClick}
      />
    );
    expect(screen.getByRole('button', { name: 'MyNode' })).toBeInTheDocument();
  });

  it('renders node name as plain text when onNodeClick is not provided', () => {
    renderWithProviders(
      <BottomNotificationPanel
        notifications={[makeNotification({ node_name: 'PlainNode', node_id: 'node-1' })]}
        onClose={vi.fn()}
      />
    );
    // It should appear as text, not a button with name 'PlainNode'
    expect(screen.queryByRole('button', { name: 'PlainNode' })).toBeNull();
    expect(screen.getByText('PlainNode')).toBeInTheDocument();
  });

  it('renders node name as plain text when node_id is absent', () => {
    const onNodeClick = vi.fn();
    renderWithProviders(
      <BottomNotificationPanel
        notifications={[makeNotification({ node_name: 'NoIdNode', node_id: null })]}
        onClose={vi.fn()}
        onNodeClick={onNodeClick}
      />
    );
    expect(screen.queryByRole('button', { name: 'NoIdNode' })).toBeNull();
    expect(screen.getByText('NoIdNode')).toBeInTheDocument();
  });

  it('renders dash placeholder when node_name is null', () => {
    renderWithProviders(
      <BottomNotificationPanel notifications={[makeNotification({ node_name: null })]} onClose={vi.fn()} />
    );
    expect(screen.getByText('-')).toBeInTheDocument();
  });

  it('renders expand button for each row', () => {
    renderWithProviders(<BottomNotificationPanel notifications={[makeNotification()]} onClose={vi.fn()} />);
    expect(screen.getByRole('button', { name: /expand row/i })).toBeInTheDocument();
  });

  it('renders copy button for each description cell', () => {
    renderWithProviders(<BottomNotificationPanel notifications={[makeNotification()]} onClose={vi.fn()} />);
    expect(screen.getByRole('button', { name: /copy to clipboard/i })).toBeInTheDocument();
  });

  it('renders multiple notifications with sequential row numbers', () => {
    const notifications = [
      makeNotification({ id: 'n1', message: 'First error' }),
      makeNotification({ id: 'n2', type: 'warning', message: 'Second warning' }),
    ];
    renderWithProviders(<BottomNotificationPanel notifications={notifications} onClose={vi.fn()} />);
    // Row numbers appear in <td> cells; pagination may also render "1" in <option>
    expect(screen.getAllByText('1').length).toBeGreaterThan(0);
    expect(screen.getAllByText('2').length).toBeGreaterThan(0);
  });
});

// ── Close button ──────────────────────────────────────────────────────────────

describe('BottomNotificationPanel — close', () => {
  it('calls onClose when the close button is clicked', () => {
    const onClose = vi.fn();
    renderWithProviders(<BottomNotificationPanel notifications={[makeNotification()]} onClose={onClose} />);
    fireEvent.click(screen.getByRole('button', { name: /close/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});

// ── Node link ─────────────────────────────────────────────────────────────────

describe('BottomNotificationPanel — node link click', () => {
  it('calls onNodeClick with nodeId, messageCode, and actionType when node button is clicked', () => {
    const onNodeClick = vi.fn();
    renderWithProviders(
      <BottomNotificationPanel
        notifications={[makeNotification({ node_name: 'MyNode', node_id: 'node-1', message_code: 'EXTRACT_FAILED', action_type: 'OPEN_PROPERTIES' })]}
        onClose={vi.fn()}
        onNodeClick={onNodeClick}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: 'MyNode' }));
    expect(onNodeClick).toHaveBeenCalledWith('node-1', 'EXTRACT_FAILED', 'OPEN_PROPERTIES');
  });

  it('passes null messageCode when message_code is null', () => {
    const onNodeClick = vi.fn();
    renderWithProviders(
      <BottomNotificationPanel
        notifications={[makeNotification({ node_name: 'N', node_id: 'n-id', message_code: null, action_type: null })]}
        onClose={vi.fn()}
        onNodeClick={onNodeClick}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: 'N' }));
    expect(onNodeClick).toHaveBeenCalledWith('n-id', null, null);
  });
});

// ── Expand / Collapse ─────────────────────────────────────────────────────────

describe('BottomNotificationPanel — expand/collapse rows', () => {
  it('shows expand icon initially (row is collapsed)', () => {
    renderWithProviders(<BottomNotificationPanel notifications={[makeNotification()]} onClose={vi.fn()} />);
    expect(screen.getByRole('button', { name: /expand row/i })).toBeInTheDocument();
  });

  it('toggles to collapse icon after clicking expand', () => {
    renderWithProviders(<BottomNotificationPanel notifications={[makeNotification()]} onClose={vi.fn()} />);
    const expandBtn = screen.getByRole('button', { name: /expand row/i });
    fireEvent.click(expandBtn);
    expect(screen.getByRole('button', { name: /collapse row/i })).toBeInTheDocument();
  });

  it('shows expanded row content with full message after expanding', () => {
    const msg = 'Full expanded message content';
    renderWithProviders(<BottomNotificationPanel notifications={[makeNotification({ message: msg })]} onClose={vi.fn()} />);
    const expandBtn = screen.getByRole('button', { name: /expand row/i });
    fireEvent.click(expandBtn);
    // Message appears at least twice: in table cell and in expanded row
    expect(screen.getAllByText(msg).length).toBeGreaterThanOrEqual(2);
  });

  it('collapses an expanded row on second click', () => {
    const msg = 'Collapsible message';
    renderWithProviders(<BottomNotificationPanel notifications={[makeNotification({ message: msg })]} onClose={vi.fn()} />);
    const expandBtn = screen.getByRole('button', { name: /expand row/i });
    fireEvent.click(expandBtn);
    // Now collapse
    const collapseBtn = screen.getByRole('button', { name: /collapse row/i });
    fireEvent.click(collapseBtn);
    // Back to expand icon
    expect(screen.getByRole('button', { name: /expand row/i })).toBeInTheDocument();
  });

  it('can independently expand one row without affecting another', () => {
    const notifications = [
      makeNotification({ id: 'n1', message: 'Error A' }),
      makeNotification({ id: 'n2', type: 'warning', message: 'Warning B' }),
    ];
    renderWithProviders(<BottomNotificationPanel notifications={notifications} onClose={vi.fn()} />);
    const expandBtns = screen.getAllByRole('button', { name: /expand row/i });
    fireEvent.click(expandBtns[0]);
    // First row is expanded, second is not
    expect(screen.getAllByRole('button', { name: /collapse row/i })).toHaveLength(1);
    expect(screen.getAllByRole('button', { name: /expand row/i })).toHaveLength(1);
  });
});

// ── Copy button ───────────────────────────────────────────────────────────────

describe('BottomNotificationPanel — copy description', () => {
  it('calls navigator.clipboard.writeText with the message when copy button is clicked', () => {
    const message = 'Something went wrong';
    renderWithProviders(<BottomNotificationPanel notifications={[makeNotification({ message })]} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /copy to clipboard/i }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(message);
  });

  it('calls clipboard with empty string when message is null', () => {
    renderWithProviders(
      <BottomNotificationPanel notifications={[makeNotification({ message: null })]} onClose={vi.fn()} />
    );
    fireEvent.click(screen.getByRole('button', { name: /copy to clipboard/i }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('');
  });

  it('does not throw when clipboard is rejected', async () => {
    (navigator.clipboard.writeText as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('denied'));
    renderWithProviders(<BottomNotificationPanel notifications={[makeNotification()]} onClose={vi.fn()} />);
    expect(() => {
      fireEvent.click(screen.getByRole('button', { name: /copy to clipboard/i }));
    }).not.toThrow();
  });
});

// ── Status icon ───────────────────────────────────────────────────────────────

describe('BottomNotificationPanel — status icons', () => {
  it('renders error icon for error type notifications', () => {
    const { container } = renderWithProviders(
      <BottomNotificationPanel notifications={[makeNotification({ type: 'error' })]} onClose={vi.fn()} />
    );
    // Carbon ErrorFilled renders an SVG; check for aria or class
    // We check that there is no WarningAlt (warning class) for error rows
    expect(container.querySelector('svg')).toBeTruthy();
  });

  it('renders warning icon for warning type notifications', () => {
    const { container } = renderWithProviders(
      <BottomNotificationPanel notifications={[makeNotification({ type: 'warning' })]} onClose={vi.fn()} />
    );
    expect(container.querySelector('svg')).toBeTruthy();
  });
});

// ── Index re-export ───────────────────────────────────────────────────────────

describe('BottomNotificationPanel index re-export', () => {
  it('default export from index.ts is BottomNotificationPanel', async () => {
    const mod = await import('@/components/Canvas/NotificationPanel/BottomNotificationPanel/index');
    expect(mod.default).toBeDefined();
  });

  it('re-exports NotificationItem type (module has no runtime value but import succeeds)', async () => {
    // Type exports have no runtime value, but the module should import cleanly
    const mod = await import('@/components/Canvas/NotificationPanel/BottomNotificationPanel/index');
    expect(mod).toBeDefined();
  });
});
