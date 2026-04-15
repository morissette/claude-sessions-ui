# Plan: Export Session as Skill

## Overview

A session often captures a reusable workflow — debugging a class of error, scaffolding a component type, running a specific analysis. This feature lets a user export any session as a Claude Code skill (a `.md` file in `~/.claude/skills/`) so the pattern can be invoked in future sessions via `/skill-name`.

If Ollama is available, it generates a proper skill description and body by analyzing the session's JSONL. If Ollama is unavailable, a template-based fallback is used.

---

## Background: Claude Code Skills Format

Skills live in `~/.claude/skills/*.md` with YAML frontmatter:

```markdown
---
name: debug-typescript-errors
description: Diagnose and fix TypeScript compilation errors step by step
---

When the user invokes this skill, do the following:
1. Run `tsc --noEmit` and capture output
2. Group errors by file and root cause
3. Fix errors in dependency order
4. Re-run tsc to confirm clean
```

Skills are invoked with `/skill-name` in any Claude Code session. The `name` field must be a kebab-case slug.

---

## Step 1: Backend — Skill Export Logic (`backend.py`)

### New constant

```python
SKILLS_DIR = Path.home() / ".claude" / "skills"
```

### New helper: `extract_session_skill_data(path: Path) -> dict`

Deep scan of the JSONL file to extract:
- All tools used (unique, sorted) — from `tool_use` entries
- First user message (the original intent)
- Last assistant message (the outcome/conclusion)
- Session title and project path

```python
def extract_session_skill_data(path: Path) -> dict:
    tools_used: set[str] = set()
    first_user_message: str | None = None
    last_assistant_message: str | None = None
    title = ""

    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = entry.get("type", "")
        if t == "tool_use":
            tools_used.add(entry.get("name", ""))
        elif t == "user":
            content = entry.get("content", "")
            if isinstance(content, str) and not first_user_message:
                first_user_message = content[:500]
        elif t == "assistant":
            for block in entry.get("content", []):
                if isinstance(block, dict) and block.get("type") == "text":
                    last_assistant_message = block["text"][:500]
        elif t == "summary":
            title = entry.get("summary", "")

    return {
        "tools_used": sorted(tools_used - {""}),
        "first_user_message": first_user_message or "",
        "last_assistant_message": last_assistant_message or "",
        "title": title,
    }
```

### New helper: `slugify_skill_name(title: str) -> str`

Converts a session title to a valid skill filename slug:

```python
import re

def slugify_skill_name(title: str) -> str:
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:60] or "untitled-skill"
```

### New helper: `resolve_skill_path(name: str, scope: str) -> Path`

Returns target path; avoids overwriting by appending `-2`, `-3`, etc.

```python
def resolve_skill_path(name: str, scope: str) -> Path:
    if scope == "local":
        base_dir = Path.cwd() / ".claude" / "skills"
    else:
        base_dir = SKILLS_DIR
    base_dir.mkdir(parents=True, exist_ok=True)
    path = base_dir / f"{name}.md"
    counter = 2
    while path.exists():
        path = base_dir / f"{name}-{counter}.md"
        counter += 1
    return path
```

### New helper: `ollama_generate_skill(skill_data: dict) -> tuple[str, str]`

Calls Ollama with a structured prompt. Returns `(skill_name, skill_body)`.

```python
SKILL_PROMPT_TEMPLATE = """
You are creating a Claude Code skill definition.

Session context:
- Title: {title}
- Tools used: {tools}
- Original user intent: {intent}
- Session outcome: {outcome}

Generate a reusable skill. Output EXACTLY two sections:

SKILL_NAME: <kebab-case-name-under-50-chars>
SKILL_BODY:
<markdown instructions that tell Claude what to do when this skill is invoked>

The skill body should be 3–10 steps, actionable, and tool-specific where relevant.
"""

def ollama_generate_skill(skill_data: dict) -> tuple[str, str]:
    prompt = SKILL_PROMPT_TEMPLATE.format(
        title=skill_data["title"],
        tools=", ".join(skill_data["tools_used"]) or "none",
        intent=skill_data["first_user_message"],
        outcome=skill_data["last_assistant_message"],
    )
    resp = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
        timeout=60,
    )
    resp.raise_for_status()
    text = resp.json().get("response", "")
    # Parse SKILL_NAME and SKILL_BODY from response
    name_match = re.search(r"SKILL_NAME:\s*(.+)", text)
    body_match = re.search(r"SKILL_BODY:\s*\n([\s\S]+)", text)
    name = slugify_skill_name(name_match.group(1).strip() if name_match else skill_data["title"])
    body = body_match.group(1).strip() if body_match else text.strip()
    return name, body
```

