import React, { useState } from 'react';
import MarkdownRenderer from './MarkdownRenderer';
import PipelineTimeline from './PipelineTimeline';

export default function ChatMessage({ msg, onFeedback }) {
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
  const verdictColor = verdict === 'grounded' ? 'var(--green)' : verdict === 'hallucination' ? 'var(--red)' : 'var(--text-muted)';
  const verdictBg = verdict === 'grounded' ? 'rgba(22,163,74,0.08)' : verdict === 'hallucination' ? 'rgba(225,29,72,0.08)' : 'var(--bg-elevated)';
  const verdictBorder = verdict === 'grounded' ? 'rgba(22,163,74,0.25)' : verdict === 'hallucination' ? 'rgba(225,29,72,0.25)' : 'var(--border)';

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
      {/* Role Label */}
      <div style={{
        fontFamily: 'var(--font-body)',
        fontSize: '11px',
        fontWeight: 600,
        color: isUser ? 'var(--text-muted)' : 'var(--text-secondary)',
      }}>
        {isUser ? 'You' : 'Autonomous Document Intelligence Assistant'}
      </div>

      {/* Message Bubble */}
      <div style={{
        maxWidth: isUser ? '75%' : '85%',
        background: isUser ? 'var(--accent)' : 'var(--bg-surface)',
        border: isUser ? 'none' : '1px solid var(--border)',
        borderRadius: 'var(--radius-md)',
        padding: '12px 18px',
        fontFamily: 'var(--font-body)',
        fontSize: '14px',
        lineHeight: 1.7,
        color: isUser ? 'white' : 'var(--text-primary)',
        wordBreak: 'break-word',
        boxShadow: isUser ? 'none' : '0 1px 3px rgba(0,0,0,0.04)',
      }}>
        {isUser ? (
          <div style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</div>
        ) : (
          <MarkdownRenderer content={msg.content} />
        )}

        {/* Blinking cursor while streaming */}
        {isStreaming && (
          <span style={{
            display: 'inline-block',
            width: '2px',
            height: '1em',
            background: isUser ? 'white' : 'var(--accent)',
            marginLeft: '4px',
            verticalAlign: 'text-bottom',
            animation: 'cursorBlink 0.8s infinite',
          }} />
        )}
      </div>

      {/* Assistant Glassbox Pipeline Timeline & Telemetry */}
      {!isUser && !isStreaming && (
        <div style={{ maxWidth: '85%', width: '100%' }}>
          {/* Glassbox Pipeline Visualizer */}
          <PipelineTimeline
            telemetry={{
              latency_ms: msg.latency_ms,
              cost_usd: msg.cost_usd,
              cache_hit: msg.cache_hit,
              route: msg.route,
              security_flags: msg.security_flags,
              crag: msg.crag,
              verification: msg.verification,
              grounding_score: msg.grounding_score,
              verification_verdict: msg.verification_verdict,
              citations: msg.citations,
            }}
          />

          {/* Feedback Rating Bar */}
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginTop: '8px' }}>
            <button
              onClick={() => doFeedback(true)}
              style={{
                fontFamily: 'var(--font-body)',
                fontSize: '11px',
                fontWeight: 600,
                padding: '4px 10px',
                borderRadius: 'var(--radius-sm)',
                border: `1px solid ${fb === 'correct' ? 'rgba(22,163,74,0.35)' : 'var(--border)'}`,
                background: fb === 'correct' ? 'rgba(22,163,74,0.08)' : 'var(--bg-surface)',
                color: fb === 'correct' ? 'var(--green)' : 'var(--text-secondary)',
                cursor: fb !== null ? 'default' : 'pointer',
                transition: 'all 0.15s ease',
              }}
            >
              Grounding Accurate
            </button>
            <button
              onClick={() => doFeedback(false)}
              style={{
                fontFamily: 'var(--font-body)',
                fontSize: '11px',
                fontWeight: 600,
                padding: '4px 10px',
                borderRadius: 'var(--radius-sm)',
                border: `1px solid ${fb === 'incorrect' ? 'rgba(225,29,72,0.35)' : 'var(--border)'}`,
                background: fb === 'incorrect' ? 'rgba(225,29,72,0.08)' : 'var(--bg-surface)',
                color: fb === 'incorrect' ? 'var(--red)' : 'var(--text-secondary)',
                cursor: fb !== null ? 'default' : 'pointer',
                transition: 'all 0.15s ease',
              }}
            >
              Report Hallucination
            </button>
            {fb && (
              <span style={{ fontFamily: 'var(--font-body)', fontSize: '11px', color: 'var(--text-muted)' }}>
                Recorded in SQLite feedback ledger.
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
