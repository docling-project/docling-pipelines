import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '../../../../utils/renderWithProviders';
import { FlowInfoPanel } from '@/components/common/FlowInfoPanel/FlowInfoPanel';
import type { FlowPanelData } from '@/components/common/FlowInfoPanel/FlowInfoPanel';

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
