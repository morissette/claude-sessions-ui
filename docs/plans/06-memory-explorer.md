# Feature 6: Memory Explorer

**Phase:** 2 — Intelligence | **Effort:** L | **Target:** Q3 2026

---

## Overview

Add a "Memory" tab to the dashboard that lets users browse and read Claude's entire memory system: `~/.claude/memory/`, CLAUDE.md files (global and per-project), skills, commands, agents, hooks, and `settings.json`. The left panel shows a file tree; the right panel renders the selected file as read-only Markdown. This is strictly a read-only browser — no editing.

---

## Problem / Motivation

Claude's memory and configuration spread across multiple directories and formats that are invisible without a terminal. Developers accumulate memory files, hooks, and skills over months without knowing what Claude "knows". The Memory Explorer provides a GUI window into Claude's persistent state, helping users audit and understand their Claude configuration without leaving the dashboard.

Security is the central concern: the backend must never expose files outside `~/.claude/`.

---

## Acceptance Criteria

- [ ] A "Memory" tab in the toolbar switches the main content area to the Memory Explorer
- [ ] The left panel shows a file tree scoped to safe subdirectories of `~/.claude/`
- [ ] Clicking a file in the tree loads its content in the right panel
- [ ] Markdown files render as formatted HTML (headings, bold, code blocks, links as plain text)
- [ ] JSON and plain text files render in a `<pre>` block with monospace font
- [ ] File metadata (size, last modified) is shown below the file name in the right panel
- [ ] The backend rejects any path that resolves outside `~/.claude/` via symlink or traversal — returns HTTP 403
- [ ] Directory entries that do not exist on disk are not shown in the tree (graceful degradation)
- [ ] Large files (>500KB) show a truncation notice and only the first 500KB of content

---

## Backend Changes

### Allowed directories (allowlist)

Add constant to `backend.py`:

```python
CLAUDE_BASE_DIR = Path.home() / ".claude"

MEMORY_ALLOWLIST = [
    "memory",
    "projects",      # per-project CLAUDE.md files
    "commands",
    "agents",
    "skills",
    "hooks",
    "todos",
]
MEMORY_ALLOWLIST_FILES = [
    "settings.json",
    "settings.local.json",
    "CLAUDE.md",
]
```

### Path validation function

```python
def validate_memory_path(rel_path: str) -> Path:
    """
    Resolve rel_path relative to CLAUDE_BASE_DIR.
    Raises HTTPException(403) if the resolved path escapes CLAUDE_BASE_DIR
    or is not within an allowlisted subdirectory.
    """
    # Reject null bytes
    if "\x00" in rel_path:
        raise HTTPException(status_code=403, detail="Invalid path")

    resolved = (CLAUDE_BASE_DIR / rel_path).resolve()
    base_resolved = CLAUDE_BASE_DIR.resolve()

    # Symlink escape check
    if not str(resolved).startswith(str(base_resolved) + "/") and resolved != base_resolved:
        raise HTTPException(status_code=403, detail="Path outside allowed directory")

    # Allowlist check: first component of rel_path must be in MEMORY_ALLOWLIST
    # or the full rel_path must be an allowlisted root file
    parts = Path(rel_path).parts
    if not parts:
        raise HTTPException(status_code=403, detail="Empty path")

    root = parts[0]
    if root not in MEMORY_ALLOWLIST and rel_path not in MEMORY_ALLOWLIST_FILES:
        raise HTTPException(status_code=403, detail="Directory not allowed")

    return resolved
```

### New endpoint: `GET /api/memory`

Returns a recursive directory tree of allowed entries:

```python
@app.get("/api/memory")
async def get_memory_tree():
    def _build_tree(base: Path) -> dict:
        tree = {"type": "dir", "name": ".claude", "children": []}
        # Add allowlisted files at root
        for fname in MEMORY_ALLOWLIST_FILES:
            fp = base / fname
            if fp.exists() and fp.is_file():
                tree["children"].append({
                    "type": "file",
                    "name": fname,
                    "path": fname,
                    "size": fp.stat().st_size,
                    "mtime": fp.stat().st_mtime,
                })
        # Add allowlisted directories
        for dname in MEMORY_ALLOWLIST:
            dp = base / dname
            if dp.exists() and dp.is_dir():
                tree["children"].append(_build_dir(dp, dname))
        return tree

    def _build_dir(directory: Path, rel_prefix: str) -> dict:
        children = []
        try:
            for entry in sorted(directory.iterdir()):
                rel = f"{rel_prefix}/{entry.name}"
                if entry.is_symlink():
                    continue  # skip symlinks entirely
                if entry.is_file():
                    children.append({
                        "type": "file",
                        "name": entry.name,
                        "path": rel,
                        "size": entry.stat().st_size,
                        "mtime": entry.stat().st_mtime,
                    })
                elif entry.is_dir() and not entry.name.startswith("."):
                    children.append(_build_dir(entry, rel))
        except PermissionError:
            pass  # silently skip unreadable directories
        return {"type": "dir", "name": directory.name, "path": rel_prefix, "children": children}

    tree = await asyncio.get_event_loop().run_in_executor(None, lambda: _build_tree(CLAUDE_BASE_DIR))
    return tree
```

