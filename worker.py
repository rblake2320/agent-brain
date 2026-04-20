"""PKA runtime job queue integration — polls for queued jobs and executes them."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

from .config import JOBS_ACTIVE, PKA_ROOT
from .config import AGENT_BRAIN_ROOT


# Make sure pka_runtime is reachable
_PKA_SCRIPTS = PKA_ROOT / "scripts"


def _run_runtime(args: list[str]) -> tuple[int, str]:
    """Call pka_runtime.py CLI as a subprocess."""
    result = subprocess.run(
        [sys.executable, str(_PKA_SCRIPTS / "pka_runtime.py")] + args,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode, result.stdout + result.stderr


def _find_queued_jobs() -> list[dict]:
    """Scan active jobs directory for jobs with status 'queued'."""
    jobs_dir = PKA_ROOT / "Team" / "runtime" / "jobs" / "active"
    if not jobs_dir.exists():
        return []
    queued = []
    for f in jobs_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("status") == "queued":
                queued.append(data)
        except Exception:
            pass
    return queued


async def _heartbeat_loop(job_id: str, interval: int = 60) -> None:
    """Send periodic heartbeats while a job is running."""
    while True:
        await asyncio.sleep(interval)
        _run_runtime(["heartbeat", "--job-id", job_id, "--agent", "agent-brain"])


class RuntimeWorker:
    """Polls the PKA job queue and executes jobs via AgentBrain."""

    def __init__(self, poll_interval: float = 10.0):
        self.poll_interval = poll_interval

    async def run(self, print_fn=None) -> None:
        from .agent import AgentBrain
        if print_fn is None:
            print_fn = print

        agent = AgentBrain()
        reachable = await agent.ping()
        if not reachable:
            print_fn("[worker] WARNING: LLM backend not reachable. Jobs will still be attempted.")

        print_fn(f"[worker] Polling for jobs every {self.poll_interval}s...")

        while True:
            jobs = _find_queued_jobs()
            for job in jobs:
                await self._execute_job(agent, job, print_fn)
            await asyncio.sleep(self.poll_interval)

    async def _execute_job(self, agent, job: dict, print_fn) -> None:
        job_id = job.get("id", "unknown")
        task = job.get("task", "") or job.get("title", "")
        if not task:
            print_fn(f"[worker] Job {job_id} has no task/title — skipping")
            return

        print_fn(f"[worker] Claiming job {job_id}: {task[:80]}")
        rc, out = _run_runtime(["claim", "--job-id", job_id, "--agent", "agent-brain"])
        if rc != 0:
            print_fn(f"[worker] Could not claim job {job_id}: {out.strip()}")
            return

        # Start heartbeat in background
        hb_task = asyncio.create_task(_heartbeat_loop(job_id))

        try:
            print_fn(f"[worker] Running task: {task[:80]}")
            result = await agent.run(task, print_fn=print_fn)
            print_fn(f"[worker] Job {job_id} complete. Result: {result[:120]}")
            _run_runtime(["complete", "--job-id", job_id, "--agent", "agent-brain", "--result", result[:500]])
        except Exception as exc:
            print_fn(f"[worker] Job {job_id} failed: {exc}")
            _run_runtime([
                "interrupt", "--job-id", job_id, "--agent", "agent-brain",
                "--kind", "blocker", "--reason", str(exc)[:200],
            ])
        finally:
            hb_task.cancel()
            try:
                await hb_task
            except asyncio.CancelledError:
                pass
