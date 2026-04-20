"""CLI entry point: python -m agent_brain <command>"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def _print_header() -> None:
    print("=" * 60)
    print("  Agent Brain v0.1.0  |  PKA Workspace Autonomous Runtime")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
async def cmd_run(args: argparse.Namespace) -> int:
    """One-shot task execution."""
    from .agent import AgentBrain

    def printer(msg: str) -> None:
        if args.verbose:
            print(msg)

    agent = AgentBrain(
        model_override=args.model or None,
        session_id=args.session or None,
    )

    if not args.quiet:
        print(f"[agent-brain] Running task: {args.task[:80]}")
        print(f"[agent-brain] Session: {agent.session_id}")
        print()

    result = await agent.run(args.task, print_fn=printer)
    print(result)
    return 0


async def cmd_chat(args: argparse.Namespace) -> int:
    """Interactive multi-turn chat REPL."""
    from .agent import AgentBrain

    _print_header()

    try:
        from rich.console import Console
        from rich.markdown import Markdown
        console = Console()
        def _print_result(text: str) -> None:
            console.print(Markdown(text))
    except ImportError:
        console = None
        def _print_result(text: str) -> None:
            print(text)

    agent = AgentBrain(
        model_override=args.model or None,
        session_id=args.session or None,
    )

    # Check connectivity
    print("Checking LLM connection...", end=" ", flush=True)
    ok = await agent.ping()
    print("OK" if ok else "OFFLINE (will retry on first message)")
    print(f"Session: {agent.session_id}")
    print("Type 'exit' or Ctrl-C to quit. Type '/help' for commands.\n")

    def verbose_printer(msg: str) -> None:
        if args.verbose:
            print(f"  {msg}", flush=True)

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit", "/exit", "/quit"):
            print("Bye.")
            break

        if user_input == "/help":
            print("Commands: /exit  /session  /memory  /clear  /status")
            continue

        if user_input == "/session":
            print(f"Session ID: {agent.session_id}")
            print(f"History: {len(agent._history)} messages")
            continue

        if user_input == "/memory":
            print(agent.memory.read())
            continue

        if user_input == "/clear":
            agent._history = []
            print("Conversation cleared.")
            continue

        if user_input == "/status":
            ok = await agent.ping()
            print(f"LLM: {'OK' if ok else 'OFFLINE'}")
            print(f"Session: {agent.session_id}")
            print(f"History: {len(agent._history)} messages")
            continue

        print()
        result = await agent.chat(user_input, print_fn=verbose_printer)
        print("\nAgent:", end=" ")
        _print_result(result)
        print()

    return 0


async def cmd_worker(args: argparse.Namespace) -> int:
    """Job queue worker — polls PKA runtime for queued jobs."""
    from .worker import RuntimeWorker

    _print_header()
    print("[worker] Starting job queue consumer...")
    print("[worker] Press Ctrl-C to stop.\n")

    worker = RuntimeWorker(poll_interval=args.interval)
    try:
        await worker.run(print_fn=print)
    except KeyboardInterrupt:
        print("\n[worker] Stopped.")
    return 0


async def cmd_status(args: argparse.Namespace) -> int:
    """Show agent brain status: memory, sessions, model health."""
    from .agent import AgentBrain
    from .config import DATA_DIR, LOGS_DIR, MEMORY_DIR, MODELS, SESSIONS_DIR
    from .memory import MemoryStore

    _print_header()

    # LLM ping
    agent = AgentBrain()
    print("Checking LLM backend...", end=" ", flush=True)
    ok = await agent.ping()
    print("OK" if ok else "OFFLINE")

    # Memory
    store = MemoryStore()
    sections = store.list_sections()
    print(f"\nMemory sections ({len(sections)}): {', '.join(sections) or 'none'}")

    # Sessions
    sessions = agent.sessions.list_sessions()
    print(f"Saved sessions: {len(sessions)}")

    # Logs
    log_files = list(LOGS_DIR.glob("agent_*.jsonl"))
    print(f"Audit logs: {len(log_files)} files")

    # Models
    print(f"\nConfigured models:")
    for key, profile in MODELS.items():
        print(f"  {key:12s} {profile.name:40s} {profile.avg_latency_s}s latency")

    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        prog="agent_brain",
        description="Agent Brain — Autonomous LLM runtime for PKA workspace",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # run
    p_run = sub.add_parser("run", help="Execute a one-shot task")
    p_run.add_argument("task", help="Task description or question")
    p_run.add_argument("--model", help="Override model key (gemma3/qwen3/llama70b/deepseek)")
    p_run.add_argument("--session", help="Session ID to use (creates new if omitted)")
    p_run.add_argument("--verbose", "-v", action="store_true", help="Show tool call details")
    p_run.add_argument("--quiet", "-q", action="store_true", help="Suppress header output")

    # chat
    p_chat = sub.add_parser("chat", help="Interactive multi-turn chat")
    p_chat.add_argument("--model", help="Override model key")
    p_chat.add_argument("--session", help="Resume a previous session ID")
    p_chat.add_argument("--verbose", "-v", action="store_true", help="Show tool call details")

    # worker
    p_worker = sub.add_parser("worker", help="PKA job queue consumer")
    p_worker.add_argument("--interval", type=float, default=10.0, help="Poll interval in seconds")

    # status
    sub.add_parser("status", help="Show agent brain status and health")

    args = parser.parse_args()

    dispatch = {
        "run": cmd_run,
        "chat": cmd_chat,
        "worker": cmd_worker,
        "status": cmd_status,
    }

    fn = dispatch[args.command]
    try:
        return asyncio.run(fn(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
