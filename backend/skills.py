"""Skill export helpers for Claude Sessions UI backend."""

import json
import logging
import re
import urllib.request
from pathlib import Path

from . import constants

logger = logging.getLogger(__name__)

# ─── Skill export helpers ─────────────────────────────────────────────────────

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

The skill body should be 3-10 steps, actionable, and tool-specific where relevant.
"""


def slugify_skill_name(title: str) -> str:
    """Convert a session title to a valid kebab-case skill filename slug."""
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:60] or "untitled-skill"


def extract_session_skill_data(path: Path) -> dict:
    """Deep scan JSONL to extract tools used, first user message, last assistant message, title."""
    tools_used: set[str] = set()
    first_user_message: str | None = None
    last_assistant_message: str | None = None
    title = ""

    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = entry.get("type", "")
                if t == "assistant":
                    for block in entry.get("message", {}).get("content", []):
                        if isinstance(block, dict):
                            if block.get("type") == "tool_use":
                                name = block.get("name", "")
                                if name:
                                    tools_used.add(name)
                            elif block.get("type") == "text":
                                last_assistant_message = block.get("text", "")[:500]
                elif t == "user":
                    content = entry.get("message", {}).get("content", "")
                    if isinstance(content, str) and not first_user_message:
                        first_user_message = content[:500]
                elif t == "summary":
                    title = entry.get("summary", "")
    except OSError:
        pass

    # Fall back to first user message or file stem when no summary line was found
    if not title and first_user_message:
        title = first_user_message[:100]
    if not title:
        title = path.stem

    return {
        "tools_used": sorted(tools_used),
        "first_user_message": first_user_message or "",
        "last_assistant_message": last_assistant_message or "",
        "title": title,
    }


def resolve_skill_path(name: str, scope: str) -> Path:
    """Return a non-conflicting path for the skill file, auto-incrementing suffix if needed."""
    base_dir = (Path.cwd() / ".claude" / "skills") if scope == "local" else constants.SKILLS_DIR
    base_dir.mkdir(parents=True, exist_ok=True)
    path = base_dir / f"{name}.md"
    counter = 2
    while path.exists():
        path = base_dir / f"{name}-{counter}.md"
        counter += 1
    return path


def ollama_generate_skill(skill_data: dict) -> tuple[str, str]:
    """Call Ollama to generate a skill name and body. Returns (name, body)."""
    prompt = SKILL_PROMPT_TEMPLATE.format(
        title=skill_data["title"],
        tools=", ".join(skill_data["tools_used"]) or "none",
        intent=skill_data["first_user_message"],
        outcome=skill_data["last_assistant_message"],
    )
    payload = json.dumps({"model": constants.SUMMARY_MODEL, "prompt": prompt, "stream": False}).encode()
    req = urllib.request.Request(
        f"{constants.OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        text = json.loads(resp.read()).get("response", "")
    name_match = re.search(r"SKILL_NAME:\s*(.+)", text)
    body_match = re.search(r"SKILL_BODY:\s*\n([\s\S]+)", text)
    name = slugify_skill_name(name_match.group(1).strip() if name_match else skill_data["title"])
    body = body_match.group(1).strip() if body_match else text.strip()
    return name, body


def template_generate_skill(skill_data: dict) -> tuple[str, str]:
    """Fallback skill generator when Ollama is unavailable."""
    name = slugify_skill_name(skill_data["title"])
    tools_str = "\n".join(f"- {t}" for t in skill_data["tools_used"]) or "- (no tools recorded)"
    body = (
        f"Replicate the workflow from a session titled: {skill_data['title']}\n\n"
        f"Original intent: {skill_data['first_user_message']}\n\n"
        f"Tools used in the original session:\n{tools_str}\n\n"
        "Steps:\n"
        "1. Understand the user's goal in context\n"
        "2. Apply the tools above as appropriate\n"
        "3. Confirm the outcome matches the original intent\n"
    )
    return name, body
