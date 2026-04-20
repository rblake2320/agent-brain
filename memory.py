"""Persistent file-based memory engine — MEMORY.md with ## Section headers."""
from __future__ import annotations

import re
from pathlib import Path

from .config import MEMORY_CONTEXT_MAX_CHARS, MEMORY_DIR


class MemoryStore:
    """Reads and writes to data/memory/MEMORY.md using ## Section headers."""

    def __init__(self, memory_dir: Path = MEMORY_DIR):
        self.memory_dir = memory_dir
        self.memory_file = memory_dir / "MEMORY.md"
        self._ensure_exists()

    def _ensure_exists(self) -> None:
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        if not self.memory_file.exists():
            self.memory_file.write_text(
                "# Agent Brain Memory\n\n"
                "## Identity\nI am Agent Brain, an autonomous LLM runtime running in the PKA workspace.\n\n",
                encoding="utf-8",
            )

    def read(self, section: str | None = None) -> str:
        """Read full memory or a specific section."""
        text = self.memory_file.read_text(encoding="utf-8")
        if section is None:
            return text

        # Extract the named section
        pattern = re.compile(
            rf"^## {re.escape(section)}\s*\n(.*?)(?=^## |\Z)",
            re.MULTILINE | re.DOTALL,
        )
        m = pattern.search(text)
        if m:
            return m.group(1).strip()
        return f"[No section '{section}' in memory]"

    def list_sections(self) -> list[str]:
        text = self.memory_file.read_text(encoding="utf-8")
        return re.findall(r"^## (.+)$", text, re.MULTILINE)

    def write(self, section: str, content: str, mode: str = "append") -> None:
        """Write or update a section in MEMORY.md."""
        text = self.memory_file.read_text(encoding="utf-8")
        pattern = re.compile(
            rf"(^## {re.escape(section)}\s*\n)(.*?)(?=^## |\Z)",
            re.MULTILINE | re.DOTALL,
        )
        m = pattern.search(text)
        if m:
            if mode == "append":
                new_content = m.group(2).rstrip() + "\n" + content.strip() + "\n\n"
            else:
                new_content = content.strip() + "\n\n"
            text = text[:m.start(2)] + new_content + text[m.end(2):]
        else:
            # Add new section at the end
            text = text.rstrip() + f"\n\n## {section}\n{content.strip()}\n\n"

        self.memory_file.write_text(text, encoding="utf-8")

    def get_context_block(self, max_chars: int = MEMORY_CONTEXT_MAX_CHARS) -> str:
        """Return condensed memory for injection into the system prompt."""
        text = self.memory_file.read_text(encoding="utf-8")
        if len(text) <= max_chars:
            return text.strip()
        # Truncate with indicator
        return text[:max_chars].rstrip() + "\n... [memory truncated]"
