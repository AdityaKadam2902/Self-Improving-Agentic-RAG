import React, { useState } from 'react';

/**
 * High-performance, dependency-free Markdown & Table Renderer.
 * Supports Markdown tables, fenced code blocks with copy button,
 * inline code, bold, headers, and bullet lists.
 */
export default function MarkdownRenderer({ content }) {
  if (!content) return null;

  // Split content into blocks: code blocks, tables, and paragraphs
  const blocks = parseBlocks(content);

  return (
    <div className="markdown-rendered-content">
      {blocks.map((block, idx) => {
        if (block.type === 'code') {
          return <CodeBlock key={idx} language={block.language} code={block.code} />;
        }
        if (block.type === 'table') {
          return <TableBlock key={idx} rows={block.rows} />;
        }
        if (block.type === 'header') {
          return <HeaderBlock key={idx} level={block.level} text={block.text} />;
        }
        if (block.type === 'list') {
          return <ListBlock key={idx} items={block.items} ordered={block.ordered} />;
        }
        return <ParagraphBlock key={idx} text={block.text} />;
      })}
    </div>
  );
}

function parseBlocks(text) {
  const lines = text.split('\n');
  const blocks = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // 1. Fenced Code Block
    if (line.trim().startsWith('```')) {
      const lang = line.trim().slice(3).trim() || 'text';
      const codeLines = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        codeLines.push(lines[i]);
        i++;
      }
      blocks.push({ type: 'code', language: lang, code: codeLines.join('\n') });
      i++;
      continue;
    }

    // 2. Markdown Table Detection (| ... |)
    if (line.trim().startsWith('|') && line.trim().endsWith('|')) {
      const tableLines = [];
      while (i < lines.length && lines[i].trim().startsWith('|') && lines[i].trim().endsWith('|')) {
        tableLines.push(lines[i].trim());
        i++;
      }
      if (tableLines.length >= 2) {
        const rows = tableLines
          .filter(l => !l.replace(/\s+/g, '').match(/^\|[-:|]+\|$/)) // remove separator |---|---|
          .map(l => l.slice(1, -1).split('|').map(c => c.trim()));
        if (rows.length > 0) {
          blocks.push({ type: 'table', rows });
          continue;
        }
      }
    }

    // 3. Headers (# H1, ## H2, ### H3)
    const headerMatch = line.match(/^(#{1,3})\s+(.+)$/);
    if (headerMatch) {
      blocks.push({
        type: 'header',
        level: headerMatch[1].length,
        text: headerMatch[2].trim(),
      });
      i++;
      continue;
    }

    // 4. Bullet & Numbered Lists
    if (line.trim().match(/^(\*|-|\d+\.)\s+/)) {
      const items = [];
      const isOrdered = Boolean(line.trim().match(/^\d+\.\s+/));
      while (i < lines.length && lines[i].trim().match(/^(\*|-|\d+\.)\s+/)) {
        items.push(lines[i].trim().replace(/^(\*|-|\d+\.)\s+/, ''));
        i++;
      }
      blocks.push({ type: 'list', items, ordered: isOrdered });
      continue;
    }

    // 5. Normal Paragraph
    if (line.trim().length > 0) {
      const pLines = [];
      while (i < lines.length && lines[i].trim().length > 0 && !lines[i].trim().startsWith('```') && !lines[i].trim().startsWith('|') && !lines[i].trim().startsWith('#')) {
        pLines.push(lines[i]);
        i++;
      }
      blocks.push({ type: 'paragraph', text: pLines.join(' ') });
      continue;
    }

    i++;
  }

  return blocks;
}

function CodeBlock({ language, code }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="code-block-wrapper">
      <div className="code-block-header">
        <span>{language.toUpperCase()}</span>
        <button
          onClick={handleCopy}
          style={{
            background: 'transparent',
            border: 'none',
            color: copied ? '#4ade80' : '#94a3b8',
            fontSize: '11px',
            cursor: 'pointer',
            fontWeight: 600,
          }}
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="code-block-pre">
        <code>{code}</code>
      </pre>
    </div>
  );
}

function TableBlock({ rows }) {
  if (!rows || rows.length === 0) return null;
  const headers = rows[0];
  const bodyRows = rows.slice(1);

  return (
    <div className="markdown-table-wrapper">
      <table className="markdown-table">
        <thead>
          <tr>
            {headers.map((h, idx) => (
              <th key={idx}><InlineText text={h} /></th>
            ))}
          </tr>
        </thead>
        <tbody>
          {bodyRows.map((r, rIdx) => (
            <tr key={rIdx}>
              {r.map((cell, cIdx) => (
                <td key={cIdx}><InlineText text={cell} /></td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function HeaderBlock({ level, text }) {
  const style = { margin: '14px 0 6px', fontWeight: 700, color: 'var(--text-primary)' };
  if (level === 1) return <h2 style={{ ...style, fontSize: '18px' }}><InlineText text={text} /></h2>;
  if (level === 2) return <h3 style={{ ...style, fontSize: '16px' }}><InlineText text={text} /></h3>;
  return <h4 style={{ ...style, fontSize: '14px' }}><InlineText text={text} /></h4>;
}

function ListBlock({ items, ordered }) {
  const Tag = ordered ? 'ol' : 'ul';
  return (
    <Tag style={{ margin: '8px 0 8px 20px', color: 'var(--text-primary)', fontSize: '14px', lineHeight: 1.7 }}>
      {items.map((it, idx) => (
        <li key={idx} style={{ marginBottom: '4px' }}>
          <InlineText text={it} />
        </li>
      ))}
    </Tag>
  );
}

function ParagraphBlock({ text }) {
  return (
    <p style={{ margin: '6px 0', lineHeight: 1.7, color: 'var(--text-primary)' }}>
      <InlineText text={text} />
    </p>
  );
}

/**
 * Format inline text: bold, code, links.
 */
function InlineText({ text }) {
  if (!text) return null;

  // Split by inline code: `code`
  const codeParts = text.split(/(`[^`]+`)/g);

  return (
    <>
      {codeParts.map((part, pIdx) => {
        if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
          return (
            <code key={pIdx} className="inline-code">
              {part.slice(1, -1)}
            </code>
          );
        }

        // Split by bold: **bold**
        const boldParts = part.split(/(\*\*[^*]+\*\*)/g);
        return boldParts.map((bPart, bIdx) => {
          if (bPart.startsWith('**') && bPart.endsWith('**') && bPart.length > 4) {
            return <strong key={bIdx}>{bPart.slice(2, -2)}</strong>;
          }
          return <span key={bIdx}>{bPart}</span>;
        });
      })}
    </>
  );
}
