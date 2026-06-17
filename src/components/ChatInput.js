import React, { useState, useRef, useEffect } from 'react';

export default function ChatInput({ onSend, loading, disabled, docCount }) {
  const [value, setValue] = useState('');
  const textareaRef = useRef();

  useEffect(() => {
    if (!loading && textareaRef.current) textareaRef.current.focus();
  }, [loading]);

  const autoResize = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 140) + 'px';
  };

  const submit = () => {
    const q = value.trim();
    if (!q || loading || disabled) return;
    onSend(q);
    setValue('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
  };

  const canSend = value.trim().length > 0 && !loading && !disabled;

  const s = {
    container: {
      padding: '16px 32px 24px',
      borderTop: '1px solid var(--border)',
      background: 'var(--bg-surface)',
      flexShrink: 0,
    },
    box: {
      display: 'flex', alignItems: 'flex-end', gap: '12px',
      background: 'white',
      border: '1px solid var(--border)',
      borderRadius: '8px', padding: '12px 16px',
      transition: 'border-color 0.2s ease',
      cursor: 'text',
    },
    textarea: {
      flex: 1, background: 'none', border: 'none', outline: 'none',
      resize: 'none', fontFamily: 'var(--font-body)', fontSize: '14px',
      color: 'var(--text-primary)', lineHeight: 1.6,
      maxHeight: '140px', overflowY: 'auto',
      caretColor: 'var(--accent)',
    },
    sendBtn: {
      flexShrink: 0, width: '36px', height: '36px',
      borderRadius: '6px', border: 'none',
      background: canSend ? 'var(--accent)' : 'var(--bg-elevated)',
      color: canSend ? 'white' : 'var(--text-muted)',
      cursor: canSend ? 'pointer' : 'not-allowed',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: '16px', transition: 'all 0.2s ease',
      fontWeight: 600,
    },
    spinner: {
      width: '14px', height: '14px',
      border: '2px solid var(--border)', borderTopColor: 'var(--accent)',
      borderRadius: '50%', animation: 'spin 0.7s linear infinite',
    },
    disclaimer: {
      marginTop: '10px',
      fontFamily: 'var(--font-body)',
      fontSize: '11px',
      color: 'var(--text-muted)',
      textAlign: 'center',
      lineHeight: 1.5,
      paddingLeft: '2px',
    },
  };

  const placeholder = disabled
    ? 'Backend offline — please connect to continue'
    : docCount === 0
    ? 'Upload a document to begin asking questions'
    : 'Ask a question about your documents...';

  return (
    <div style={s.container}>
      <div style={s.box}
        onMouseDown={() => textareaRef.current?.focus()}
        onFocus={e => e.currentTarget.style.borderColor = 'var(--accent)'}
        onBlur={e => e.currentTarget.style.borderColor = 'var(--border)'}>
        <textarea ref={textareaRef} value={value} rows={1} style={s.textarea}
          placeholder={placeholder} disabled={loading || disabled}
          onChange={e => { setValue(e.target.value); autoResize(); }}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); } }} />
        <button style={s.sendBtn} onClick={submit} disabled={!canSend}
          onMouseEnter={e => { if (canSend) e.currentTarget.style.background = 'var(--accent-dim)'; }}
          onMouseLeave={e => { if (canSend) e.currentTarget.style.background = 'var(--accent)'; }}>
          {loading ? <div style={s.spinner} /> : '↑'}
        </button>
      </div>
      <div style={s.disclaimer}>
        AI can make mistakes. Please recheck important information before using it.
      </div>
    </div>
  );
}