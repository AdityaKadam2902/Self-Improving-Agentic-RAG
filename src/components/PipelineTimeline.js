import React, { useState } from 'react';

/**
 * Interactive Glassbox Pipeline Visualizer.
 * Displays stage-by-stage execution metrics:
 * Security -> Route -> Cache -> Retrieval -> CRAG -> NLI Grounding -> Cost
 */
export default function PipelineTimeline({ telemetry }) {
  const [expanded, setExpanded] = useState(false);
  const [activeTab, setActiveTab] = useState('stages'); // 'stages' | 'claims' | 'citations'

  if (!telemetry) return null;

  const {
    latency_ms = 0,
    cost_usd = 0.0,
    cache_hit = false,
    route = 'single_hop',
    security_flags = {},
    crag = null,
    verification = null,
    grounding_score = 1.0,
    verification_verdict = 'grounded',
    citations = [],
  } = telemetry;

  const hasPii = security_flags.pii_redactions > 0 || security_flags.pii_redactions_count > 0;
  const isSuspicious = security_flags.is_suspicious;

  return (
    <div style={{
      marginTop: '10px',
      border: '1px solid var(--border)',
      borderRadius: 'var(--radius-md)',
      background: 'var(--bg-elevated)',
      overflow: 'hidden',
      fontSize: '12px',
    }}>
      {/* Top Summary Bar */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '8px 12px',
        background: 'var(--bg-surface)',
        borderBottom: expanded ? '1px solid var(--border)' : 'none',
        cursor: 'pointer',
      }} onClick={() => setExpanded(!expanded)}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
          <span style={{ fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', fontSize: '10px', letterSpacing: '0.5px' }}>
            Glassbox Pipeline
          </span>

          {/* Cache Badge */}
          {cache_hit ? (
            <span className="timeline-pill" style={{ background: 'rgba(22,163,74,0.12)', color: 'var(--green)' }}>
              Cache Hit (Sub-40ms)
            </span>
          ) : (
            <span className="timeline-pill" style={{ background: 'rgba(37,99,235,0.08)', color: 'var(--accent)' }}>
              Route: {route.toUpperCase()}
            </span>
          )}

          {/* CRAG Badge */}
          {crag && (
            <span className="timeline-pill" style={{
              background: crag.action === 'CORRECT' ? 'rgba(22,163,74,0.12)' : crag.action === 'AMBIGUOUS' ? 'rgba(217,119,6,0.12)' : 'rgba(225,29,72,0.12)',
              color: crag.action === 'CORRECT' ? 'var(--green)' : crag.action === 'AMBIGUOUS' ? 'var(--amber)' : 'var(--red)',
            }}>
              CRAG: {crag.action}
            </span>
          )}

          {/* NLI Grounding Score */}
          <span className="timeline-pill" style={{
            background: verification_verdict === 'grounded' ? 'rgba(22,163,74,0.12)' : 'rgba(225,29,72,0.12)',
            color: verification_verdict === 'grounded' ? 'var(--green)' : 'var(--red)',
          }}>
            NLI: {Math.round(grounding_score * 100)}% Grounded
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
          <span>{latency_ms ? `${Math.round(latency_ms)}ms` : '<40ms'}</span>
          <span>${Number(cost_usd || 0).toFixed(6)}</span>
          <span style={{ fontSize: '11px', fontWeight: 700 }}>{expanded ? '[-]' : '[+]'}</span>
        </div>
      </div>

      {/* Expanded Glassbox Inspection Drawer */}
      {expanded && (
        <div style={{ padding: '12px' }}>
          {/* Sub-nav Tabs */}
          <div style={{ display: 'flex', gap: '8px', marginBottom: '12px', borderBottom: '1px solid var(--border)', paddingBottom: '6px' }}>
            <button
              onClick={() => setActiveTab('stages')}
              style={{
                background: 'transparent',
                border: 'none',
                fontWeight: activeTab === 'stages' ? 700 : 500,
                color: activeTab === 'stages' ? 'var(--accent)' : 'var(--text-muted)',
                cursor: 'pointer',
                fontSize: '12px',
              }}
            >
              Stage Telemetry
            </button>
            {verification?.claim_details && verification.claim_details.length > 0 && (
              <button
                onClick={() => setActiveTab('claims')}
                style={{
                  background: 'transparent',
                  border: 'none',
                  fontWeight: activeTab === 'claims' ? 700 : 500,
                  color: activeTab === 'claims' ? 'var(--accent)' : 'var(--text-muted)',
                  cursor: 'pointer',
                  fontSize: '12px',
                }}
              >
                Atomic Claims ({verification.claim_details.length})
              </button>
            )}
            {citations && citations.length > 0 && (
              <button
                onClick={() => setActiveTab('citations')}
                style={{
                  background: 'transparent',
                  border: 'none',
                  fontWeight: activeTab === 'citations' ? 700 : 500,
                  color: activeTab === 'citations' ? 'var(--accent)' : 'var(--text-muted)',
                  cursor: 'pointer',
                  fontSize: '12px',
                }}
              >
                Source Coordinates ({citations.length})
              </button>
            )}
          </div>

          {/* Tab 1: Stages Visualizer */}
          {activeTab === 'stages' && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '8px' }}>
              {/* Security Box */}
              <div style={{ background: 'var(--bg-surface)', padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)' }}>
                <div style={{ color: 'var(--text-muted)', fontSize: '10px', fontWeight: 600, textTransform: 'uppercase' }}>1. Zero-Trust Security</div>
                <div style={{ marginTop: '4px', fontWeight: 600, color: isSuspicious ? 'var(--red)' : 'var(--green)' }}>
                  {isSuspicious ? 'Adversarial Injection Neutralized' : 'Shield Verified Clean'}
                </div>
                <div style={{ color: 'var(--text-muted)', fontSize: '11px', marginTop: '2px' }}>
                  PII Masked: {security_flags.pii_redactions || 0}
                </div>
              </div>

              {/* Economic Routing */}
              <div style={{ background: 'var(--bg-surface)', padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)' }}>
                <div style={{ color: 'var(--text-muted)', fontSize: '10px', fontWeight: 600, textTransform: 'uppercase' }}>2. Routing & Cache</div>
                <div style={{ marginTop: '4px', fontWeight: 600, color: 'var(--accent)' }}>
                  {cache_hit ? 'Cosine Vector Cache Hit' : `Dispatched: ${route}`}
                </div>
                <div style={{ color: 'var(--text-muted)', fontSize: '11px', marginTop: '2px' }}>
                  Estimated Cost: ${Number(cost_usd || 0).toFixed(6)}
                </div>
              </div>

              {/* CRAG Quality Gate */}
              <div style={{ background: 'var(--bg-surface)', padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)' }}>
                <div style={{ color: 'var(--text-muted)', fontSize: '10px', fontWeight: 600, textTransform: 'uppercase' }}>3. Corrective RAG (CRAG)</div>
                <div style={{ marginTop: '4px', fontWeight: 600, color: crag?.action === 'CORRECT' ? 'var(--green)' : 'var(--amber)' }}>
                  Status: {crag?.action || 'NOMINAL'}
                </div>
                <div style={{ color: 'var(--text-muted)', fontSize: '11px', marginTop: '2px' }}>
                  Kept: {crag?.kept_chunks ?? 'N/A'} | Discarded Distractors: {crag?.discarded_chunks ?? '0'}
                </div>
              </div>

              {/* NLI Entailment */}
              <div style={{ background: 'var(--bg-surface)', padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)' }}>
                <div style={{ color: 'var(--text-muted)', fontSize: '10px', fontWeight: 600, textTransform: 'uppercase' }}>4. NLI Verification</div>
                <div style={{ marginTop: '4px', fontWeight: 600, color: verification_verdict === 'grounded' ? 'var(--green)' : 'var(--red)' }}>
                  Verdict: {verification_verdict.toUpperCase()}
                </div>
                <div style={{ color: 'var(--text-muted)', fontSize: '11px', marginTop: '2px' }}>
                  Entailed Claims: {verification?.entailed_claims ?? 1} / {verification?.total_claims ?? 1}
                </div>
              </div>
            </div>
          )}

          {/* Tab 2: Atomic Claims Table */}
          {activeTab === 'claims' && verification?.claim_details && (
            <div style={{ overflowX: 'auto' }}>
              <table className="markdown-table" style={{ fontSize: '12px' }}>
                <thead>
                  <tr>
                    <th>Claim ID</th>
                    <th>Proposition Text</th>
                    <th>NLI Verdict</th>
                    <th>Confidence</th>
                    <th>Supporting Evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {verification.claim_details.map((c, i) => (
                    <tr key={i}>
                      <td style={{ fontFamily: 'var(--font-mono)' }}>{c.claim_id}</td>
                      <td>{c.claim_text}</td>
                      <td>
                        <span style={{
                          fontWeight: 700,
                          color: c.verdict === 'ENTAILED' ? 'var(--green)' : c.verdict === 'CONTRADICTED' ? 'var(--red)' : 'var(--amber)',
                        }}>
                          {c.verdict}
                        </span>
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)' }}>{Math.round((c.confidence || 0) * 100)}%</td>
                      <td style={{ color: 'var(--text-muted)', fontSize: '11px' }}>{c.evidence_span || c.reason || 'None'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Tab 3: Source Citations */}
          {activeTab === 'citations' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {citations.map((cit, i) => (
                <div key={i} style={{ background: 'var(--bg-surface)', padding: '8px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 600 }}>
                    <span style={{ color: 'var(--accent)' }}>[{i + 1}] {cit.source || 'Document'}</span>
                    <span style={{ color: 'var(--text-muted)', fontSize: '11px' }}>Page {cit.page || 1}</span>
                  </div>
                  {cit.evidence_quote && (
                    <p style={{ marginTop: '4px', color: 'var(--text-secondary)', fontStyle: 'italic', fontSize: '11px' }}>
                      "{cit.evidence_quote}"
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
