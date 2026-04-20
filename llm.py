"""Ollama HTTP client (OpenAI-compatible) and model router."""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import (
    DEEP_PATTERNS,
    DEFAULT_MODEL_KEY,
    FAST_PATTERNS,
    LLM_TIMEOUT_S,
    MODELS,
    PRIMARY_ENDPOINT,
    THINK_PATTERNS,
    TUNNEL_ENDPOINT,
    ModelProfile,
)


# ---------------------------------------------------------------------------
# Response types
# ---------------------------------------------------------------------------
@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


# ---------------------------------------------------------------------------
# Ollama client
# ---------------------------------------------------------------------------
class OllamaClient:
    """Async HTTP client for Ollama's OpenAI-compatible endpoint."""

    def __init__(self, endpoint: str = PRIMARY_ENDPOINT, fallback: str = TUNNEL_ENDPOINT):
        self.endpoint = endpoint.rstrip("/")
        self.fallback = fallback.rstrip("/")

    async def chat_completion(
        self,
        messages: list[dict],
        model_profile: ModelProfile,
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> ChatResponse:
        """Call /v1/chat/completions with retries and endpoint fallback."""
        payload: dict[str, Any] = {
            "model": model_profile.name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        # qwen3 needs think:false to suppress reasoning tokens
        if model_profile.inject_think_false:
            payload["think"] = False
            payload["options"] = payload.get("options", {})
            payload["options"]["think"] = False

        last_exc: Exception | None = None
        for attempt in range(4):
            try:
                # Last attempt uses fallback/tunnel endpoint
                endpoint = self.fallback if attempt == 3 else self.endpoint
                return await self._post(endpoint, payload, LLM_TIMEOUT_S)
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_exc = exc
                await asyncio.sleep(min(2 ** attempt, 8))
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                # 503 = server busy — retry with backoff
                if exc.response.status_code == 503:
                    wait = min(2 ** attempt, 8)
                    await asyncio.sleep(wait)
                    continue
                # Other HTTP errors are not retryable
                raise RuntimeError(f"LLM HTTP error {exc.response.status_code}: {exc}") from exc

        raise RuntimeError(f"LLM call failed after 4 attempts: {last_exc}")

    async def _post(self, endpoint: str, payload: dict, timeout: float) -> ChatResponse:
        url = f"{endpoint}/v1/chat/completions"
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = client.post(url, json=payload)
            resp = await resp
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]["message"]
        content = choice.get("content") or None

        # Parse tool calls if present
        raw_tool_calls = choice.get("tool_calls") or []
        tool_calls: list[ToolCall] = []
        for tc in raw_tool_calls:
            fn = tc.get("function", {})
            raw_args = fn.get("arguments", "{}")
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError:
                    args = {"raw": raw_args}
            else:
                args = raw_args
            tool_calls.append(ToolCall(
                id=tc.get("id", f"call_{len(tool_calls)}"),
                name=fn.get("name", ""),
                arguments=args,
            ))

        usage = data.get("usage", {})
        return ChatResponse(
            content=content,
            tool_calls=tool_calls,
            model=data.get("model", ""),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )

    async def ping(self, model_key: str = "gemma3") -> bool:
        """Quick health check — returns True if Ollama responds."""
        profile = MODELS[model_key]
        try:
            resp = await self.chat_completion(
                messages=[{"role": "user", "content": "Hi"}],
                model_profile=profile,
                max_tokens=10,
                temperature=0.0,
            )
            return resp.content is not None or resp.has_tool_calls
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Model router
# ---------------------------------------------------------------------------
class ModelRouter:
    """Selects the best Ollama model for a given task."""

    def __init__(self, override: str | None = None):
        """
        override: a model key from MODELS dict (e.g. "gemma3", "llama70b")
                  or an Ollama model tag (e.g. "qwen3:14b")
        """
        self._override = override

    def select(
        self,
        task_hint: str = "",
        tool_calling_required: bool = True,
        estimated_tokens: int = 0,
    ) -> ModelProfile:
        # Explicit CLI override
        if self._override:
            if self._override in MODELS:
                return MODELS[self._override]
            # Treat as raw model tag — use qwen3 profile but swap the name
            profile = MODELS[DEFAULT_MODEL_KEY]
            from dataclasses import replace
            return replace(profile, name=self._override)

        hint = task_hint.lower()

        # Think step-by-step patterns → deepseek
        if any(p in hint for p in THINK_PATTERNS):
            candidate = MODELS["deepseek"]
        # Heavy reasoning/analysis → llama70b
        elif any(p in hint for p in DEEP_PATTERNS):
            candidate = MODELS["llama70b"]
        # Fast/summarize + no tools needed → gemma3
        elif any(p in hint for p in FAST_PATTERNS) and not tool_calling_required:
            candidate = MODELS["gemma3"]
        # Default / tool-calling → qwen3
        else:
            candidate = MODELS[DEFAULT_MODEL_KEY]

        # Upgrade to large context model if input is huge
        if estimated_tokens > candidate.context_window * 0.8:
            if candidate.context_window < MODELS["llama70b"].context_window:
                candidate = MODELS["llama70b"]

        return candidate
