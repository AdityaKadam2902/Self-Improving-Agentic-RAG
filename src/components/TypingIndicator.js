import React from 'react';

export default function TypingIndicator() {
  return (
    <div style={{ display:'flex', flexDirection:'column', alignItems:'flex-start', gap:'6px', animation:'fadeUp 0.3s ease', flexShrink:0 }}>
      <div style={{ fontFamily:'var(--font-body)', fontSize:'11px', fontWeight: 600, color:'var(--text-secondary)' }}>
        AI Assistant
      </div>
      <div style={{ background:'white', border:'1px solid var(--border)', borderRadius:'8px', padding:'12px 16px', display:'flex', alignItems:'center', gap:'10px' }}>
        <div style={{ display:'flex', alignItems:'center', gap:'6px' }}>
          {[0, 0.2, 0.4].map((delay, i) => (
            <span key={i} style={{ width:'6px', height:'6px', borderRadius:'50%', background:'var(--accent)', display:'inline-block', animation:'typingBounce 1.2s infinite ease-in-out', animationDelay:`${delay}s` }} />
          ))}
        </div>
        <span style={{ fontFamily:'var(--font-body)', fontSize:'13px', color:'var(--text-secondary)' }}>
          Thinking...
        </span>
      </div>
    </div>
  );
}