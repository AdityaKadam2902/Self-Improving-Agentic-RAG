import React, { useState } from 'react';

export default function ChatMessage({ msg, onFeedback }) {
  const [showCit,   setShowCit]   = useState(false);
  const [showTrace, setShowTrace] = useState(false);
  const [fb, setFb] = useState(null);

  const isUser = msg.role === 'user';
  const isStreaming = msg.streaming === true;
  if (!isUser && isStreaming && msg.content === '') return null;

  const doFeedback = (correct) => {
    if (fb !== null) return;
    setFb(correct ? 'correct' : 'incorrect');
    onFeedback && onFeedback(msg, correct);
  };

  const verdict = msg.verification_verdict;
  const verdictColor  = verdict === 'grounded' ? 'var(--green)' : verdict === 'hallucination' ? 'var(--red)' : 'var(--text-muted)';
  const verdictBg     = verdict === 'grounded' ? 'rgba(22,163,74,0.08)' : verdict === 'hallucination' ? 'rgba(220,38,38,0.08)' : 'var(--bg-elevated)';
  const verdictBorder = verdict === 'grounded' ? 'rgba(22,163,74,0.25)' : verdict === 'hallucination' ? 'rgba(220,38,38,0.25)' : 'var(--border)';

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: isUser ? 'flex-end' : 'flex-start',
      gap: '6px',
      animation: 'fadeUp 0.25s var(--ease)',
      flexShrink: 0,
      width: '100%',
    }}>
      {/* Role label */}
      <div style={{
        fontFamily: 'var(--font-body)', fontSize: '11px', fontWeight: 600,
        color: isUser ? 'var(--text-muted)' : 'var(--text-secondary)',
      }}>
        {isUser ? 'You' : 'AI Assistant'}
      </div>

      {/* Bubble */}
      <div style={{
        maxWidth: '68%',
        background: isUser ? 'var(--accent)' : 'white',
        border: isUser ? 'none' : '1px solid var(--border)',
        borderRadius: '8px',
        padding: '12px 16px',
        fontFamily: 'var(--font-body)',
        fontSize: '14px',
        lineHeight: 1.7,
        color: isUser ? 'white' : 'var(--text-primary)',
        wordBreak: 'break-word',
        whiteSpace: 'pre-wrap',
        minWidth: isStreaming && msg.content === '' ? '40px' : undefined,
        minHeight: isStreaming && msg.content === '' ? '44px' : undefined,
      }}>
        {msg.content}
        {/* Blinking cursor while streaming */}
        {isStreaming && (
          <span style={{
            display: 'inline-block',
            width: '2px',
            height: '1em',
            background: isUser ? 'white' : 'var(--accent)',
            marginLeft: '2px',
            verticalAlign: 'text-bottom',
            animation: 'cursorBlink 0.8s infinite',
          }} />
        )}
      </div>

      {/* Assistant metadata — only show when done streaming */}
      {!isUser && !isStreaming && (
        <>
          {/* Meta row */}
          <div style={{ display:'flex', alignItems:'center', gap:'12px', flexWrap:'wrap', marginTop: '6px' }}>
            {verdict && (
              <span style={{ fontFamily:'var(--font-body)', fontSize:'10px', fontWeight: 500, padding:'4px 8px', borderRadius:'4px', background:verdictBg, color:verdictColor, border:`1px solid ${verdictBorder}`, textTransform: 'capitalize' }}>
                {verdict}
              </span>
            )}
            {msg.latency_ms != null && (
              <span style={{ fontFamily:'var(--font-mono)', fontSize:'10px', color:'var(--text-muted)' }}>
                {msg.latency_ms}ms
              </span>
            )}
            {msg.rewritten_query && msg.rewritten_query !== msg.originalQuery && (
              <span style={{ fontFamily:'var(--font-body)', fontSize:'10px', color:'var(--accent)', maxWidth:'200px', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}
                title={msg.rewritten_query}>
                ↺ {msg.rewritten_query.slice(0,35)}{msg.rewritten_query.length > 35 ? '…' : ''}
              </span>
            )}
          </div>

          {/* Sources */}
          {msg.citations?.length > 0 && (
            <>
              <button onClick={() => setShowCit(v => !v)}
                onMouseEnter={e => e.currentTarget.style.color='var(--accent)'}
                onMouseLeave={e => e.currentTarget.style.color='var(--text-secondary)'}
                style={{ background:'none', border:'none', cursor:'pointer', fontFamily:'var(--font-body)', fontSize:'12px', color:'var(--text-secondary)', padding:'4px 0', display:'flex', alignItems:'center', gap:'6px', transition:'color 0.15s ease', fontWeight: 500 }}>
                {showCit ? '▼' : '▶'} {msg.citations.length} source{msg.citations.length !== 1 ? 's' : ''}
              </button>
              {showCit && (
                <div style={{ background:'white', border:'1px solid var(--border)', borderRadius:'8px', padding:'12px 14px', maxWidth:'68%', animation:'fadeUp 0.2s ease' }}>
                  {msg.citations.map((c, i) => (
                    <div key={i} style={{ display:'flex', gap:'10px', alignItems:'flex-start', paddingBottom: i < msg.citations.length-1 ? '8px':'0', marginBottom: i < msg.citations.length-1 ? '8px':'0', borderBottom: i < msg.citations.length-1 ? '1px solid var(--border)':'none' }}>
                      <span style={{ fontFamily:'var(--font-mono)', fontSize:'10px', color:'var(--accent)', background:'var(--accent-glow)', padding:'3px 6px', borderRadius:'4px', flexShrink:0, marginTop:'1px', fontWeight: 600 }}>{c.reference}</span>
                      <div style={{ fontFamily:'var(--font-body)', fontSize:'12px', lineHeight:1.6, flex: 1 }}>
                        <div style={{ color:'var(--text-primary)', fontWeight: 500 }}>{(c.source||'').split(/[/\\]/).pop()}</div>
                        <div style={{ color:'var(--text-muted)', fontSize:'11px' }}>Page {c.page} • Score {c.score?.toFixed(3)}</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}

          {/* Trace */}
          {msg.trace && (
            <>
              <button onClick={() => setShowTrace(v => !v)}
                onMouseEnter={e => e.currentTarget.style.color='var(--accent)'}
                onMouseLeave={e => e.currentTarget.style.color='var(--text-secondary)'}
                style={{ background:'none', border:'none', cursor:'pointer', fontFamily:'var(--font-body)', fontSize:'12px', color:'var(--text-secondary)', padding:'4px 0', display:'flex', alignItems:'center', gap:'6px', transition:'color 0.15s ease', fontWeight: 500 }}>
                {showTrace ? '▼' : '▶'} Pipeline execution
              </button>
              {showTrace && (
                <div style={{ background:'var(--bg-elevated)', border:'1px solid var(--border)', borderRadius:'8px', padding:'12px 14px', maxWidth:'68%', animation:'fadeUp 0.2s ease' }}>
                  {Object.entries(msg.trace || {}).filter(([k]) => !k.startsWith('_') && !['query','session_id'].includes(k)).slice(0,8).map(([k,v]) => (
                    <div key={k} style={{ fontFamily:'var(--font-mono)', fontSize:'11px', lineHeight:1.9, color:'var(--text-primary)' }}>
                      <span style={{ color:'var(--accent)' }}>{k}</span>
                      <span style={{ color:'var(--text-muted)' }}> → </span>
                      <span style={{ color:'var(--text-secondary)' }}>{String(v).slice(0,80)}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}

          {/* Feedback */}
          <div style={{ display:'flex', gap:'8px', alignItems:'center', marginTop: '8px' }}>
            {[
              ['correct',   '✓ Helpful',   'rgba(22,163,74,0.08)', 'rgba(22,163,74,0.35)', 'var(--green)'],
              ['incorrect', '✗ Unhelpful', 'rgba(220,38,38,0.08)', 'rgba(220,38,38,0.35)', 'var(--red)'],
            ].map(([type, label, bg, border, color]) => (
              <button key={type} onClick={() => doFeedback(type === 'correct')}
                style={{ fontFamily:'var(--font-body)', fontSize:'11px', padding:'5px 10px', borderRadius:'4px', border:`1px solid ${fb===type ? border : 'var(--border)'}`, background: fb===type ? bg : 'white', color: fb===type ? color : 'var(--text-secondary)', cursor: fb!==null ? 'default':'pointer', transition:'all 0.15s ease' }}>
                {label}
              </button>
            ))}
            {fb && <span style={{ fontFamily:'var(--font-body)', fontSize:'10px', color:'var(--text-muted)' }}>Thanks for your feedback!</span>}
          </div>
        </>
      )}
    </div>
  );
}