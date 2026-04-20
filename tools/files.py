"""File read/write tools — scope-enforced to PKA workspace."""
from __future__ import annotations

from pathlib import Path

from ..config import DATA_DIR, PKA_ROOT, READONLY_DIRS, READONLY_PATHS
from . import tool

_SCOPE_ROOTS = (PKA_ROOT, DATA_DIR)


def _resolve_and_check(path_str: str, writing: bool = False) -> tuple[Path, str | None]:
    """Resolve path and verify it's within allowed scope. Returns (path, error_or_None)."""
    try:
        p = Path(path_str).resolve()
    except Exception as exc:
        return Path(path_str), f"Invalid path: {exc}"

    # Check readonly restrictions for writes
    if writing:
        if p in READONLY_PATHS:
            return p, f"[BLOCKED] {p.name} is read-only (Data Isolation Rule)"
        for rd in READONLY_DIRS:
            try:
                p.relative_to(rd)
                return p, f"[BLOCKED] {rd.name}/ directory is read-only (Data Isolation Rule)"
            except ValueError:
                pass

    # Check scope — must be inside PKA_ROOT or DATA_DIR
    in_scope = False
    for root in _SCOPE_ROOTS:
        try:
            p.relative_to(root)
            in_scope = True
            break
        except ValueError:
            pass

    if not in_scope:
        return p, f"[BLOCKED] Path is outside workspace scope: {p}"

    return p, None


@tool(
    name="file_read",
    description="Read a file from the PKA workspace. Returns the file contents as text.",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative path to the file. Relative paths resolved from PKA workspace root.",
            },
            "offset": {
                "type": "integer",
                "description": "Line number to start reading from (1-indexed). Default: 1.",
                "default": 1,
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to return. Default: 200.",
                "default": 200,
            },
        },
        "required": ["path"],
    },
)
async def file_read(path: str, offset: int = 1, limit: int = 200) -> str:
    # Resolve relative to PKA_ROOT if not absolute
    p = Path(path)
    if not p.is_absolute():
        p = PKA_ROOT / p

    resolved, err = _resolve_and_check(str(p), writing=False)
    if err:
        return err

    if not resolved.exists():
        return f"[ERROR] File not found: {resolved}"
    if not resolved.is_file():
        return f"[ERROR] Not a file: {resolved}"

    try:
        text = resolved.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"[ERROR] Could not read file: {exc}"

    lines = text.splitlines()
    start = max(0, offset - 1)
    chunk = lines[start : start + limit]
    result = "\n".join(chunk)
    if start + limit < len(lines):
        result += f"\n... [{len(lines) - start - limit} more lines]"
    return result


@tool(
    name="file_write",
    description=(
        "Write content to a file inside the agent_brain data directory or PKA workspace. "
        "Will not write to CLAUDE.md, owner.md, MEMORY.md, or Owner's Inbox. "
        "Creates parent directories as needed."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute or relative path to write. "
                    "Relative paths default to agent_brain/data/. "
                    "Paths inside PKA workspace are allowed but checked."
                ),
            },
            "content": {
                "type": "string",
                "description": "Text content to write.",
            },
            "mode": {
                "type": "string",
                "enum": ["write", "append"],
                "description": "Write mode: 'write' (overwrite) or 'append'. Default: write.",
                "default": "write",
            },
        },
        "required": ["path", "content"],
    },
)
async def file_write(path: str, content: str, mode: str = "write") -> str:
    p = Path(path)
    if not p.is_absolute():
        p = DATA_DIR / p

    resolved, err = _resolve_and_check(str(p), writing=True)
    if err:
        return err

    # Secret scan
    import sys
    sys.path.insert(0, str(PKA_ROOT / "scripts"))
    try:
        from pka_guardrails import check_secret_guardrail
        violations = check_secret_guardrail("Write", {"content": content})
        if violations:
            return f"[GUARDRAIL] Secret detected in content — write blocked:\n" + "\n".join(violations)
    except ImportError:
        pass  # guardrails not available, proceed

    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        open_mode = "a" if mode == "append" else "w"
        resolved.write_text(content, encoding="utf-8") if open_mode == "w" else \
            resolved.open("a", encoding="utf-8").write(content)
        return f"Written {len(content)} chars to {resolved}"
    except Exception as exc:
        return f"[ERROR] Could not write file: {exc}"
