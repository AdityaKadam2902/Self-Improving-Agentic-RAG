import React from 'react';

const suggestions = [
  'Summarize the key findings in this document.',
  'What are the main arguments made by the author?',
  'Compare the methodology in different sections.',
  'What conclusions does the document reach?',
  'List the most important statistics or data points.',
];

export default function EmptyState({ onSuggest, hasDocuments, docCount }) {
  const s = {
    wrapper: {
      flex: 1, display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      padding: '48px 32px', gap: '32px',
    },
    iconWrap: {
      width: '80px', height: '80px', borderRadius: '12px',
      background: 'var(--accent)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: '36px', animation: 'fadeIn 0.5s var(--ease)',
      color: 'white',
    },
    headline: {
      fontFamily: 'var(--font-display)', fontWeight: 600, fontSize: '28px',
      color: 'var(--text-primary)', letterSpacing: '0',
      textAlign: 'center', animation: 'fadeUp 0.4s var(--ease)',
    },
    sub: {
      fontFamily: 'var(--font-body)', fontSize: '15px',
      color: 'var(--text-secondary)', textAlign: 'center',
      maxWidth: '420px', lineHeight: 1.7,
      animation: 'fadeUp 0.5s var(--ease)',
    },
    uploadHint: {
      fontFamily: 'var(--font-body)', fontSize: '13px',
      color: 'var(--text-secondary)', textAlign: 'center',
      padding: '18px 28px', border: '1px solid var(--border)',
      borderRadius: '8px', maxWidth: '320px', lineHeight: 1.7,
      animation: 'fadeUp 0.5s var(--ease)',
    },
    sugLabel: {
      fontFamily: 'var(--font-body)', fontSize: '12px', fontWeight: 600,
      color: 'var(--text-primary)', textAlign: 'center',
    },
    suggestions: {
      display: 'flex', flexDirection: 'column', gap: '10px',
      width: '100%', maxWidth: '520px', animation: 'fadeUp 0.6s var(--ease)',
    },
    sugBtn: {
      background: 'white', border: '1px solid var(--border)',
      borderRadius: '8px', padding: '12px 16px',
      color: 'var(--text-primary)', fontFamily: 'var(--font-body)',
      fontSize: '14px', cursor: 'pointer', textAlign: 'left',
      transition: 'all 0.2s ease', lineHeight: 1.6,
      fontWeight: 500,
    },
  };

  return (
    <div style={s.wrapper}>
      <div style={s.iconWrap}>⬢</div>
      <div style={s.headline}>Document Intelligence</div>
      <div style={s.sub}>
        Upload documents and ask questions with AI-powered retrieval,
        intelligent reranking, and continuous self-improvement.
      </div>

      {!hasDocuments ? (
        <div style={s.uploadHint}>
          ← Upload a document in the sidebar<br />
          to start asking questions
        </div>
      ) : (
        <div style={s.suggestions}>
          <div style={s.sugLabel}>Suggested Questions</div>
          {suggestions.map((text, i) => (
            <button key={i} style={s.sugBtn} onClick={() => onSuggest(text)}
              onMouseEnter={e => {
                e.currentTarget.style.borderColor = 'var(--accent)';
                e.currentTarget.style.backgroundColor = 'var(--accent-glow)';
                e.currentTarget.style.color = 'var(--accent)';
              }}
              onMouseLeave={e => {
                e.currentTarget.style.borderColor = 'var(--border)';
                e.currentTarget.style.backgroundColor = 'white';
                e.currentTarget.style.color = 'var(--text-primary)';
              }}>
              {text}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}