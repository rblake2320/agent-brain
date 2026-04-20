"""Sandboxed shell execution tool."""
from __future__ import annotations

import asyncio
import re
import shlex
from pathlib import Path

from ..config import DATA_DIR, PKA_ROOT, SANDBOX_DIR, SHELL_TIMEOUT_S, TOOL_OUTPUT_MAX_CHARS
from . import tool

# Commands/patterns that are always blocked
_BLOCKLIST = [
    # === Destructive ===
    re.compile(r"\brm\s+-[a-z]*r[a-z]*f\b", re.IGNORECASE),       # rm -rf
    re.compile(r"\bformat\b", re.IGNORECASE),                       # Windows format
    re.compile(r"\bdel\s+/s\b", re.IGNORECASE),                    # del /s
    re.compile(r"\brd\s+/s\b", re.IGNORECASE),                     # rd /s
    re.compile(r"\bshutdown\b", re.IGNORECASE),
    re.compile(r"\breboot\b", re.IGNORECASE),
    re.compile(r"\breg\s+(delete|add)\b", re.IGNORECASE),
    re.compile(r"\bnetsh\s+.*?firewall\b", re.IGNORECASE),
    re.compile(r">\s*/dev/sd", re.IGNORECASE),
    re.compile(r"\bdd\s+.*?of=/dev/sd", re.IGNORECASE),
    re.compile(r"\bkillall\b", re.IGNORECASE),
    re.compile(r"\bpkill\s+-9\b", re.IGNORECASE),
    re.compile(r":\(\)\s*\{.*\|.*&\s*\}\s*;", re.IGNORECASE),     # fork bomb

    # === Arbitrary code execution (injection risk) ===
    re.compile(r"\bpython\s+-c\b", re.IGNORECASE),
    re.compile(r"\bpython3\s+-c\b", re.IGNORECASE),
    re.compile(r"\bpowershell\s+(-c|-Command|-enc)", re.IGNORECASE),
    re.compile(r"\bcmd\s+/c\b", re.IGNORECASE),
    re.compile(r"\bnode\s+-e\b", re.IGNORECASE),

    # === Exfiltration ===
    re.compile(r"\bcurl\b.*https?://", re.IGNORECASE),
    re.compile(r"\bwget\b.*https?://", re.IGNORECASE),
    re.compile(r"\bInvoke-WebRequest\b", re.IGNORECASE),
    re.compile(r"\bInvoke-RestMethod\b", re.IGNORECASE),
    re.compile(r"\bnc\b\s+-", re.IGNORECASE),                      # netcat
    re.compile(r"\bncat\b", re.IGNORECASE),

    # === Credential/secret reading outside workspace ===
    re.compile(r"\b(cat|type|more|less|head|tail|Get-Content)\b.*\.(env|key|pem|token|secret)", re.IGNORECASE),
    re.compile(r"\b(cat|type|more)\b.*\\\.ssh\\", re.IGNORECASE),
    re.compile(r"\b(cat|type|more)\b.*\\\.nvidia", re.IGNORECASE),
    re.compile(r"\bprintenv\b", re.IGNORECASE),

    # === Package installation (supply chain) ===
    re.compile(r"\bpip\s+install\b", re.IGNORECASE),
    re.compile(r"\bnpm\s+install\b", re.IGNORECASE),
]


def _is_blocked(command: str) -> str | None:
    for pattern in _BLOCKLIST:
        if pattern.search(command):
            return f"[BLOCKED] Command matches safety blocklist pattern: {pattern.pattern}"
    return None


@tool(
    name="shell_exec",
    description=(
        "Execute a shell command. Working directory defaults to a sandboxed temp directory. "
        "Destructive commands (rm -rf, format, shutdown, etc.) are blocked. "
        "Output is truncated to 4000 chars. Timeout: 30s."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
            "working_dir": {
                "type": "string",
                "description": "Working directory. Defaults to agent_brain sandbox directory.",
            },
            "timeout": {
                "type": "integer",
                "description": f"Timeout in seconds. Max {SHELL_TIMEOUT_S}s.",
                "default": SHELL_TIMEOUT_S,
            },
        },
        "required": ["command"],
    },
)
async def shell_exec(
    command: str,
    working_dir: str | None = None,
    timeout: int = SHELL_TIMEOUT_S,
) -> str:
    # Safety check
    block_reason = _is_blocked(command)
    if block_reason:
        return block_reason

    timeout = min(timeout, SHELL_TIMEOUT_S)

    cwd = Path(working_dir).resolve() if working_dir else SANDBOX_DIR
    # Scope check: working_dir must be inside PKA_ROOT, DATA_DIR, or default sandbox
    in_scope = False
    for root in (PKA_ROOT, DATA_DIR, SANDBOX_DIR):
        try:
            cwd.relative_to(root)
            in_scope = True
            break
        except ValueError:
            pass
    if not in_scope:
        return f"[BLOCKED] Working directory is outside workspace scope: {cwd}"
    cwd.mkdir(parents=True, exist_ok=True)

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(cwd),
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return f"[TIMEOUT] Command exceeded {timeout}s limit and was killed."

        output = stdout.decode("utf-8", errors="replace")
        rc = proc.returncode
        if len(output) > TOOL_OUTPUT_MAX_CHARS:
            output = output[:TOOL_OUTPUT_MAX_CHARS] + f"\n... [truncated, {len(output)} chars total]"
        return f"[exit {rc}]\n{output}" if output else f"[exit {rc}] (no output)"
    except Exception as exc:
        return f"[ERROR] Failed to execute command: {exc}"
