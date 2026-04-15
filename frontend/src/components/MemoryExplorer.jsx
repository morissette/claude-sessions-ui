import { useState, useEffect } from 'react'
import './MemoryExplorer.css'

// Escape HTML special characters so raw file content cannot inject markup.
// Must be applied before any innerHTML substitution to prevent XSS.
function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

// Simple Markdown renderer — handles headings, bold, italic, code blocks, inline code.
// File content is HTML-escaped before any pattern substitution so that raw tags
// from untrusted files can never execute in the browser (XSS prevention).
function renderMarkdown(text) {
  const lines = text.split('\n')
  const elements = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    // Code block — content rendered as plain text via React children (no innerHTML)
    if (line.startsWith('```')) {
      const codeLines = []
      i++
      while (i < lines.length && !lines[i].startsWith('```')) {
        codeLines.push(lines[i])
        i++
      }
      elements.push(<pre key={i} className="memory-md__code"><code>{codeLines.join('\n')}</code></pre>)
    } else if (/^#{1,3} /.test(line)) {
      const level = line.match(/^(#+)/)[1].length
      const txt = line.replace(/^#+\s*/, '')
      const Tag = `h${Math.min(level + 2, 6)}`
      elements.push(<Tag key={i} className="memory-md__heading">{txt}</Tag>)
    } else {
      // Escape raw HTML first, then apply only safe inline markdown patterns so
      // that no HTML from the file content can ever reach dangerouslySetInnerHTML.
      const escaped = escapeHtml(line)
      const inlined = escaped
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/`(.*?)`/g, '<code>$1</code>')
        // Render links as plain text (security: no href)
        .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
      elements.push(<p key={i} className="memory-md__p" dangerouslySetInnerHTML={{__html: inlined || '\u00a0'}} />)
    }
    i++
  }
  return elements
}

function FileTree({ node, onSelect, selectedPath, depth = 0 }) {
  const [expanded, setExpanded] = useState(depth === 0)

  if (node.type === 'file') {
    return (
      <button
        className={`memory-tree__file ${selectedPath === node.path ? 'memory-tree__file--selected' : ''}`}
        onClick={() => onSelect(node.path)}
        style={{paddingLeft: `${(depth + 1) * 12}px`}}
      >
        {node.name}
      </button>
    )
  }

  return (
    <div className="memory-tree__dir">
      {depth > 0 && (
        <button
          className="memory-tree__dir-btn"
          style={{paddingLeft: `${depth * 12}px`}}
          onClick={() => setExpanded(e => !e)}
        >
          <span className="memory-tree__chevron">{expanded ? '▼' : '▶'}</span>
          {node.name}
        </button>
      )}
      {(expanded || depth === 0) && (
        <div>
          {(node.children || []).map((child, i) => (
            <FileTree key={child.path || child.name || i} node={child} onSelect={onSelect}
                      selectedPath={selectedPath} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  )
}

function MemoryFileView({ fileData, loading }) {
  if (loading) return <div className="memory-content__loading">Loading…</div>
  if (!fileData) return <div className="memory-content__placeholder">Select a file to view its contents.</div>

  const { name, content, mime, size, mtime, truncated } = fileData
  const modDate = new Date(mtime * 1000).toLocaleString()
  const sizeLabel = size > 1024 ? `${(size / 1024).toFixed(1)} KB` : `${size} B`

  return (
    <div className="memory-content__inner">
      <div className="memory-content__meta">
        <span className="memory-content__filename">{name}</span>
        <span className="memory-content__info">{sizeLabel} · modified {modDate}</span>
      </div>
      {truncated && (
        <div className="memory-content__truncation">
          Showing first 500 KB of {sizeLabel} file.
        </div>
      )}
      {mime === 'text/markdown'
        ? <div className="memory-md">{renderMarkdown(content)}</div>
        : <pre className="memory__raw">{content}</pre>
      }
    </div>
  )
}

export default function MemoryExplorer() {
  const [tree, setTree] = useState(null)
  const [selectedPath, setSelectedPath] = useState(null)
  const [fileData, setFileData] = useState(null)
  const [fileLoading, setFileLoading] = useState(false)

  useEffect(() => {
    fetch('/api/memory')
      .then(r => r.json())
      .then(setTree)
      .catch(() => {})
  }, [])

  async function selectFile(path) {
    setSelectedPath(path)
    setFileLoading(true)
    try {
      const res = await fetch(`/api/memory/file?path=${encodeURIComponent(path)}`)
      if (res.ok) setFileData(await res.json())
      else setFileData(null)
    } catch {
      setFileData(null)
    }
    setFileLoading(false)
  }

  return (
    <div className="memory-explorer">
      <div className="memory-tree">
        {tree
          ? <FileTree node={tree} onSelect={selectFile} selectedPath={selectedPath} depth={0} />
          : <div className="memory-tree__loading">Loading…</div>
        }
      </div>
      <div className="memory-content">
        <MemoryFileView fileData={fileData} loading={fileLoading} />
      </div>
    </div>
  )
}
