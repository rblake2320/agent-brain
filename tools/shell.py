"""Sandboxed shell execution tool."""
from __future__ import annotations

import asyncio
import re
import shlex
from pathlib import Path

from ..config import SANDBOX_DIR, SHELL_TIMEOUT_S, TOOL_OUTPUT_MAX_CHARS
from . import tool

# Commands/patterns that are always blocked
_BLOCKLIST = [
    re.compile(r"\brm\s+-[a-z]*r[a-z]*f\b", re.IGNORECASE),       # rm -rf
    re.compile(r"\bformat\b", re.IGNORECASE),                       # Windows format
    re.compile(r"\bdel\s+/s\b", re.IGNORECASE),                    # del /s
    re.compile(r"\brd\s+/s\b", re.IGNORECASE),                     # rd /s
    re.compile(r"\bshutdown\b", re.IGNORECASE),
    re.compile(r"\breboot\b", re.IGNORECASE),
    re.compile(r"\breg\s+(delete|add)\b", re.IGNORECASE),          # reg delete/add
    re.compile(r"\bnetsh\s+.*?firewall\b", re.IGNORECASE),
    re.compile(r">\s*/dev/sd", re.IGNORECASE),                      # writing to raw disk
    re.compile(r"\bdd\s+.*?of=/dev/sd", re.IGNORECASE),
    re.compile(r"\bkillall\b", re.IGNORECASE),
    re.compile(r"\bpkill\s+-9\b", re.IGNORECASE),
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

    cwd = Path(working_dir) if working_dir else SANDBOX_DIR
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
