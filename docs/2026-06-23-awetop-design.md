# awetop Design Spec

## Summary

Profile-aware Claude Code session monitoring tool. Standalone CLI that reads local session files, correlates with aweswitch profiles, and displays live token/context/cost metrics.

## Goals

- Show running Claude Code sessions with token usage, context %, cost, CPU/memory
- Correlate sessions with aweswitch profiles and categories
- Graceful degradation: works without aweswitch/aweshelf (profile/category show `-`)
- Lightweight: ~600 lines, one dependency (Click), no TUI framework

## Non-Goals

- No chat message or tool call parsing (leave to abtop)
- No subagent tracking
- No MCP server detection
- No themes or i18n
- No Codex support (future)

## Usage

```bash
pip install awetop

awetop                    # Live monitor, 2s refresh, Ctrl-C to exit
awetop --json             # One JSON snapshot, exit
awetop --once             # One table print, exit
```

## Output

### Table Mode (default)

```
awetop — 3 sessions (2 active) — 2026-06-23 10:30:00

STATUS   PROFILE      CATEGORY    MODEL           TOKENS(IN/OUT)   CTX%   CPU    MEM    COST    UPTIME
running  cc-glm       research    glm-5.1         45k/12k          34%    12%   256M   $0.42   1h5m
idle     cc-xiaomi    -           mimo-v2.5-pro   120k/35k         78%    2%    180M   $1.20   3h22m
waiting  -            -           claude-opus-4-6  8k/2k            12%    0%    90M    $0.15   5m
```

### Status Values

| Status | Meaning |
|---|---|
| `running` | CPU active or model thinking (last message is user, no assistant reply yet) |
| `waiting` | Last message is assistant with tool_use, no tool_result yet |
| `idle` | Process alive, no recent activity |
| `stopped` | Process exited |

### JSON Mode

```json
{
  "generated_at": "2026-06-23T10:30:00Z",
  "sessions": [
    {
      "session_id": "abc123",
      "profile": "cc-glm",
      "category": "research",
      "model": "glm-5.1",
      "status": "running",
      "pid": 12345,
      "cpu_pct": 12.3,
      "mem_mb": 256,
      "tokens": {
        "input": 45000,
        "output": 12000,
        "cache_read": 8000,
        "cache_create": 3000
      },
      "context_pct": 34,
      "elapsed_secs": 3900,
      "cost_usd": 0.42
    }
  ],
  "aggregate": {
    "total_sessions": 3,
    "active": 2,
    "total_cost_usd": 1.77
  }
}
```

## Data Sources

### Session Discovery

Scan `~/.claude/projects/*/sessions/*.jsonl`. Each JSONL file is one session. The file path encodes project name and session ID.

### Transcript Parsing (Lightweight)

Read JSONL line by line. Extract only:

1. **Token usage** — accumulate `usage.input_tokens`, `usage.output_tokens`, `usage.cache_read_input_tokens`, `usage.cache_creation_input_tokens` from assistant messages
2. **Model name** — from the last assistant message's `model` field
3. **Last message role** — `user` vs `assistant` for status inference

Do NOT parse:
- Chat message text
- Tool call names or arguments
- Tool results
- Subagent references

### Status Inference

```
if process not found:
    status = "stopped"
elif last message role == "user" (no assistant reply yet):
    status = "running"    # model is thinking
elif last message has tool_use blocks (assistant asked to run tools):
    if child process active:
        status = "running"
    else:
        status = "waiting"  # waiting for tool result
else:
    if cpu > 0:
        status = "running"
    else:
        status = "idle"
```

### Process Metrics

Use `ps` on macOS/Linux to get:
- PID (from session file)
- CPU % (`ps -p PID -o %cpu`)
- Memory (`ps -p PID -o rss`)
- Start time (`ps -p PID -o lstart`)
- Process alive check (exit code of `ps -p PID`)

### Profile Matching

Read `~/.config/aweswitch/config.json`. For each session:
1. Get model name from transcript
2. Get base_url from aweswitch profiles
3. Match session's model against profile entries
4. If match found, use profile name

Falls back to `-` if:
- aweswitch not installed
- config.json not found
- No profile matches

### Category Matching

Read `~/.config/aweswitch/sessions.json` (if exists). Map `session_id → category`.

Falls back to `-` if:
- File doesn't exist
- Session ID not in file

### Context Window

Hardcoded map of known models to context window sizes:

```python
CONTEXT_WINDOWS = {
    "claude-opus-4-6": 200_000,
    "claude-opus-4-5": 200_000,
    "claude-sonnet-4-6": 200_000,
    "claude-sonnet-4-5": 200_000,
    "claude-haiku-4-5": 200_000,
    # third-party models via aweswitch
    "glm-5.1": 128_000,
    "mimo-v2.5-pro": 128_000,
    "gemini-3.1-pro-preview": 1_000_000,
}
```

Default to 200,000 if model not in map. Context % = total_tokens / context_window × 100.

## Pricing

### Two-Layer Lookup

1. **Custom pricing** — `~/.config/awetop/custom-pricing.json` (highest priority)
2. **LiteLLM cache** — fetched from GitHub, cached 1 hour

### Custom Pricing Format

```json
{
  "glm-5.1": {
    "input": 2.0,
    "output": 10.0,
    "cache_read": 0.2,
    "cache_create": 2.0
  }
}
```

Values are per million tokens (USD).

### LiteLLM Source

URL: `https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json`

Cache to `~/.config/awetop/pricing-cache.json`. Refresh after 1 hour.

### Cost Calculation

```
cost = (input_tokens × input_price + output_tokens × output_price
      + cache_read_tokens × cache_read_price
      + cache_create_tokens × cache_create_price) / 1_000_000
```

If model not found in either source, cost shows `-`.

## Code Structure

```
src/awetop/
  __init__.py           # Version (0.1.0)
  cli.py                # Click entry point + watch loop
  discovery.py          # Scan ~/.claude/projects, find session files
  transcript.py         # Lightweight JSONL parsing (tokens, model, status)
  process.py            # ps-based CPU/memory/status
  pricing.py            # LiteLLM cache + custom pricing + cost calc
  profile.py            # Read aweswitch config, match profile/category
  render.py             # ANSI table rendering
  snapshot.py           # JSON snapshot dataclass
```

## Dependencies

```
click>=8.1
```

No rich, no ratatui, no TUI framework. Pure ANSI escape codes for colors and table alignment.

## Estimated Code Size

| Module | Lines | Purpose |
|---|---|---|
| cli.py | ~60 | Click commands, watch loop, Ctrl-C handler |
| discovery.py | ~80 | Scan ~/.claude/projects for JSONL files |
| transcript.py | ~120 | Parse JSONL for tokens, model, last role |
| process.py | ~60 | ps commands for CPU/mem/status |
| pricing.py | ~100 | LiteLLM fetch/cache, custom pricing, cost calc |
| profile.py | ~50 | Read aweswitch config, match profiles |
| render.py | ~80 | ANSI table with colors |
| snapshot.py | ~40 | Dataclass for JSON output |
| **Total** | **~590** | |

## Project Structure

```
/Users/peng/Desktop/Project/product/tools/awetop/
  pyproject.toml
  README.md
  src/awetop/
    __init__.py
    cli.py
    discovery.py
    transcript.py
    process.py
    pricing.py
    profile.py
    render.py
    snapshot.py
  tests/
    test_awetop.py
```
