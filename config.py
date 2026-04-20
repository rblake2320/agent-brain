"""Agent Brain configuration — all constants, model profiles, paths."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
AGENT_BRAIN_ROOT = Path(__file__).resolve().parent
DATA_DIR = AGENT_BRAIN_ROOT / "data"
PKA_ROOT = AGENT_BRAIN_ROOT.parent.parent  # C:\Users\techai\PKA testing

MEMORY_DIR = DATA_DIR / "memory"
SESSIONS_DIR = DATA_DIR / "sessions"
LOGS_DIR = DATA_DIR / "logs"
SANDBOX_DIR = DATA_DIR / "sandbox"

# Files the agent may NEVER write to (Data Isolation Rule)
READONLY_PATHS = {
    PKA_ROOT / "CLAUDE.md",
    PKA_ROOT / "MEMORY.md",
    PKA_ROOT / "Owner's Inbox" / "owner.md",
}
READONLY_DIRS: set[Path] = set()  # Agent CAN write to Owner's Inbox (deliverables go there)

# ---------------------------------------------------------------------------
# Ollama endpoints
# ---------------------------------------------------------------------------
SPARK1_ENDPOINT = os.getenv("AGENT_BRAIN_SPARK1", "http://192.168.12.132:11434")
SPARK2_ENDPOINT = os.getenv("AGENT_BRAIN_SPARK2", "http://10.0.0.2:11434")
TUNNEL_ENDPOINT = os.getenv("AGENT_BRAIN_TUNNEL", "http://ollama.ultrarag.app")

# Primary endpoint used by default; falls back to tunnel on timeout
PRIMARY_ENDPOINT = os.getenv("AGENT_BRAIN_PRIMARY", SPARK1_ENDPOINT)

# ---------------------------------------------------------------------------
# Model profiles
# ---------------------------------------------------------------------------
@dataclass
class ModelProfile:
    name: str              # Ollama model tag
    endpoint: str          # Ollama base URL
    context_window: int    # Max tokens
    avg_latency_s: float   # Approximate first-token latency
    capabilities: set[str] = field(default_factory=set)
    inject_think_false: bool = False  # qwen3 needs think:false suppression


MODELS: dict[str, ModelProfile] = {
    "gemma3": ModelProfile(
        name="qwen3:latest",   # qwen3 8B — fast model for compression; gemma3 not on Spark-1
        endpoint=SPARK1_ENDPOINT,
        context_window=32768,
        avg_latency_s=1.0,
        capabilities={"fast", "summarize"},
        inject_think_false=True,
    ),
    "qwen3": ModelProfile(
        name="qwen3-fast-hermes:latest",
        endpoint=SPARK1_ENDPOINT,
        context_window=32768,
        avg_latency_s=2.0,
        capabilities={"tool_calling", "fast"},
        inject_think_false=True,
    ),
    "qwen3-8b": ModelProfile(
        name="qwen3:latest",   # 8B — lighter, faster
        endpoint=SPARK1_ENDPOINT,
        context_window=32768,
        avg_latency_s=1.0,
        capabilities={"tool_calling", "fast"},
        inject_think_false=True,
    ),
    "llama70b": ModelProfile(
        name="llama3.1:70b",
        endpoint=SPARK1_ENDPOINT,
        context_window=131072,
        avg_latency_s=31.9,
        capabilities={"reasoning", "tool_calling"},
    ),
    "deepseek": ModelProfile(
        name="deepseek-r1:32b",
        endpoint=SPARK1_ENDPOINT,
        context_window=32768,
        avg_latency_s=15.0,
        capabilities={"reasoning"},
    ),
}

DEFAULT_MODEL_KEY = "qwen3"

# ---------------------------------------------------------------------------
# Agent loop limits
# ---------------------------------------------------------------------------
MAX_ITERATIONS = 25
SHELL_TIMEOUT_S = 30
SSH_TIMEOUT_S = 30
LLM_TIMEOUT_S = 120
TOOL_OUTPUT_MAX_CHARS = 4000
WEB_FETCH_MAX_CHARS = 8000
MEMORY_CONTEXT_MAX_CHARS = 2000

# ---------------------------------------------------------------------------
# Model routing keyword lists
# ---------------------------------------------------------------------------
FAST_PATTERNS = {"summarize", "classify", "extract", "list", "count", "yes or no", "format"}
DEEP_PATTERNS = {"reason", "analyze", "plan", "debug", "complex", "architect", "compare", "evaluate", "design"}
THINK_PATTERNS = {"think step by step", "chain of thought", "prove", "step by step"}

# ---------------------------------------------------------------------------
# PKA Runtime paths (for worker integration)
# ---------------------------------------------------------------------------
JOBS_ACTIVE = PKA_ROOT / "Team" / "runtime" / "jobs" / "active"

# ---------------------------------------------------------------------------
# SSH
# ---------------------------------------------------------------------------
SPARK1_SSH_HOST = "192.168.12.132"
SPARK1_SSH_USER = "rblake2320"
SPARK2_SSH_HOST = "10.0.0.2"
SPARK2_SSH_USER = "rblake2320"
SSH_KEY_CANDIDATES = [
    Path.home() / ".ssh" / "ai_army_codex",
    Path.home() / ".ssh" / "ai_army",
    Path.home() / ".ssh" / "id_rsa",
]
