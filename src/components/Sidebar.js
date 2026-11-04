import React, { useState, useEffect, useRef } from 'react';
import { api } from '../api';

export default function Sidebar({ onClearChat, sessionId, onOpenMetrics }) {
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
      showStatus('success', `Indexed ${res.chunks_indexed} chunks across ${res.pages_parsed} pages`);
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
      showStatus('success', `Tuning complete: ${b} boosts applied`);
    } catch (e) { showStatus('error', e.message); }
    finally { setImproving(false); }
  };

  const ext = (name) => (name || '').split('.').pop().toUpperCase().slice(0, 4) || 'DOC';

  return (
    <aside style={{
      width: 'var(--sidebar-w)',
      minWidth: 'var(--sidebar-w)',
      background: 'var(--bg-surface)',
      borderRight: '1px solid var(--border)',
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      overflow: 'hidden',
    }}>
      {/* Platform Branding */}
      <div style={{
        padding: '18px 20px',
        borderBottom: '1px solid var(--border)',
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
      }}>
        <div style={{
          width: '36px',
          height: '36px',
          borderRadius: 'var(--radius-sm)',
          background: 'var(--accent)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'white',
          fontWeight: 800,
          fontFamily: 'var(--font-mono)',
          fontSize: '14px',
        }}>
          RAG
        </div>
        <div>
          <div style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)' }}>
            Enterprise Platform
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
            Autonomous Document Intelligence
          </div>
        </div>
      </div>

      {/* Upload Box */}
      <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '8px' }}>
          Document Ingestion
        </div>
        <div
          onDragOver={e => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={e => { e.preventDefault(); setDragging(false); const f = e.dataTransfer.files[0]; if (f) setFile(f); }}
          onClick={() => fileRef.current?.click()}
          style={{
            border: `1px dashed ${dragging ? 'var(--accent)' : 'var(--border)'}`,
            borderRadius: 'var(--radius-sm)',
            padding: '16px 12px',
            textAlign: 'center',
            cursor: 'pointer',
            background: dragging ? 'var(--accent-glow)' : 'var(--bg-elevated)',
            transition: 'all 0.15s ease',
          }}
        >
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.docx,.doc,.txt,.md,.csv,.tsv"
            style={{ display: 'none' }}
            onChange={e => setFile(e.target.files[0])}
          />
          <div style={{ fontSize: '12px', color: 'var(--text-primary)', fontWeight: 600 }}>
            {file ? file.name : 'Upload Document'}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
            PDF, DOCX, CSV, Markdown, TXT
          </div>
        </div>

        {file && (
          <button
            onClick={handleUpload}
            disabled={uploading}
            style={{
              width: '100%',
              marginTop: '10px',
              padding: '8px',
              background: 'var(--accent)',
              color: 'white',
              border: 'none',
              borderRadius: 'var(--radius-sm)',
              fontWeight: 600,
              fontSize: '12px',
              cursor: uploading ? 'default' : 'pointer',
            }}
          >
            {uploading ? 'Processing Ingestion...' : 'Index Document'}
          </button>
        )}

        {status && (
          <div style={{
            marginTop: '8px',
            padding: '6px 10px',
            borderRadius: 'var(--radius-sm)',
            fontSize: '11px',
            background: status.type === 'success' ? 'rgba(22,163,74,0.08)' : 'rgba(225,29,72,0.08)',
            color: status.type === 'success' ? 'var(--green)' : 'var(--red)',
            border: `1px solid ${status.type === 'success' ? 'rgba(22,163,74,0.2)' : 'rgba(225,29,72,0.2)'}`,
          }}>
            {status.msg}
          </div>
        )}
      </div>

      {/* Indexed Document List */}
      <div style={{ padding: '16px 20px 8px' }}>
        <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase' }}>
          Indexed Documents ({docs.length})
        </div>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '0 20px' }}>
        {docs.length === 0 ? (
          <div style={{ fontSize: '12px', color: 'var(--text-muted)', textAlign: 'center', padding: '16px 0' }}>
            No documents indexed yet
          </div>
        ) : (
          docs.map(doc => (
            <div
              key={doc.source}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                padding: '8px 0',
                borderBottom: '1px solid var(--border)',
                fontSize: '12px',
              }}
            >
              <span style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '9px',
                fontWeight: 700,
                background: 'var(--bg-elevated)',
                color: 'var(--accent)',
                padding: '2px 4px',
                borderRadius: '3px',
              }}>
                {ext(doc.source)}
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontWeight: 500 }} title={doc.source}>
                  {doc.source.split('/').pop().split('\\').pop()}
                </div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{doc.chunk_count} chunks</div>
              </div>
              <button
                onClick={() => handleDelete(doc.source)}
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: 'var(--text-muted)',
                  cursor: 'pointer',
                  fontSize: '14px',
                }}
                title="Delete document"
              >
                x
              </button>
            </div>
          ))
        )}
      </div>

      {/* Sidebar Footer Operations */}
      <div style={{ padding: '16px 20px', borderTop: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {onOpenMetrics && (
          <button
            onClick={onOpenMetrics}
            style={{
              width: '100%',
              padding: '8px',
              background: 'var(--bg-elevated)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)',
              fontSize: '12px',
              fontWeight: 600,
              cursor: 'pointer',
              color: 'var(--text-primary)',
            }}
          >
            Metrics & Benchmark
          </button>
        )}

        <button
          onClick={handleImprove}
          disabled={improving}
          style={{
            width: '100%',
            padding: '8px',
            background: 'var(--accent)',
            color: 'white',
            border: 'none',
            borderRadius: 'var(--radius-sm)',
            fontSize: '12px',
            fontWeight: 600,
            cursor: improving ? 'default' : 'pointer',
          }}
        >
          {improving ? 'Optimizing Parameters...' : 'Trigger Self-Evolution'}
        </button>

        <button
          onClick={onClearChat}
          style={{
            width: '100%',
            padding: '8px',
            background: 'var(--bg-surface)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)',
            fontSize: '12px',
            fontWeight: 500,
            cursor: 'pointer',
            color: 'var(--text-secondary)',
          }}
        >
          New Chat Session
        </button>

        <div style={{ textAlign: 'center', fontSize: '10px', color: 'var(--text-muted)', marginTop: '4px', fontFamily: 'var(--font-mono)' }}>
          SESSION: {(sessionId || '').slice(0, 8).toUpperCase()}
        </div>
      </div>
    </aside>
  );
}
