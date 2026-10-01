/** Readable, wrapped text that enters a transaction only when editing is committed. */
import React, { useEffect, useRef, useState } from 'react';
import { useFlowchart } from './context.js';

/** Edit on double-click/Enter. Escape cancels, blur commits, multiline uses Ctrl/Cmd+Enter. */
export default function TextField({ value = '', label, placeholder = '', maxLength, multiline = false, onCommit, className = '', prefix = '', suffix = '' }) {
  const { readOnly } = useFlowchart();
  const [editing, setEditing] = useState(false), [draft, setDraft] = useState(value);
  const cancelled = useRef(false), input = useRef(null);
  useEffect(() => { if (editing) { input.current?.focus(); input.current?.select(); } }, [editing]);
  const begin = () => { if (!readOnly) { cancelled.current = false; setDraft(value); setEditing(true); } };
  const finish = () => { if (!cancelled.current && draft !== value) onCommit(draft); setEditing(false); };
  if (!editing) return <span tabIndex={readOnly ? undefined : 0} role={readOnly ? undefined : 'button'}
    className={`flowchart-text ${className}`} aria-label={label} title={value || placeholder}
    onDoubleClick={begin} onKeyDown={(event) => { if (event.key === 'Enter') { event.stopPropagation(); begin(); } }}>
    {prefix && <span aria-hidden="true">{prefix}</span>}{value || <span className="flowchart-placeholder">{placeholder}</span>}{suffix && <span aria-hidden="true">{suffix}</span>}
  </span>;
  const Tag = multiline ? 'textarea' : 'input';
  return <Tag ref={input} className={`nodrag nopan nowheel flowchart-text-editor ${className}`} aria-label={label}
    value={draft} maxLength={maxLength} onChange={(event) => setDraft(event.target.value)} onBlur={finish}
    onKeyDown={(event) => {
      event.stopPropagation();
      if (event.key === 'Escape') { event.preventDefault(); cancelled.current = true; setEditing(false); }
      else if (event.key === 'Enter' && (!multiline || event.ctrlKey || event.metaKey)) { event.preventDefault(); finish(); }
    }} />;
}
