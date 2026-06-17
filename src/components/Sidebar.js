import React, { useState, useEffect, useRef } from 'react';
import { api } from '../api';

export default function Sidebar({ onClearChat, sessionId }) {
  const [file, setFile] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [docs, setDocs] = useState([]);
  const [improving, setImproving] = useState(false);
  const [status, setStatus] = useState(null);
  const fileRef = useRef();

  const loadDocs = async () => {
    try { setDocs(await api.listDocuments()); } catch {}
  };

  useEffect(() => {
    loadDocs();
    const t = setInterval(loadDocs, 10000);
    return () => clearInterval(t);
  }, []);

  const showStatus = (type, msg) => {
    setStatus({ type, msg });
    setTimeout(() => setStatus(null), 4000);
  };

  const handleUpload = async () => {
    if (!file || uploading) return;
    setUploading(true);
    try {
      const res = await api.uploadDocument(file);
      showStatus('success', `✓ ${res.chunks_indexed} chunks · ${res.pages_parsed} pages`);
      setFile(null);
      loadDocs();
    } catch (e) { showStatus('error', e.message); }
    finally { setUploading(false); }
  };

  const handleDelete = async (source) => {
    try { await api.deleteDocument(source); loadDocs(); }
    catch (e) { showStatus('error', e.message); }
  };

  const handleImprove = async () => {
    setImproving(true);
    try {
      const res = await api.triggerImprovement();
      const b = res.optimization?.keyword_boosts_added || 0;
      showStatus('success', `✓ ${b} boosts · ${res.optimization?.prompt_updated ? 'prompt updated' : 'done'}`);
    } catch (e) { showStatus('error', e.message); }
    finally { setImproving(false); }
  };

  const ext = (name) => (name || '').split('.').pop().toUpperCase().slice(0, 3) || 'DOC';

  const s = {
    sidebar: {
      width: 'var(--sidebar-w)', minWidth: 'var(--sidebar-w)',
      background: 'var(--bg-surface)', borderRight: '1px solid var(--border)',
      display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden',
    },
    header: {
      padding: '20px',
      borderBottom: '1px solid var(--border)',
      display: 'flex', alignItems: 'flex-start', gap: '12px',
    },
    iconBox: {
      width: '40px', height: '40px', borderRadius: '8px',
      background: 'var(--accent)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: '18px', flexShrink: 0, color: 'white', fontWeight: 600,
    },
    logoText: {
      fontFamily: 'var(--font-display)', fontWeight: 600, fontSize: '15px',
      color: 'var(--text-primary)', letterSpacing: '0',
    },
    logoSub: {
      fontFamily: 'var(--font-body)', fontSize: '12px',
      color: 'var(--text-secondary)', marginTop: '3px',
    },
    section: { padding: '16px 16px 0' },
    sectionLabel: {
      fontFamily: 'var(--font-body)', fontSize: '11px', fontWeight: 600,
      color: 'var(--text-primary)', marginBottom: '10px',
    },
    dropZone: {
      border: `2px dashed ${dragging ? 'var(--accent)' : 'var(--border)'}`,
      borderRadius: '8px', padding: '24px 16px',
      textAlign: 'center', cursor: 'pointer',
      background: dragging ? 'var(--accent-glow)' : 'white',
      transition: 'all 0.2s ease',
    },
    dropIcon: {
      fontSize: '24px', marginBottom: '8px',
      color: dragging ? 'var(--accent)' : 'var(--text-muted)',
    },
    dropText: {
      fontFamily: 'var(--font-body)', fontSize: '12px',
      color: dragging ? 'var(--accent)' : 'var(--text-secondary)', lineHeight: 1.6,
    },
    uploadBtn: {
      width: '100%', marginTop: '10px', padding: '10px',
      background: uploading ? 'var(--bg-elevated)' : 'var(--accent)',
      color: uploading ? 'var(--text-muted)' : 'white',
      border: 'none', borderRadius: '6px',
      fontFamily: 'var(--font-body)', fontWeight: 600, fontSize: '13px',
      cursor: uploading ? 'not-allowed' : 'pointer',
      transition: 'all 0.2s ease',
    },
    docList: { flex: 1, overflowY: 'auto', padding: '12px 16px' },
    docItem: {
      display: 'flex', alignItems: 'center', gap: '10px',
      padding: '10px', borderRadius: '6px', marginBottom: '6px',
      background: 'white', border: '1px solid var(--border)',
      animation: 'fadeUp 0.3s ease',
    },
    docBadge: {
      fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'white',
      background: 'var(--accent)', padding: '2px 5px',
      borderRadius: '3px', flexShrink: 0, textTransform: 'uppercase', fontWeight: 600,
    },
    docName: {
      fontFamily: 'var(--font-body)', fontSize: '11px', color: 'var(--text-primary)',
      flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontWeight: 500,
    },
    docChunks: { fontFamily: 'var(--font-body)', fontSize: '10px', color: 'var(--text-muted)' },
    deleteBtn: {
      background: 'none', border: 'none', cursor: 'pointer',
      color: 'var(--text-muted)', fontSize: '16px', padding: '0 4px',
      borderRadius: '4px', lineHeight: 1, flexShrink: 0,
      transition: 'color 0.15s',
    },
    footer: {
      padding: '14px 16px', borderTop: '1px solid var(--border)',
      display: 'flex', flexDirection: 'column', gap: '10px',
    },
    improveBtn: {
      width: '100%', padding: '10px',
      background: improving ? 'var(--bg-elevated)' : 'var(--accent)',
      color: improving ? 'var(--text-muted)' : 'white',
      border: 'none',
      borderRadius: '6px',
      fontFamily: 'var(--font-body)', fontWeight: 600, fontSize: '13px',
      cursor: improving ? 'not-allowed' : 'pointer',
      transition: 'all 0.2s ease', display: 'flex', alignItems: 'center',
      justifyContent: 'center', gap: '6px',
    },
    clearBtn: {
      width: '100%', padding: '10px',
      background: 'white', color: 'var(--text-secondary)',
      border: '1px solid var(--border)', borderRadius: '6px',
      fontFamily: 'var(--font-body)', fontSize: '13px', fontWeight: 600,
      cursor: 'pointer', transition: 'all 0.2s ease',
      display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px',
    },
    sessionLabel: {
      fontFamily: 'var(--font-body)', fontSize: '10px',
      color: 'var(--text-muted)', textAlign: 'center',
    },
    statusMsg: (type) => ({
      fontFamily: 'var(--font-body)', fontSize: '11px',
      padding: '8px 10px', borderRadius: '6px', marginTop: '8px',
      background: type === 'success' ? 'rgba(22,163,74,0.08)' : 'rgba(220,38,38,0.08)',
      color: type === 'success' ? 'var(--green)' : 'var(--red)',
      border: `1px solid ${type === 'success' ? 'rgba(22,163,74,0.2)' : 'rgba(220,38,38,0.2)'}`,
      animation: 'fadeIn 0.2s ease', lineHeight: 1.5,
    }),
  };

  return (
    <aside style={s.sidebar}>
      <div style={s.header}>
        <div style={s.iconBox}>◈</div>
        <div>
          <div style={s.logoText}>RAG Workspace</div>
          <div style={s.logoSub}>Document search and answers</div>
        </div>
      </div>

      <div style={s.section}>
        <div style={s.sectionLabel}>Upload a Document</div>
        <div style={s.dropZone}
          onDragOver={e => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={e => { e.preventDefault(); setDragging(false); const f = e.dataTransfer.files[0]; if (f) setFile(f); }}
          onClick={() => fileRef.current?.click()}
        >
          <input ref={fileRef} type="file" accept=".pdf,.docx,.txt"
            style={{ display: 'none' }} onChange={e => setFile(e.target.files[0])} />
          <div style={s.dropIcon}>{file ? '📄' : '↑'}</div>
          <div style={s.dropText}>
            {file ? file.name : <>Drop PDF, DOCX, TXT<br />or click here to browse</>}
          </div>
        </div>
        {file && (
          <button style={s.uploadBtn} onClick={handleUpload} disabled={uploading}>
            {uploading ? '⟳ Indexing…' : '↑ Index Document'}
          </button>
        )}
        {status && <div style={s.statusMsg(status.type)}>{status.msg}</div>}
      </div>

      <div style={{ ...s.section, marginTop: '14px' }}>
        <div style={s.sectionLabel}>Indexed Documents {docs.length > 0 && `(${docs.length})`}</div>
      </div>
      <div style={s.docList}>
        {docs.length === 0
          ? <div style={{ fontFamily: 'var(--font-body)', fontSize: '11px', color: 'var(--text-muted)', textAlign: 'center', paddingTop: '12px' }}>No documents indexed yet</div>
          : docs.map(doc => (
            <div key={doc.source} style={s.docItem}>
              <span style={s.docBadge}>{ext(doc.source)}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={s.docName} title={doc.source}>{doc.source.split('/').pop().split('\\').pop()}</div>
                <div style={s.docChunks}>{doc.chunk_count} chunks</div>
              </div>
              <button style={s.deleteBtn} onClick={() => handleDelete(doc.source)}
                onMouseEnter={e => e.currentTarget.style.color = 'var(--red)'}
                onMouseLeave={e => e.currentTarget.style.color = 'var(--text-muted)'}>×</button>
            </div>
          ))
        }
      </div>

      <div style={s.footer}>
        <button style={s.improveBtn} onClick={handleImprove} disabled={improving}
          onMouseEnter={e => { if (!improving) e.currentTarget.style.background = 'var(--accent-dim)'; }}
          onMouseLeave={e => { if (!improving) e.currentTarget.style.background = 'var(--accent)'; }}>
          <span>⟳</span>{improving ? 'Optimizing…' : 'Self-Improve'}
        </button>
        <button style={s.clearBtn} onClick={onClearChat}
          onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--accent)'; e.currentTarget.style.color = 'var(--accent)'; }}
          onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.color = 'var(--text-secondary)'; }}>
          ↺ New Chat
        </button>
        <div style={s.sessionLabel}>Session {(sessionId || '').slice(0, 8).toUpperCase()}</div>
      </div>
    </aside>
  );
}