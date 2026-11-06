import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import { FlowMetrics } from '@/components/FlowDetail/FlowMetrics/FlowMetrics';
import type { RunMetrics } from '@/components/FlowDetail/FlowMetrics/FlowMetrics';

const SAMPLE_METRICS: RunMetrics = {
  total: 10,
  run: 5,
  in_progress: 2,
  run_with_issues: 1,
  failed: 1,
  cancelled: 1,
};

describe('FlowMetrics', () => {
  it('renders run metrics heading with total count', () => {
    renderWithProviders(<FlowMetrics metrics={SAMPLE_METRICS} />);
    expect(screen.getByText('Run metrics (10)')).toBeDefined();
  });

  it('renders Completed metric with correct count', () => {
    renderWithProviders(<FlowMetrics metrics={SAMPLE_METRICS} />);
    expect(screen.getByText('Run')).toBeDefined();
    expect(screen.getByText('5')).toBeDefined();
  });

  it('renders In progress metric', () => {
    renderWithProviders(<FlowMetrics metrics={SAMPLE_METRICS} />);
    expect(screen.getByText('In progress')).toBeDefined();
    expect(screen.getByText('2')).toBeDefined();
  });

  it('renders Failed metric', () => {
    renderWithProviders(<FlowMetrics metrics={SAMPLE_METRICS} />);
    expect(screen.getByText('Failed')).toBeDefined();
  });

  it('renders Cancelled metric', () => {
    renderWithProviders(<FlowMetrics metrics={SAMPLE_METRICS} />);
    expect(screen.getByText('Cancelled')).toBeDefined();
  });

  it('renders Run with issues metric', () => {
    renderWithProviders(<FlowMetrics metrics={SAMPLE_METRICS} />);
    expect(screen.getByText('Run with issues')).toBeDefined();
  });

  it('renders zero counts correctly', () => {
    const zero: RunMetrics = { total: 0, run: 0, in_progress: 0, run_with_issues: 0, failed: 0, cancelled: 0 };
    renderWithProviders(<FlowMetrics metrics={zero} />);
    expect(screen.getByText('Run metrics (0)')).toBeDefined();
  });
});
