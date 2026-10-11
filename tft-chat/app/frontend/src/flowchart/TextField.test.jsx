import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import TextField from './TextField.jsx';
import { FlowchartContext } from './context.js';
afterEach(cleanup);

it('shows wrapped text and edits on demand, committing one transaction on Enter or blur', () => {
  const commit = vi.fn();
  render(<FlowchartContext.Provider value={{ readOnly: false }}><TextField label="Title" value="Readable" maxLength={120} onCommit={commit} /></FlowchartContext.Provider>);
  expect(screen.queryByRole('textbox')).toBeNull();
  fireEvent.keyDown(screen.getByRole('button', { name: 'Title' }), { key: 'Enter' });
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Changed' } });
  expect(commit).not.toHaveBeenCalled();
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
  expect(commit).toHaveBeenCalledExactlyOnceWith('Changed');
});
it('Escape cancels and multiline Enter inserts text until Ctrl/Cmd+Enter or blur commits', () => {
  const commit = vi.fn();
  render(<FlowchartContext.Provider value={{ readOnly: false }}><TextField label="Note" value="Old" multiline onCommit={commit} /></FlowchartContext.Provider>);
  fireEvent.doubleClick(screen.getByText('Old'));
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Discard' } });
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Escape' });
  expect(commit).not.toHaveBeenCalled();
  fireEvent.doubleClick(screen.getByText('Old'));
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Two\nlines' } });
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
  expect(commit).not.toHaveBeenCalled();
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter', metaKey: true });
  expect(commit).toHaveBeenCalledExactlyOnceWith('Two\nlines');
  fireEvent.doubleClick(screen.getByText('Old'));
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Blur' } }); fireEvent.blur(screen.getByRole('textbox'));
  expect(commit).toHaveBeenLastCalledWith('Blur');
});
it('read-only text cannot enter edit mode', () => {
  render(<FlowchartContext.Provider value={{ readOnly: true }}><TextField label="Title" value="Read only" onCommit={vi.fn()} /></FlowchartContext.Provider>);
  fireEvent.doubleClick(screen.getByText('Read only'));
  expect(screen.queryByRole('textbox')).toBeNull();
});
