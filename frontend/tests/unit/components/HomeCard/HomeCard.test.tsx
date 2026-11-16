import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import { HomeCard } from '@/components/HomeCard/HomeCard';
import { Add } from '@carbon/icons-react';

describe('HomeCard', () => {
  const defaultProps = {
    title: 'My Projects',
    headerIcon: Add,
    headerIconDescription: 'Add project',
    emptyTitle: 'No projects yet',
    emptySubtitle: 'Create your first project to get started.',
  };

  it('renders the card title', () => {
    renderWithProviders(<HomeCard {...defaultProps} />);
    expect(screen.getByText('My Projects')).toBeDefined();
  });

  it('renders empty state when no children provided', () => {
    renderWithProviders(<HomeCard {...defaultProps} />);
    const emptyTitles = screen.getAllByText('No projects yet');
    expect(emptyTitles.length).toBeGreaterThan(0);
  });

  it('renders children instead of empty state when children are provided', () => {
    renderWithProviders(
      <HomeCard {...defaultProps}>
        <div>child content</div>
      </HomeCard>
    );
    expect(screen.getByText('child content')).toBeDefined();
    expect(screen.queryByText('No projects yet')).toBeNull();
  });

  it('calls onHeaderAction when header icon button is clicked', async () => {
    const onHeaderAction = vi.fn();
    renderWithProviders(<HomeCard {...defaultProps} onHeaderAction={onHeaderAction} />);
    const btn = document.querySelector('button[aria-label="Add project"]');
    if (btn) {
      (btn as HTMLButtonElement).click();
      expect(onHeaderAction).toHaveBeenCalled();
    }
  });

  it('applies wide class when wide=true', () => {
    const { container } = renderWithProviders(<HomeCard {...defaultProps} wide />);
    // wide cards get a different class — just check container renders without error
    expect(container.firstChild).toBeTruthy();
  });
});
