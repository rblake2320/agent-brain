# Agent Brain

Autonomous LLM runtime for the PKA workspace. Powered by Ollama models on Spark-1/Spark-2.

## What It Does

- **ReAct loop**: think → tool call → observe → repeat (max 25 iterations)
- **Internet access**: DuckDuckGo search + web fetch
- **8 built-in tools**: web_search, web_fetch, file_read, file_write, memory_read, memory_write, shell_exec, ssh_exec
- **Model routing**: gemma3 (fast) → qwen3 (tool-calling) → llama3.1:70b (deep reasoning)
- **Persistent memory**: MEMORY.md survives across sessions
- **Context compression**: Hermes-pattern summarizer kicks in at 85% context window
- **PKA integration**: consumes job queue via `pka_runtime.py`

## Quick Start

```bash
# One-shot task
python -m scripts.agent_brain run "Search for the latest RTX 5090 benchmarks"

# Interactive chat
python -m scripts.agent_brain chat

# Job queue consumer (picks up queued PKA jobs)
python -m scripts.agent_brain worker

# Status check
python -m scripts.agent_brain status
```

## Models

| Key | Model | Latency | Use |
|-----|-------|---------|-----|
| gemma3 | gemma3:latest | 0.4s | Summarization, classification |
| qwen3 | qwen3-fast-hermes:latest | 2s | Tool-calling (default) |
| llama70b | llama3.1:70b | 31.9s | Deep reasoning/analysis |
| deepseek | deepseek-r1:32b | 15s | Step-by-step reasoning |

Override: `--model gemma3` (or any Ollama tag)

## Tools

| Tool | Description |
|------|-------------|
| `web_search` | DuckDuckGo search (no API key) |
| `web_fetch` | Fetch and strip a web page |
| `file_read` | Read any file inside PKA workspace |
| `file_write` | Write files (scope-enforced, secret-scanned) |
| `memory_read` | Read persistent memory sections |
| `memory_write` | Update persistent memory |
| `shell_exec` | Run shell commands (sandboxed, blocklisted) |
| `ssh_exec` | SSH to Spark-1 or Spark-2 |

## Safety

- Writes blocked outside `C:\Users\techai\PKA testing\`
- CLAUDE.md, owner.md, MEMORY.md, Owner's Inbox → read-only
- Shell blocklist: rm -rf, format, shutdown, etc.
- Secret detection via pka_guardrails.py before every write
- 25 iteration cap per task
- All tool calls logged to `data/logs/agent_YYYYMMDD.jsonl`

## Endpoints

Primary: Spark-1 `http://192.168.12.132:11434`
Fallback: Tunnel `http://ollama.ultrarag.app`

Override: `AGENT_BRAIN_SPARK1=http://...`

## Structure

```
scripts/agent_brain/
├── __main__.py   CLI
├── agent.py      ReAct loop
├── llm.py        Ollama client + model router
├── context.py    Context compression
├── memory.py     Persistent memory engine
├── worker.py     PKA job queue consumer
├── config.py     All configuration
└── tools/        8 tool implementations
    └── data/     Runtime state (gitignored)
```