### New helper: `template_generate_skill(skill_data: dict) -> tuple[str, str]`

Fallback when Ollama unavailable:

```python
def template_generate_skill(skill_data: dict) -> tuple[str, str]:
    name = slugify_skill_name(skill_data["title"])
    tools_str = "\n".join(f"- {t}" for t in skill_data["tools_used"]) or "- (no tools recorded)"
    body = f"""Replicate the workflow from a session titled: {skill_data["title"]}

Original intent: {skill_data["first_user_message"]}

Tools used in the original session:
{tools_str}

Steps:
1. Understand the user's goal in context
2. Apply the tools above as appropriate
3. Confirm the outcome matches the original intent
"""
    return name, body
```

### New endpoint: `POST /api/sessions/{session_id}/export-skill`

```python
@app.post("/api/sessions/{session_id}/export-skill")
async def export_skill(
    session_id: str,
    scope: str = "global",  # "global" | "local"
    ollama_state: dict = Depends(get_ollama_state),  # reuse existing check
):
    if scope not in ("global", "local"):
        scope = "global"

    path = find_session_file(session_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Session not found")

    loop = asyncio.get_event_loop()
    skill_data = await loop.run_in_executor(None, extract_session_skill_data, path)

    try:
        if ollama_state.get("model_ready"):
            name, body = await loop.run_in_executor(None, ollama_generate_skill, skill_data)
        else:
            raise RuntimeError("Ollama not ready")
    except Exception:
        name, body = template_generate_skill(skill_data)

    skill_path = resolve_skill_path(name, scope)
    frontmatter = f"---\nname: {name}\ndescription: {skill_data['title']}\n---\n\n"
    skill_path.write_text(frontmatter + body, encoding="utf-8")

    return {
        "skill_name": name,
        "skill_path": str(skill_path),
        "scope": scope,
        "ollama_used": ollama_state.get("model_ready", False),
    }
```

---

## Step 2: Frontend — SessionCard Export UI

### State additions in `SessionCard.jsx`

```jsx
const [exportState, setExportState] = useState('idle')  // idle | loading | done | error
const [exportScope, setExportScope] = useState('global')
const [exportedName, setExportedName] = useState('')
```

### Export button section (rendered below existing card actions)

```jsx
<div className="card-export">
  <select
    className="export-scope"
    value={exportScope}
    onChange={e => setExportScope(e.target.value)}
    disabled={exportState === 'loading'}
  >
    <option value="global">Global skill</option>
    <option value="local">Local skill</option>
  </select>
  <button
    className={`export-btn ${exportState}`}
    disabled={exportState === 'loading' || exportState === 'done'}
    onClick={handleExport}
  >
    {exportState === 'idle' && 'Export as skill'}
    {exportState === 'loading' && 'Exporting…'}
    {exportState === 'done' && `✓ /${exportedName}`}
    {exportState === 'error' && 'Retry export'}
  </button>
</div>
```

### `handleExport` function

```js
async function handleExport() {
  setExportState('loading')
  try {
    const res = await fetch(
      `/api/sessions/${session.session_id}/export-skill?scope=${exportScope}`,
      { method: 'POST' }
    )
    if (!res.ok) throw new Error(await res.text())
    const data = await res.json()
    setExportedName(data.skill_name)
    setExportState('done')
  } catch {
    setExportState('error')
  }
}
```

