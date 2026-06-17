import React, { useState, useEffect, useRef, useCallback } from 'react';
import { api, streamChat } from './api';
import Sidebar from './components/Sidebar';
import ChatMessage from './components/ChatMessage';
import ChatInput from './components/ChatInput';
import EmptyState from './components/EmptyState';
import TypingIndicator from './components/TypingIndicator';

const SESSION_ID = (typeof crypto !== 'undefined' && crypto.randomUUID)
  ? crypto.randomUUID()
  : Math.random().toString(36).slice(2);

let msgIdCounter = 0;

export default function App() {
  const [messages, setMessages]   = useState([]);
  const [loading, setLoading]     = useState(false);
  const [streamStage, setStage]   = useState('');
  const [error, setError]         = useState(null);
  const [apiOnline, setApiOnline] = useState(null);
  const [docCount, setDocCount]   = useState(0);
  const bottomRef   = useRef(null);
  const abortRef    = useRef(null);

  // Typewriter queue — holds full text received, types it char by char
  const fullTextRef    = useRef('');  // complete text received from stream
  const displayedRef   = useRef('');  // how much we've typed so far
  const typeTimerRef   = useRef(null);
  const activeAIdRef   = useRef(null);
  const CHAR_DELAY     = 8; // ms per character — adjust for speed

  const startTypewriter = useCallback((aId) => {
    clearInterval(typeTimerRef.current);
    typeTimerRef.current = setInterval(() => {
      const full    = fullTextRef.current;
      const displayed = displayedRef.current;
      if (displayed.length < full.length) {
        // Type next character
        const next = full.slice(0, displayed.length + 1);
        displayedRef.current = next;
        setMessages(prev => prev.map(m =>
          m.id === aId ? { ...m, content: next } : m
        ));
      }
      // Don't stop here — keep running so new chunks get typed too
    }, CHAR_DELAY);
  }, []);

  const stopTypewriter = useCallback((aId, finalData) => {
    // Wait until typewriter finishes the full text, then finalise
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
      try   { await api.health(); if (alive) setApiOnline(true);  }
      catch { if (alive) setApiOnline(false); }
    };
    check();
    const t = setInterval(check, 15000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  useEffect(() => {
    let alive = true;
    const check = async () => {
      try { const d = await api.listDocuments(); if (alive) setDocCount(d.length); }
      catch {}
    };
    check();
    const t = setInterval(check, 8000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      clearInterval(typeTimerRef.current);
    };
  }, []);

  const sendMessage = useCallback((question) => {
    if (loading) return;
    setError(null);
    setLoading(true);
    setStage('Thinking…');

    // Reset typewriter state
    fullTextRef.current    = '';
    displayedRef.current   = '';
    clearInterval(typeTimerRef.current);

    // User message
    setMessages(prev => [...prev, {
      id: ++msgIdCounter, role: 'user', content: question,
    }]);

    // Empty assistant placeholder
    const aId = ++msgIdCounter;
    activeAIdRef.current = aId;
    setMessages(prev => [...prev, {
      id: aId, role: 'assistant', content: '',
      streaming: true, citations: [], verification_verdict: null,
      rewritten_query: null, originalQuery: question, _raw: null,
    }]);

    abortRef.current = streamChat(question, SESSION_ID, {
      onStatus: (stage) => setStage(stage),

      onToken: (token) => {
        // Accumulate full text
        fullTextRef.current += token;
        // Start typewriter on first token
        if (displayedRef.current === '' && fullTextRef.current.length > 0) {
          startTypewriter(aId);
        }
      },

      onDone: (data) => {
        // Ensure full text is set and let typewriter finish
        fullTextRef.current = data.answer;
        stopTypewriter(aId, data);
      },

      onError: (msg) => {
        clearInterval(typeTimerRef.current);
        setError(msg || 'Stream failed. Is the backend running?');
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
    fullTextRef.current  = '';
    displayedRef.current = '';
  }, []);

  // Show dots only when waiting (no assistant bubble with content yet)
  const lastMsg  = messages[messages.length - 1];
  const showDots = loading && lastMsg?.role === 'assistant' && lastMsg?.content === '';
  const showEmpty = messages.length === 0 && !loading;

  return (
    <div style={{ display:'flex', height:'100vh', width:'100vw', overflow:'hidden', background:'var(--bg-base)', fontFamily:'var(--font-body)' }}>
      <Sidebar onClearChat={clearChat} sessionId={SESSION_ID} />

      <div style={{ flex:1, minWidth:0, display:'flex', flexDirection:'column', height:'100vh', overflow:'hidden', background:'var(--bg-base)' }}>

        {/* Top bar */}
        <div style={{ height:'56px', flexShrink:0, display:'flex', alignItems:'center', justifyContent:'space-between', padding:'0 32px', borderBottom:'1px solid var(--border)', background:'var(--bg-surface)' }}>
          <div style={{ fontSize:'13px', fontWeight: 600, color:'var(--text-primary)' }}>Chat</div>
          <div style={{ display:'flex', alignItems:'center', gap:'12px', fontSize:'12px', color:'var(--text-secondary)' }}>
            <span>📄 {docCount} document{docCount !== 1 ? 's' : ''} indexed</span>
          </div>
        </div>

        {/* Chat scroll */}
        <div style={{ flex:1, minHeight:0, overflowY:'auto', padding:'28px 32px', display:'flex', flexDirection:'column', gap:'24px' }}>
          {showEmpty
            ? <EmptyState docCount={docCount} onSuggest={sendMessage} />
            : <>
                {messages.map((msg) => (
                  <ChatMessage key={msg.id} msg={msg}
                    onFeedback={msg.role === 'assistant' ? handleFeedback : undefined} />
                ))}
                {showDots && <TypingIndicator />}
              </>
          }
          <div ref={bottomRef} />
        </div>

        {/* Error */}
        {error && (
          <div style={{ flexShrink:0, margin:'0 24px 8px', padding:'10px 14px', background:'rgba(248,113,113,0.06)', border:'1px solid rgba(248,113,113,0.2)', borderRadius:'12px', display:'flex', alignItems:'center', gap:'8px', fontFamily:'var(--font-mono)', fontSize:'11px', color:'var(--red)' }}>
            <span>✗</span><span style={{ flex:1 }}>{error}</span>
            <button onClick={() => setError(null)} style={{ background:'none', border:'none', color:'var(--red)', cursor:'pointer', fontSize:'18px', lineHeight:1 }}>×</button>
          </div>
        )}

        <ChatInput onSend={sendMessage} loading={loading} disabled={apiOnline === false} docCount={docCount} />
      </div>
    </div>
  );
}