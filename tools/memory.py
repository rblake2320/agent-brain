"""Memory read/write tools — thin wrappers around the MemoryStore engine."""
from __future__ import annotations

from ..memory import MemoryStore
from . import tool

_store = MemoryStore()

# Sections that cannot be modified by the agent (hardened against poisoning)
_IMMUTABLE_SECTIONS = {"Identity"}


@tool(
    name="memory_read",
    description=(
        "Read from the agent's persistent memory. "
        "Read a specific section by name, or omit section to get all memory."
    ),
    parameters={
        "type": "object",
        "properties": {
            "section": {
                "type": "string",
                "description": "Section name to read (the ## heading). Omit to read all memory.",
            },
        },
        "required": [],
    },
)
async def memory_read(section: str | None = None) -> str:
    return _store.read(section)


@tool(
    name="memory_write",
    description=(
        "Write or update a section in the agent's persistent memory. "
        "Memory persists across sessions. Use append to add to an existing section, "
        "replace to overwrite it."
    ),
    parameters={
        "type": "object",
        "properties": {
            "section": {
                "type": "string",
                "description": "Section name (creates it if it doesn't exist).",
            },
            "content": {
                "type": "string",
                "description": "Content to write into the section.",
            },
            "mode": {
                "type": "string",
                "enum": ["append", "replace"],
                "description": "append (default) adds to existing content; replace overwrites it.",
                "default": "append",
            },
        },
        "required": ["section", "content"],
    },
)
async def memory_write(section: str, content: str, mode: str = "append") -> str:
    if section in _IMMUTABLE_SECTIONS:
        return f"[BLOCKED] Section '{section}' is immutable and cannot be modified."
    # Block instruction-like content that could poison future system prompts
    _poison_patterns = [
        "ignore previous", "ignore all", "you are now", "new instructions",
        "system prompt", "from now on", "override", "maintenance mode",
    ]
    content_lower = content.lower()
    for pattern in _poison_patterns:
        if pattern in content_lower:
            return f"[BLOCKED] Memory content contains instruction-injection pattern: '{pattern}'"
    _store.write(section, content, mode)
    return f"Memory section '{section}' updated ({mode} mode)."
