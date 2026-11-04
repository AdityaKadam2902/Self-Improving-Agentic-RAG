import React, { useState, useEffect, useRef, useCallback } from 'react';
import { api, streamChat } from './api';
import Sidebar from './components/Sidebar';
import ChatMessage from './components/ChatMessage';
import ChatInput from './components/ChatInput';
import EmptyState from './components/EmptyState';
import TypingIndicator from './components/TypingIndicator';
import MetricsDashboard from './components/MetricsDashboard';

const SESSION_ID = (typeof crypto !== 'undefined' && crypto.randomUUID)
  ? crypto.randomUUID()
  : Math.random().toString(36).slice(2);

let msgIdCounter = 0;

export default function App() {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [streamStage, setStage] = useState('');
  const [error, setError] = useState(null);
  const [apiOnline, setApiOnline] = useState(null);
  const [docCount, setDocCount] = useState(0);
  const [activeView, setActiveView] = useState('chat'); // 'chat' | 'metrics'
  const [darkMode, setDarkMode] = useState(false);

  const bottomRef = useRef(null);
  const abortRef = useRef(null);

  // Typewriter queue
  const fullTextRef = useRef('');
  const displayedRef = useRef('');
  const typeTimerRef = useRef(null);
  const activeAIdRef = useRef(null);
  const CHAR_DELAY = 8;

  // Dark mode effect
  useEffect(() => {
    if (darkMode) {
      document.body.classList.add('dark');
    } else {
      document.body.classList.remove('dark');
    }
  }, [darkMode]);

  const startTypewriter = useCallback((aId) => {
    clearInterval(typeTimerRef.current);
    typeTimerRef.current = setInterval(() => {
      const full = fullTextRef.current;
      const displayed = displayedRef.current;
      if (displayed.length < full.length) {
        const next = full.slice(0, displayed.length + 1);
        displayedRef.current = next;
        setMessages(prev => prev.map(m =>
          m.id === aId ? { ...m, content: next } : m
        ));
      }
    }, CHAR_DELAY);
  }, []);

  const stopTypewriter = useCallback((aId, finalData) => {
    const finish = setInterval(() => {
      if (displayedRef.current.length >= fullTextRef.current.length) {
        clearInterval(finish);
        clearInterval(typeTimerRef.current);
        setMessages(prev => prev.map(m =>
          m.id === aId ? {
            ...m,
            streaming: false,
            content: fullTextRef.current,
            citations: finalData.citations || [],
            verification_verdict: finalData.verification_verdict,
            grounding_score: finalData.grounding_score ?? 1.0,
            verification: finalData.verification || null,
            latency_ms: finalData.latency_ms,
            cache_hit: finalData.cache_hit,
            cost_usd: finalData.cost_usd,
            route: finalData.route,
            security_flags: finalData.security_flags || {},
            crag: finalData.crag || null,
            rewritten_query: finalData.rewritten_query,
            _raw: finalData,
          } : m
        ));
        setLoading(false);
        setStage('');
      }
    }, 20);
  }, []);

  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        await api.health();
        if (alive) setApiOnline(true);
      } catch {
        if (alive) setApiOnline(false);
      }
    };
    check();
    const t = setInterval(check, 15000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const d = await api.listDocuments();
        if (alive) setDocCount(d.length);
      } catch {}
    };
    check();
    const t = setInterval(check, 8000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    return () => {
      clearInterval(typeTimerRef.current);
    };
  }, []);

  const sendMessage = useCallback((question) => {
    if (loading) return;
    setError(null);
    setLoading(true);
    setStage('Initializing pipeline...');

    fullTextRef.current = '';
    displayedRef.current = '';
    clearInterval(typeTimerRef.current);

    setMessages(prev => [...prev, {
      id: ++msgIdCounter,
      role: 'user',
      content: question,
    }]);

    const aId = ++msgIdCounter;
    activeAIdRef.current = aId;
    setMessages(prev => [...prev, {
      id: aId,
      role: 'assistant',
      content: '',
      streaming: true,
      citations: [],
      verification_verdict: null,
      grounding_score: 1.0,
      verification: null,
      rewritten_query: null,
      originalQuery: question,
      _raw: null,
    }]);

    abortRef.current = streamChat(question, SESSION_ID, {
      onStatus: (stage) => setStage(stage),

      onToken: (token) => {
        fullTextRef.current += token;
        if (displayedRef.current === '' && fullTextRef.current.length > 0) {
          startTypewriter(aId);
        }
      },

      onDone: (data) => {
        fullTextRef.current = data.answer;
        stopTypewriter(aId, data);
      },

      onError: (msg) => {
        clearInterval(typeTimerRef.current);
        setError(msg || 'Stream connection failed. Verify backend service is running.');
        setMessages(prev => prev.filter(m => m.id !== aId));
        setLoading(false);
        setStage('');
      },
    });
  }, [loading, startTypewriter, stopTypewriter]);

  const handleFeedback = useCallback(async (msg, isCorrect) => {
    try {
      await api.sendFeedback({
        session_id: SESSION_ID,
        question: msg.originalQuery || '',
        answer: msg.content,
        rewritten_query: msg.rewritten_query || msg.originalQuery || '',
        citations: msg.citations || [],
        is_correct: isCorrect,
        verification_verdict: msg.verification_verdict || 'unknown',
        grounding_score: msg.grounding_score || 1.0,
        latency_ms: msg.latency_ms || 0.0,
        cost_usd: msg.cost_usd || 0.0,
      });
    } catch {}
  }, []);

  const clearChat = useCallback(async () => {
    abortRef.current?.abort();
    clearInterval(typeTimerRef.current);
    try { await api.clearSession(SESSION_ID); } catch {}
    setMessages([]);
    setLoading(false);
    setError(null);
    setStage('');
    fullTextRef.current = '';
    displayedRef.current = '';
  }, []);

  const lastMsg = messages[messages.length - 1];
  const showDots = loading && lastMsg?.role === 'assistant' && lastMsg?.content === '';
  const showEmpty = messages.length === 0 && !loading;

  return (
    <div style={{
      display: 'flex',
      height: '100vh',
      width: '100vw',
      overflow: 'hidden',
      background: 'var(--bg-base)',
      fontFamily: 'var(--font-body)',
    }}>
      <Sidebar
        onClearChat={clearChat}
        sessionId={SESSION_ID}
        onOpenMetrics={() => setActiveView(activeView === 'metrics' ? 'chat' : 'metrics')}
      />

      <div style={{
        flex: 1,
        minWidth: 0,
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        overflow: 'hidden',
        background: 'var(--bg-base)',
      }}>
        {/* Top Control Bar */}
        <div style={{
          height: '56px',
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 28px',
          borderBottom: '1px solid var(--border)',
          background: 'var(--bg-surface)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <span style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)' }}>
              {activeView === 'metrics' ? 'Observability & Evaluation' : 'Live Document Inquiry'}
            </span>
            {streamStage && (
              <span style={{
                fontSize: '11px',
                color: 'var(--accent)',
                fontWeight: 600,
                fontFamily: 'var(--font-mono)',
                animation: 'pulse 1.5s infinite',
              }}>
                [STAGE: {streamStage}]
              </span>
            )}
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <button
              onClick={() => setActiveView(activeView === 'metrics' ? 'chat' : 'metrics')}
              style={{
                background: activeView === 'metrics' ? 'var(--accent-glow)' : 'var(--bg-elevated)',
                color: activeView === 'metrics' ? 'var(--accent)' : 'var(--text-secondary)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-sm)',
                padding: '5px 12px',
                fontSize: '12px',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              {activeView === 'metrics' ? 'View Live Chat' : 'System Metrics'}
            </button>

            <button
              onClick={() => setDarkMode(!darkMode)}
              style={{
                background: 'var(--bg-elevated)',
                color: 'var(--text-secondary)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-sm)',
                padding: '5px 10px',
                fontSize: '12px',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              {darkMode ? 'Light Theme' : 'Dark Theme'}
            </button>

            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
              Indexed Documents: {docCount}
            </span>
          </div>
        </div>

        {/* View Switcher: Metrics Dashboard vs Chat Pane */}
        {activeView === 'metrics' ? (
          <MetricsDashboard onClose={() => setActiveView('chat')} />
        ) : (
          <>
            {/* Chat Message Stream */}
            <div style={{
              flex: 1,
              minHeight: 0,
              overflowY: 'auto',
              padding: '24px 32px',
              display: 'flex',
              flexDirection: 'column',
              gap: '20px',
            }}>
              {showEmpty ? (
                <EmptyState docCount={docCount} onSuggest={sendMessage} />
              ) : (
                <>
                  {messages.map((msg) => (
                    <ChatMessage
                      key={msg.id}
                      msg={msg}
                      onFeedback={msg.role === 'assistant' ? handleFeedback : undefined}
                    />
                  ))}
                  {showDots && <TypingIndicator />}
                </>
              )}
              <div ref={bottomRef} />
            </div>

            {/* Error Notification */}
            {error && (
              <div style={{
                flexShrink: 0,
                margin: '0 24px 8px',
                padding: '10px 14px',
                background: 'rgba(225,29,72,0.08)',
                border: '1px solid rgba(225,29,72,0.25)',
                borderRadius: 'var(--radius-sm)',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                fontFamily: 'var(--font-mono)',
                fontSize: '12px',
                color: 'var(--red)',
              }}>
                <span style={{ flex: 1 }}>{error}</span>
                <button
                  onClick={() => setError(null)}
                  style={{ background: 'none', border: 'none', color: 'var(--red)', cursor: 'pointer', fontSize: '14px' }}
                >
                  x
                </button>
              </div>
            )}

            <ChatInput
              onSend={sendMessage}
              loading={loading}
              disabled={apiOnline === false}
              docCount={docCount}
            />
          </>
        )}
      </div>
    </div>
  );
}
