import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import { Home } from '@/pages/Home/Home';

describe('Home page', () => {
  it('renders without crashing', () => {
    const { container } = renderWithProviders(<Home />);
    expect(container).toBeTruthy();
  });

  it('renders ProjectsCard section', async () => {
    renderWithProviders(<Home />);
    // ProjectsCard renders a "Projects" heading in the HomeCard title
    const projectsTitle = await screen.findAllByText('Projects', {}, { timeout: 2000 });
    expect(projectsTitle.length).toBeGreaterThan(0);
  });

  it('renders FlowsCard section', async () => {
    renderWithProviders(<Home />);
    const flowsTitle = await screen.findAllByText('Flows', {}, { timeout: 2000 });
    expect(flowsTitle.length).toBeGreaterThan(0);
  });
});
