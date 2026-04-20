"""Context window management and conversation compression (Hermes pattern)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .llm import OllamaClient

from .config import MODELS


class ContextManager:
    """Manages conversation history within model token limits."""

    COMPRESS_THRESHOLD = 0.85   # Compress when estimated usage > 85% of window
    TAIL_FRACTION = 0.30        # Reserve 30% of budget for recent tail
    TAIL_MIN = 6                # Always protect at least 6 tail messages
    SUMMARY_TOOL_TRUNCATE = 200  # Chars to keep per old tool result

    def __init__(self, max_tokens: int, llm_client: "OllamaClient"):
        self.max_tokens = max_tokens
        self.llm = llm_client
        self._compression_count = 0

    def estimate_tokens(self, messages: list[dict]) -> int:
        """Rough token estimate: 1 token ≈ 4 chars."""
        total = 0
        for m in messages:
            content = m.get("content") or ""
            if isinstance(content, list):  # multimodal content
                content = str(content)
            total += len(content)
            # Tool calls add overhead
            if m.get("tool_calls"):
                total += len(str(m["tool_calls"]))
        return total // 4

    async def maybe_compress(self, messages: list[dict]) -> list[dict]:
        """Compress context if estimated tokens exceed threshold."""
        estimated = self.estimate_tokens(messages)
        if estimated <= self.max_tokens * self.COMPRESS_THRESHOLD:
            return messages
        return await self._compress(messages)

    async def _compress(self, messages: list[dict]) -> list[dict]:
        """Compress middle turns of the conversation."""
        if len(messages) <= 4:
            return messages  # Too short to compress

        # Calculate tail protection count
        tail_token_budget = max(
            self.TAIL_MIN * 2,
            int(self.max_tokens * self.TAIL_FRACTION // 100),  # rough msg estimate
        )
        tail_count = max(self.TAIL_MIN, min(10, len(messages) // 3))

        # Protected zones
        head = messages[:3]           # system prompt + first exchange
        tail = messages[-tail_count:]  # recent messages
        middle = messages[3:-tail_count]

        if not middle:
            return messages  # Nothing to compress

        # Pre-pass: truncate old tool results (no LLM call)
        compacted_middle = self._truncate_tool_results(middle)

        # Check if pre-pass was enough
        test_messages = head + compacted_middle + tail
        if self.estimate_tokens(test_messages) <= self.max_tokens * self.COMPRESS_THRESHOLD:
            return test_messages

        # LLM summarization pass — use gemma3 (fast, 0.4s)
        summary = await self._summarize_turns(compacted_middle)
        self._compression_count += 1

        marker = (
            f"[Context compressed #{self._compression_count} — summary of prior conversation]\n"
            + summary
        )
        summary_msg = {"role": "assistant", "content": marker}
        return head + [summary_msg] + tail

    def _truncate_tool_results(self, messages: list[dict]) -> list[dict]:
        """Truncate tool result content to save tokens without LLM call."""
        result = []
        for msg in messages:
            if msg.get("role") == "tool":
                content = str(msg.get("content", ""))
                if len(content) > self.SUMMARY_TOOL_TRUNCATE:
                    msg = dict(msg)
                    msg["content"] = content[:self.SUMMARY_TOOL_TRUNCATE] + "...[truncated]"
            result.append(msg)
        return result

    async def _summarize_turns(self, messages: list[dict]) -> str:
        """Use gemma3 to summarize middle turns."""
        transcript = []
        for m in messages:
            role = m.get("role", "")
            content = str(m.get("content") or "")
            if role == "user":
                transcript.append(f"USER: {content[:500]}")
            elif role == "assistant":
                if m.get("tool_calls"):
                    tc_names = [tc.get("function", {}).get("name", "?")
                                for tc in m.get("tool_calls", [])]
                    transcript.append(f"ASSISTANT: [called tools: {', '.join(tc_names)}]")
                else:
                    transcript.append(f"ASSISTANT: {content[:300]}")
            elif role == "tool":
                transcript.append(f"TOOL RESULT: {content[:200]}")

        prompt = (
            "Summarize this conversation segment concisely using EXACTLY this format:\n\n"
            "Goal: [what the user was trying to accomplish]\n"
            "Progress: [what was completed]\n"
            "Decisions: [key choices made]\n"
            "Files: [files created or modified, if any]\n"
            "Next Steps: [what remains]\n\n"
            "Conversation segment:\n"
            + "\n".join(transcript)
        )

        gemma = MODELS["gemma3"]
        try:
            resp = await self.llm.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model_profile=gemma,
                temperature=0.3,
                max_tokens=512,
            )
            return resp.content or "[summary unavailable]"
        except Exception as exc:
            return f"[Summary failed: {exc}]"