### CSS additions in `SessionCard.css`

```css
.card-export {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  padding-top: 0.75rem;
  border-top: 1px solid var(--border);
}

.export-scope {
  font-size: 0.75rem;
  padding: 0.2rem 0.4rem;
  background: var(--bg-hover);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
}

.export-btn {
  font-size: 0.75rem;
  padding: 0.25rem 0.6rem;
  border-radius: 4px;
  border: 1px solid var(--border);
  cursor: pointer;
  background: var(--bg-hover);
  color: var(--text);
}
.export-btn.done { background: var(--accent); color: white; border-color: var(--accent); }
.export-btn.error { border-color: var(--cost); color: var(--cost); }
.export-btn:disabled { opacity: 0.6; cursor: not-allowed; }
```

---

## Step 3: Tests

### Backend tests (`tests/test_backend.py`)

New class `TestExportSkill`:
- `test_slugify_simple_title` — `"Debug TS Errors"` → `"debug-ts-errors"`
- `test_slugify_strips_special_chars` — punctuation removed correctly
- `test_slugify_truncates_long_names` — output ≤ 60 chars
- `test_extract_skill_data_tools` — JSONL with `tool_use` entries, verifies `tools_used`
- `test_extract_skill_data_messages` — user/assistant messages captured
- `test_resolve_skill_path_no_conflict` — returns `name.md` when file absent
- `test_resolve_skill_path_conflict` — returns `name-2.md` when `name.md` exists
- `test_template_generate_skill_returns_tuple` — returns `(str, str)`
- `test_export_endpoint_creates_file` — POST endpoint, verify file written to temp dir (monkeypatch `SKILLS_DIR`)
- `test_export_endpoint_404_unknown_session` — returns 404

### Frontend tests (`frontend/src/__tests__/SessionCard.test.jsx`)

Extend existing test file:
- `test_shows_export_button` — "Export as skill" visible
- `test_export_scope_select_present` — scope `<select>` rendered
- `test_export_success_shows_skill_name` — mock fetch resolves, shows `✓ /skill-name`
- `test_export_error_shows_retry` — mock fetch rejects, shows "Retry export"

---

## Critical Files

| File | Change |
|------|--------|
| `backend.py` | `SKILLS_DIR`, `extract_session_skill_data()`, `slugify_skill_name()`, `resolve_skill_path()`, `ollama_generate_skill()`, `template_generate_skill()`, `POST /api/sessions/{session_id}/export-skill` |
| `frontend/src/components/SessionCard.jsx` | Export state, scope select, export button, `handleExport` |
| `frontend/src/components/SessionCard.css` | `.card-export`, `.export-scope`, `.export-btn` styles |
| `tests/test_backend.py` | `TestExportSkill` class |
| `frontend/src/__tests__/SessionCard.test.jsx` | 4 new export tests |

---

## Dependency on Session Detail Plan

`find_session_file()` is defined in the session detail overlay plan. If implementing export-skill before session detail, define `find_session_file()` in the same PR. If session detail is already merged, reuse it.

---

## Edge Cases

- **Session JSONL not found**: 404 response
- **Empty session**: template fallback, skill body is minimal
- **Ollama timeout**: falls back to template — never blocks the user
- **Skill name conflict**: `resolve_skill_path` auto-increments suffix, never overwrites
- **Local scope**: writes to `{cwd}/.claude/skills/` — useful for project-specific workflows
- **Binary tool output in JSONL**: `extract_session_skill_data` reads only `type == "tool_use"` names, not output content, so no binary data ends up in the skill

---

## Verification

```bash
# Backend
pytest tests/ -v -k "TestExportSkill"

# Frontend
cd frontend && npm test -- --reporter=verbose SessionCard

# Manual
./dev.sh
# Find a session card, click "Export as skill"
# Check ~/.claude/skills/ for the new file
# cat ~/.claude/skills/<name>.md — verify frontmatter + body
# In a Claude Code session: /<name> — verify skill is recognized
# Test with Ollama off: verify template fallback produces valid skill
```
