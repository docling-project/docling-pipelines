import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '../../../../utils/renderWithProviders';
import { FlowInfoPanel } from '@/components/common/FlowInfoPanel/FlowInfoPanel';
import type { FlowPanelData } from '@/components/common/FlowInfoPanel/FlowInfoPanel';
import { authStateFixture } from '../../../../mocks/fixtures/store.fixture';
import { PERMISSION_SCENARIOS, authPreloadedState } from '../../../../mocks/fixtures/permission.fixture';

const SAMPLE_FLOW: FlowPanelData = {
  flow_id: 'flow-1',
  name: 'My Flow',
  description: 'A test flow',
  tags: ['nlp', 'ocr'],
  created_on: '1/1/2024',
  modified_on: '3/15/2024',
  project_name: 'Test Project',
};

function renderPanel(props: Partial<Parameters<typeof FlowInfoPanel>[0]> = {}) {
  const defaults = {
    flow: SAMPLE_FLOW,
    onClose: vi.fn(),
    onViewFlow: vi.fn(),
    onViewProject: vi.fn(),
    onEdit: vi.fn(),
    ...props,
  };
  return { ...renderWithProviders(<FlowInfoPanel {...defaults} />), ...defaults };
}

describe('FlowInfoPanel', () => {
  it('renders the "About flow" heading', () => {
    renderPanel();
    expect(screen.getByText('About flow')).toBeDefined();
  });

  it('renders the flow name as a link', () => {
    renderPanel();
    expect(screen.getByText('My Flow')).toBeDefined();
  });

  it('renders the project name as a link', () => {
    renderPanel();
    expect(screen.getByText('Test Project')).toBeDefined();
  });

  it('renders description', () => {
    renderPanel();
    expect(screen.getByText('A test flow')).toBeDefined();
  });

  it('renders tags', () => {
    renderPanel();
    expect(screen.getByText('nlp')).toBeDefined();
    expect(screen.getByText('ocr')).toBeDefined();
  });

  it('renders created_on and modified_on dates', () => {
    renderPanel();
    expect(screen.getByText('1/1/2024')).toBeDefined();
    expect(screen.getByText('3/15/2024')).toBeDefined();
  });

  it('close button calls onClose', () => {
    const { onClose } = renderPanel();
    fireEvent.click(screen.getByLabelText('Close panel'));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('flow name button calls onViewFlow', () => {
    const { onViewFlow } = renderPanel();
    fireEvent.click(screen.getByText('My Flow'));
    expect(onViewFlow).toHaveBeenCalledOnce();
  });

  it('project name button calls onViewProject', () => {
    const { onViewProject } = renderPanel();
    fireEvent.click(screen.getByText('Test Project'));
    expect(onViewProject).toHaveBeenCalledOnce();
  });
});

describe('FlowInfoPanel permission gating', () => {
  describe.each(PERMISSION_SCENARIOS)('$name', ({ role, owner, allowed }) => {
    it('gates the edit button using created_by from the flow data', () => {
      renderWithProviders(
        <FlowInfoPanel
          flow={{ ...SAMPLE_FLOW, created_by: owner }}
          onClose={vi.fn()}
          onViewFlow={vi.fn()}
          onViewProject={vi.fn()}
          onEdit={vi.fn()}
        />,
        { preloadedState: authPreloadedState(role) }
      );
      expect(screen.getByRole('button', { name: 'Edit flow details' }).hasAttribute('disabled')).toBe(!allowed);
    });
  });

  it('calls onEdit when the caller may modify the flow', () => {
    const onEdit = vi.fn();
    renderPanel({ onEdit, flow: { ...SAMPLE_FLOW, created_by: 'me' } });
    // default store fixture is an auth-disabled admin
    fireEvent.click(screen.getByRole('button', { name: 'Edit flow details' }));
    expect(onEdit).toHaveBeenCalledTimes(1);
  });

  it('shows the missing-role tooltip for a viewer', () => {
    renderWithProviders(
      <FlowInfoPanel flow={{ ...SAMPLE_FLOW, created_by: 'me' }} onClose={vi.fn()} onViewFlow={vi.fn()} onViewProject={vi.fn()} onEdit={vi.fn()} />,
      { preloadedState: authPreloadedState('viewer') }
    );
    expect(screen.getByText('You need the editor role to do this', { selector: '[role="tooltip"] *' })).toBeInTheDocument();
  });

  it('shows the ownership tooltip for a non-owner editor', () => {
    renderWithProviders(
      <FlowInfoPanel flow={{ ...SAMPLE_FLOW, created_by: 'other' }} onClose={vi.fn()} onViewFlow={vi.fn()} onViewProject={vi.fn()} onEdit={vi.fn()} />,
      { preloadedState: authPreloadedState('editor') }
    );
    expect(screen.getByText('Only the owner or an administrator can change this', { selector: '[role="tooltip"] *' })).toBeInTheDocument();
  });

  // Canvas does not pass created_by: the owner is resolved from the store (default fixture: "test-user").
  describe('without created_by (Canvas usage)', () => {
    function renderCanvasStyle(username: string, role: 'viewer' | 'editor' | 'admin') {
      renderWithProviders(
        <FlowInfoPanel flow={SAMPLE_FLOW} onClose={vi.fn()} onViewFlow={vi.fn()} onViewProject={vi.fn()} onEdit={vi.fn()} />,
        { preloadedState: { auth: authStateFixture({ role, username }) } }
      );
      return screen.getByRole('button', { name: 'Edit flow details' });
    }

    it('enables edit for the owning editor', () => {
      expect(renderCanvasStyle('test-user', 'editor').hasAttribute('disabled')).toBe(false);
    });

    it('disables edit for a non-owner editor', () => {
      expect(renderCanvasStyle('someone-else', 'editor').hasAttribute('disabled')).toBe(true);
    });

    it('enables edit for an admin', () => {
      expect(renderCanvasStyle('someone-else', 'admin').hasAttribute('disabled')).toBe(false);
    });

    it('disables edit for a viewer', () => {
      expect(renderCanvasStyle('test-user', 'viewer').hasAttribute('disabled')).toBe(true);
    });
  });
});
