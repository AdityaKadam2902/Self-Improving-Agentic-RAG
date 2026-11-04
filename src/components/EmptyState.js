import React from 'react';

const suggestions = [
  'Summarize the key financial findings in this document.',
  'What are the main architectural constraints and latency SLAs?',
  'What zero-trust security policies are enforced?',
  'Extract table data and compare quarter-over-quarter metrics.',
  'List the most important quantitative metrics or dates.',
];

export default function EmptyState({ onSuggest, docCount = 0 }) {
  const hasDocuments = docCount > 0;

  return (
    <div style={{
      flex: 1,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '48px 32px',
      gap: '24px',
    }}>
      {/* Brand Icon Box */}
      <div style={{
        width: '64px',
        height: '64px',
        borderRadius: 'var(--radius-md)',
        background: 'var(--accent)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: '20px',
        fontWeight: 800,
        color: 'white',
        letterSpacing: '1px',
        fontFamily: 'var(--font-mono)',
        boxShadow: '0 4px 12px var(--accent-glow)',
      }}>
        RAG
      </div>

      <div style={{
        fontFamily: 'var(--font-display)',
        fontWeight: 700,
        fontSize: '24px',
        color: 'var(--text-primary)',
        letterSpacing: '-0.5px',
        textAlign: 'center',
      }}>
        Autonomous Document Intelligence Platform
      </div>

      <div style={{
        fontFamily: 'var(--font-body)',
        fontSize: '14px',
        color: 'var(--text-secondary)',
        textAlign: 'center',
        maxWidth: '500px',
        lineHeight: 1.6,
      }}>
        Zero-trust security shield, sub-40ms semantic caching, Corrective RAG (CRAG) quality gating, and claim-level NLI verification.
      </div>

      {!hasDocuments ? (
        <div style={{
          fontFamily: 'var(--font-body)',
          fontSize: '13px',
          color: 'var(--text-secondary)',
          textAlign: 'center',
          padding: '16px 24px',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-md)',
          background: 'var(--bg-surface)',
          maxWidth: '380px',
          lineHeight: 1.6,
        }}>
          Upload a document (PDF, DOCX, CSV, Markdown, or TXT) in the left panel to begin.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', width: '100%', maxWidth: '520px' }}>
          <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', textAlign: 'center' }}>
            Recommended Enterprise Inquiries
          </div>
          {suggestions.map((text, i) => (
            <button
              key={i}
              onClick={() => onSuggest(text)}
              style={{
                background: 'var(--bg-surface)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-sm)',
                padding: '10px 14px',
                color: 'var(--text-primary)',
                fontFamily: 'var(--font-body)',
                fontSize: '13px',
                cursor: 'pointer',
                textAlign: 'left',
                transition: 'all 0.15s ease',
              }}
              onMouseEnter={e => {
                e.currentTarget.style.borderColor = 'var(--accent)';
                e.currentTarget.style.backgroundColor = 'var(--bg-elevated)';
                e.currentTarget.style.color = 'var(--accent)';
              }}
              onMouseLeave={e => {
                e.currentTarget.style.borderColor = 'var(--border)';
                e.currentTarget.style.backgroundColor = 'var(--bg-surface)';
                e.currentTarget.style.color = 'var(--text-primary)';
              }}
            >
              {text}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
