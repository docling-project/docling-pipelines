import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TileContent } from '@/components/TileContent';

describe('TileContent', () => {
  it('renders the label', () => {
    render(<TileContent label="Getting Started" title="Title" subtitle="Sub" buttonLabel="Learn more" />);
    expect(screen.getByText('Getting Started')).toBeInTheDocument();
  });

  it('renders the title', () => {
    render(<TileContent label="Label" title="My Title" subtitle="Sub" buttonLabel="Go" />);
    expect(screen.getByText('My Title')).toBeInTheDocument();
  });

  it('renders the subtitle', () => {
    render(<TileContent label="Label" title="Title" subtitle="Some subtitle" buttonLabel="Go" />);
    expect(screen.getByText('Some subtitle')).toBeInTheDocument();
  });

  it('renders an anchor button when href is provided', () => {
    render(<TileContent label="L" title="T" subtitle="S" buttonLabel="Open docs" href="https://example.com" />);
    const button = screen.getByText('Open docs');
    expect(button).toBeInTheDocument();
  });

  it('renders a click button when onAction is provided', () => {
    const onAction = vi.fn();
    render(<TileContent label="L" title="T" subtitle="S" buttonLabel="Click me" onAction={onAction} />);
    expect(screen.getByText('Click me')).toBeInTheDocument();
  });

  it('calls onAction when action button is clicked', () => {
    const onAction = vi.fn();
    render(<TileContent label="L" title="T" subtitle="S" buttonLabel="Click me" onAction={onAction} />);
    screen.getByText('Click me').click();
    expect(onAction).toHaveBeenCalled();
  });
});