**Response schema:**

```json
{
  "type": "dir",
  "name": ".claude",
  "children": [
    {"type": "file", "name": "settings.json", "path": "settings.json", "size": 1432, "mtime": 1744000000.0},
    {"type": "dir",  "name": "memory", "path": "memory", "children": [
      {"type": "file", "name": "user_role.md", "path": "memory/user_role.md", "size": 312, "mtime": 1744000100.0}
    ]}
  ]
}
```

**Symlinks are explicitly skipped** in `_build_dir` — `is_symlink()` check before `is_file()`/`is_dir()`.

### New endpoint: `GET /api/memory/file`

```python
@app.get("/api/memory/file")
async def get_memory_file(path: str):
    resolved = validate_memory_path(path)  # raises 403 if invalid

    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    MAX_SIZE = 500 * 1024  # 500KB
    stat = resolved.stat()
    truncated = stat.st_size > MAX_SIZE

    content = resolved.read_bytes()[:MAX_SIZE].decode("utf-8", errors="replace")

    # Determine MIME type
    suffix = resolved.suffix.lower()
    mime = "text/markdown" if suffix in (".md", ".markdown") else \
           "application/json" if suffix == ".json" else "text/plain"

    return {
        "path": path,
        "name": resolved.name,
        "content": content,
        "mime": mime,
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "truncated": truncated,
    }
```

---

## Frontend Changes

### New toolbar tab in `App.jsx`

Add `"memory"` to the view mode options (alongside `"sessions"` and `"projects"`):

```jsx
<button
  className={`toolbar__view-btn ${viewMode === 'memory' ? 'active' : ''}`}
  onClick={() => setViewMode('memory')}
>Memory</button>
```

When `viewMode === 'memory'`, render `<MemoryExplorer />` instead of the session list.

### New component: `frontend/src/components/MemoryExplorer.jsx`

Internal state:

```javascript
const [tree, setTree] = useState(null)
const [selectedPath, setSelectedPath] = useState(null)
const [fileData, setFileData] = useState(null)
const [fileLoading, setFileLoading] = useState(false)
```

On mount, fetch the tree:

```javascript
useEffect(() => {
  fetch('/api/memory').then(r => r.json()).then(setTree)
}, [])
```

On file select:

```javascript
async function selectFile(path) {
  setSelectedPath(path)
  setFileLoading(true)
  const data = await fetch(`/api/memory/file?path=${encodeURIComponent(path)}`).then(r => r.json())
  setFileData(data)
  setFileLoading(false)
}
```

**Layout (two-panel):**

```
┌─────────────────────┬──────────────────────────────────┐
│  File Tree          │  File Content                    │
│                     │                                  │
│  ▼ .claude          │  memory/user_role.md             │
│    ▶ memory         │  312 bytes · modified 2h ago     │
│    ▶ commands       │  ─────────────────────────────── │
│      settings.json  │  # User Role                     │
│                     │  Marie is a senior engineer...   │
│                     │                                  │
└─────────────────────┴──────────────────────────────────┘
```

**File tree rendering (`FileTree` sub-component):**
- Recursive component — `FileTree` renders a `<ul>` of entries
- Directories have a toggle (▶/▼) to expand/collapse
- Files are clickable `<button>` elements
- Keyboard-accessible: Enter/Space to select, ArrowUp/Down to navigate

**Content rendering (`MemoryFileView` sub-component):**

- `mime === "text/markdown"` → simple Markdown renderer:
  - `# heading` → `<h1>`, `## heading` → `<h2>`
  - `` `code` `` → `<code>`, triple-backtick blocks → `<pre><code>`
  - `**bold**` → `<strong>`, `*italic*` → `<em>`
  - `[text](url)` → plain text (do NOT render as clickable links — prevents SSRF if a file contains a URL)
  - Implement as a ~40-line function; no `marked.js` dependency needed for this subset
