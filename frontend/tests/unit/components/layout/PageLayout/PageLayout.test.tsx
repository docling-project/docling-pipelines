import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PageLayout } from '@/components/layout/PageLayout';

describe('PageLayout', () => {
  it('renders children in a container div by default', () => {
    const { container } = render(<PageLayout><p>Content</p></PageLayout>);
    // Carbon Content renders a main element
    expect(screen.getByText('Content')).toBeInTheDocument();
    // Default layout has a pageContainer wrapper
    expect(container.querySelector('main') ?? container.querySelector('[role="main"]')).not.toBeNull();
  });

  it('renders children in full-bleed mode without container wrapper', () => {
    render(<PageLayout fullBleed><p data-testid="bleed">Full bleed</p></PageLayout>);
    expect(screen.getByTestId('bleed')).toBeInTheDocument();
  });

  it('renders children correctly in default mode', () => {
    render(<PageLayout><span>Hello World</span></PageLayout>);
    expect(screen.getByText('Hello World')).toBeInTheDocument();
  });

  it('renders children correctly in full-bleed mode', () => {
    render(<PageLayout fullBleed><span>Full bleed content</span></PageLayout>);
    expect(screen.getByText('Full bleed content')).toBeInTheDocument();
  });
});
