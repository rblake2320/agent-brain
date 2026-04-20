"""SSH remote execution tools — Spark-1 and Spark-2."""
from __future__ import annotations

import asyncio
from pathlib import Path

from ..config import (
    SPARK1_SSH_HOST,
    SPARK1_SSH_USER,
    SPARK2_SSH_HOST,
    SPARK2_SSH_USER,
    SSH_KEY_CANDIDATES,
    SSH_TIMEOUT_S,
    TOOL_OUTPUT_MAX_CHARS,
)
from . import tool


def _find_ssh_key() -> str | None:
    for candidate in SSH_KEY_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    return None


async def _ssh_run(ssh_args: list[str], command: str, timeout: int) -> str:
    key = _find_ssh_key()
    if key:
        ssh_args = ["-i", key] + ssh_args

    full_args = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={timeout}",
        *ssh_args,
        command,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *full_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout + 5)
        except asyncio.TimeoutError:
            proc.kill()
            return f"[TIMEOUT] SSH command exceeded {timeout}s limit."

        output = stdout.decode("utf-8", errors="replace")
        rc = proc.returncode
        if len(output) > TOOL_OUTPUT_MAX_CHARS:
            output = output[:TOOL_OUTPUT_MAX_CHARS] + f"\n... [truncated]"
        return f"[exit {rc}]\n{output}" if output.strip() else f"[exit {rc}] (no output)"
    except FileNotFoundError:
        return "[ERROR] 'ssh' not found in PATH. Ensure OpenSSH is installed."
    except Exception as exc:
        return f"[ERROR] SSH failed: {exc}"


@tool(
    name="ssh_exec",
    description=(
        "Execute a shell command on Spark-1 (192.168.12.132) or Spark-2 (10.0.0.2 via jump host). "
        "Use this to check services, run Ollama commands, view logs, or query the AI Army infrastructure. "
        "Output is truncated to 4000 chars."
    ),
    parameters={
        "type": "object",
        "properties": {
            "host": {
                "type": "string",
                "enum": ["spark1", "spark2"],
                "description": "Target host: 'spark1' (GB10 192.168.12.132) or 'spark2' (GB10 via jump).",
            },
            "command": {
                "type": "string",
                "description": "Shell command to execute on the remote host.",
            },
            "timeout": {
                "type": "integer",
                "description": f"Timeout in seconds. Max {SSH_TIMEOUT_S}s.",
                "default": SSH_TIMEOUT_S,
            },
        },
        "required": ["host", "command"],
    },
)
async def ssh_exec(host: str, command: str, timeout: int = SSH_TIMEOUT_S) -> str:
    timeout = min(timeout, SSH_TIMEOUT_S)

    if host == "spark1":
        ssh_args = [f"{SPARK1_SSH_USER}@{SPARK1_SSH_HOST}"]
    elif host == "spark2":
        ssh_args = [
            "-J", f"{SPARK1_SSH_USER}@{SPARK1_SSH_HOST}",
            f"{SPARK2_SSH_USER}@{SPARK2_SSH_HOST}",
        ]
    else:
        return f"[ERROR] Unknown host: {host}. Use 'spark1' or 'spark2'."

    return await _ssh_run(ssh_args, command, timeout)