- Other MIME types → `<pre className="memory__raw">{content}</pre>`
- Truncation notice: `if (fileData.truncated)` → yellow banner "Showing first 500KB of {size}…"

### New CSS: `frontend/src/components/MemoryExplorer.css`

Key layout:

```css
.memory-explorer { display: grid; grid-template-columns: 260px 1fr; height: 100%; }
.memory-tree { overflow-y: auto; border-right: 1px solid var(--border); }
.memory-content { overflow-y: auto; padding: 1rem 1.5rem; }
```

---

## Security Considerations

This feature has the largest attack surface of all 10 features. Security requirements are non-negotiable.

- **Symlink traversal:** `_build_dir` skips all symlinks. `validate_memory_path` uses `os.path.realpath()` (via `Path.resolve()`) to catch symlinks that escape `~/.claude/`.
- **Path traversal (`../`):** `validate_memory_path` resolves the full path and checks it starts with `CLAUDE_BASE_DIR.resolve()`. A path like `memory/../../.ssh/id_rsa` resolves to `~/.ssh/id_rsa`, which does not start with `~/.claude/` → 403.
- **Null byte injection:** Explicitly rejected before `Path()` construction.
- **Allowlist enforcement:** Even a valid `~/.claude/` path is rejected if its first component is not in `MEMORY_ALLOWLIST` (e.g., `projects/some-session.jsonl` is not in the allowlist — only known safe subdirs are exposed).
- **No execution:** `get_memory_file` only reads bytes — no shell execution, no import, no eval.
- **Content rendering:** Markdown renderer produces only trusted HTML tags. Links are rendered as plain text, not as `<a href>` elements, to prevent users from accidentally clicking SSRF-inducing URLs stored in memory files.

### Required security tests

```python
# Must all return 403, not 200 or 500
test_path_traversal_dotdot: path="../../etc/passwd"
test_path_traversal_encoded: path="%2e%2e%2fetc%2fpasswd"  (URL decoded before validate)
test_path_traversal_null_byte: path="memory/\x00../../etc/passwd"
test_symlink_escape: create a symlink inside ~/.claude/memory/ pointing to /etc → API returns 403
test_non_allowlisted_dir: path="some-new-dir/file.txt" → 403 even if dir exists
test_allowlisted_file_direct: path="settings.json" → 200
```

---

## Performance Considerations

- The file tree is built once on `GET /api/memory` — subsequent file reads are individual requests. No full-tree caching needed; the tree is small.
- `_build_dir` is synchronous but fast (directory enumeration, no file reads). Run in thread pool to avoid blocking the event loop.
- `read_bytes()[:500KB]` limits memory usage for large files.
- The Markdown renderer is a simple regex pass — O(n) on file size.

---

## Testing Requirements

### Backend unit tests

- `test_validate_memory_path_valid`: `"memory/user.md"` → resolves correctly
- `test_validate_memory_path_dotdot`: `"memory/../../etc/passwd"` → raises 403
- `test_validate_memory_path_null_byte`: `"memory/\x00evil"` → raises 403
- `test_validate_memory_path_non_allowlisted`: `"random_dir/file"` → raises 403
- `test_get_memory_tree_structure`: mock `CLAUDE_BASE_DIR`, verify tree shape
- `test_get_memory_file_truncation`: file > 500KB → `truncated: true`, content length ≤ 500KB
- `test_get_memory_file_404`: nonexistent path in allowed dir → 404
- `test_symlink_skipped_in_tree`: directory containing a symlink → symlink not in tree response

### Frontend tests (Vitest)

- `FileTree` renders directory expand/collapse
- `MemoryFileView` renders Markdown headings correctly
- `MemoryFileView` does NOT render links as `<a>` tags
- Truncation banner appears when `fileData.truncated === true`

### Manual QA checklist

- [ ] Click "Memory" tab → file tree loads
- [ ] Expand a directory → child entries appear
- [ ] Click `settings.json` → JSON content renders in `<pre>` block
- [ ] Click a `.md` file → headings, bold, code blocks render correctly
- [ ] A link in a Markdown file renders as plain text, not a clickable link
- [ ] Test path traversal from browser: `GET /api/memory/file?path=../../etc/passwd` → 403
- [ ] Very large file → truncation notice visible

---

## Out of Scope

- Editing memory files (read-only by design per ROADMAP "reads, never writes" principle)
- Searching within memory files (use browser's Ctrl+F)
- Diffing memory file versions
- Creating or deleting memory files
