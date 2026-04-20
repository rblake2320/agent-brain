"""Tool registry — @tool decorator and OpenAI function-calling schema export."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable

TOOL_REGISTRY: dict[str, "ToolDef"] = {}

# Callback for human approval gate — set by the agent before running.
# Signature: async def(tool_name: str, arguments: dict) -> bool
_approval_callback: Callable | None = None


def set_approval_callback(fn: Callable) -> None:
    global _approval_callback
    _approval_callback = fn


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict        # JSON Schema for the tool's arguments
    handler: Callable       # async def handler(**kwargs) -> str
    requires_approval: bool = False


def tool(
    name: str,
    description: str,
    parameters: dict,
    requires_approval: bool = False,
) -> Callable:
    """Decorator to register an async function as an agent tool."""
    def decorator(fn: Callable) -> Callable:
        TOOL_REGISTRY[name] = ToolDef(
            name=name,
            description=description,
            parameters=parameters,
            handler=fn,
            requires_approval=requires_approval,
        )
        return fn
    return decorator


def get_openai_tools_schema() -> list[dict]:
    """Return all registered tools in OpenAI function-calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in TOOL_REGISTRY.values()
    ]


async def execute_tool(name: str, arguments: dict[str, Any]) -> str:
    """Dispatch a tool call by name. Enforces approval gate for sensitive tools."""
    if name not in TOOL_REGISTRY:
        return f"[ERROR] Unknown tool: {name}. Available: {list(TOOL_REGISTRY.keys())}"
    td = TOOL_REGISTRY[name]

    # Approval gate — blocks execution until human confirms
    if td.requires_approval:
        if _approval_callback is None:
            return (
                f"[BLOCKED] Tool '{name}' requires human approval but no approval "
                f"callback is configured. Args: {str(arguments)[:200]}"
            )
        approved = _approval_callback(name, arguments)
        if asyncio.iscoroutine(approved):
            approved = await approved
        if not approved:
            return f"[DENIED] Human denied execution of '{name}' with args: {str(arguments)[:200]}"

    try:
        result = td.handler(**arguments)
        if asyncio.iscoroutine(result):
            result = await result
        return str(result)
    except TypeError as exc:
        return f"[ERROR] Tool '{name}' called with wrong arguments: {exc}"
    except Exception as exc:
        return f"[ERROR] Tool '{name}' raised {type(exc).__name__}: {exc}"


# Import all tool modules to trigger registration
def _register_all() -> None:
    from . import files, memory, shell, ssh, web  # noqa: F401


_register_all()
