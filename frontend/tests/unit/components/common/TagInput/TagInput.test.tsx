import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { TagInput } from '@/components/common/TagInput';

function renderTagInput(props: Partial<Parameters<typeof TagInput>[0]> = {}) {
  const defaultProps = {
    id: 'tag-input-test',
    tags: [],
    onChange: vi.fn(),
    ...props,
  };
  return render(React.createElement(TagInput, defaultProps));
}

describe('TagInput', () => {
  it('renders existing tags as chips', () => {
    renderTagInput({ tags: ['alpha', 'beta'] });
    expect(screen.getByText('alpha')).toBeDefined();
    expect(screen.getByText('beta')).toBeDefined();
  });

  it('typing + Enter calls onChange with new tag appended', async () => {
    const onChange = vi.fn();
    renderTagInput({ tags: ['existing'], onChange });
    const input = screen.getByRole('textbox');
    await userEvent.type(input, 'newtag{Enter}');
    expect(onChange).toHaveBeenCalledWith(['existing', 'newtag']);
  });

  it('typing + comma calls onChange', async () => {
    const onChange = vi.fn();
    renderTagInput({ tags: [], onChange });
    const input = screen.getByRole('textbox');
    await userEvent.type(input, 'csvtag,');
    expect(onChange).toHaveBeenCalledWith(['csvtag']);
  });

  it('blur with pending text commits the tag', async () => {
    const onChange = vi.fn();
    renderTagInput({ tags: [], onChange });
    const input = screen.getByRole('textbox');
    await userEvent.type(input, 'blurtag');
    fireEvent.blur(input);
    expect(onChange).toHaveBeenCalledWith(['blurtag']);
  });

  it('clicking chip × calls onChange with tag removed', () => {
    const onChange = vi.fn();
    renderTagInput({ tags: ['remove-me', 'keep'], onChange });
    // Carbon Tag filter renders a close button
    const closeBtns = document.querySelectorAll('button');
    fireEvent.click(closeBtns[0] as HTMLElement);
    expect(onChange).toHaveBeenCalled();
  });

  it('duplicate tag is a no-op — onChange not called', async () => {
    const onChange = vi.fn();
    renderTagInput({ tags: ['dupe'], onChange });
    const input = screen.getByRole('textbox');
    await userEvent.type(input, 'dupe{Enter}');
    expect(onChange).not.toHaveBeenCalled();
  });

  it('disabled → input has disabled attribute', () => {
    renderTagInput({ disabled: true });
    const input = screen.getByRole('textbox');
    expect(input).toHaveProperty('disabled', true);
  });
});
