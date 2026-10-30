import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { ThemeProvider } from '@/contexts/ThemeProvider';
import { useTheme } from '@/hooks/useTheme';
import { THEME_STORAGE_KEY } from '@/config/theme';

function ThemeConsumer() {
  const { theme, isDarkMode, toggleTheme } = useTheme();
  return React.createElement(
    'div',
    null,
    React.createElement('span', { 'data-testid': 'theme' }, theme),
    React.createElement('span', { 'data-testid': 'is-dark' }, String(isDarkMode)),
    React.createElement('button', { onClick: toggleTheme }, 'Toggle')
  );
}

beforeEach(() => {
  localStorage.clear();
});

describe('ThemeProvider', () => {
  it('children receive theme context with isDarkMode and toggleTheme', () => {
    render(React.createElement(ThemeProvider, null, React.createElement(ThemeConsumer)));
    expect(screen.getByTestId('theme')).toBeDefined();
    expect(screen.getByTestId('is-dark')).toBeDefined();
  });

  it('toggleTheme flips isDarkMode', () => {
    render(React.createElement(ThemeProvider, null, React.createElement(ThemeConsumer)));
    const before = screen.getByTestId('is-dark').textContent;
    fireEvent.click(screen.getByRole('button', { name: 'Toggle' }));
    const after = screen.getByTestId('is-dark').textContent;
    expect(after).not.toBe(before);
  });

  it('initial theme read from localStorage via getStoredTheme()', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'g10');
    render(React.createElement(ThemeProvider, null, React.createElement(ThemeConsumer)));
    expect(screen.getByTestId('theme').textContent).toBe('g10');
  });

  it('theme persisted to localStorage on toggle', () => {
    render(React.createElement(ThemeProvider, null, React.createElement(ThemeConsumer)));
    fireEvent.click(screen.getByRole('button', { name: 'Toggle' }));
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBeTruthy();
  });
});
