# Review Tracing Protocol

## Purpose

Save full prompt/response pairs for every cross-model reviewer call, enabling:
- **Reviewer-independence audit**: verify the executor only passed file paths, not summaries
- **Reproducibility**: threadId preservation allows conversation continuation
- **Meta-optimize input**: richer data for harness improvement analysis

## When to Trace

After **every** `mcp__codex__codex`, `mcp__codex__codex-reply`, `copilot --agent` (copilot backend), `mcp__manual_review__review`, or `mcp__manual_review__review_reply` call that serves a reviewer/critique function. This includes review scoring, experiment auditing, claim verification, idea critique, and patch gating.

Do NOT trace: purely informational LLM calls (e.g., `codex exec` for code generation that is not a review).

## Trace Directory

```
.aris/traces/<skill-name>/<YYYY-MM-DD>_run<NN>/
  ├── run.meta.json                      # Run-level metadata
  ├── 001-<purpose>.request.json         # Request snapshot
  ├── 001-<purpose>.response.md          # Full response text
  ├── 001-<purpose>.meta.json            # Response metadata
  ├── 002-<purpose>.request.json         # Second call (e.g., reply)
  └── ...
```

- `<skill-name>`: the ARIS skill that triggered this call (e.g., `auto-review-loop`)
- `<YYYY-MM-DD>_run<NN>`: date + sequential run number (start from `01`)
- `<purpose>`: short kebab-case label (e.g., `round-1-review`, `critique`, `ideation`, `audit`, `patch-gate`)

## How to Trace

After each reviewer MCP call — including every FAILED attempt in a capability-fallback chain (one trace entry per attempt: `--status error` + `--fallback-reason`; the successful entry records the RESOLVED pair) — save the trace using `save_trace.sh`,
resolved through the canonical helper chain (see
`integration-contract.md` §2 — failure policy C, "forensic helper").
The full invocation:

```bash
# Resolve $TRACE_HELPER (canonical strict-safe chain; see integration-contract.md §2).
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)" || exit 1
if [ -z "${ARIS_REPO:-}" ] && [ -f .aris/installed-skills.txt ]; then
    ARIS_REPO=$(awk -F'\t' '$1=="repo_root"{print $2; exit}' .aris/installed-skills.txt 2>/dev/null) || true
fi
TRACE_HELPER=".aris/tools/save_trace.sh"
[ -f "$TRACE_HELPER" ] || TRACE_HELPER="tools/save_trace.sh"
[ -f "$TRACE_HELPER" ] || { [ -n "${ARIS_REPO:-}" ] && TRACE_HELPER="$ARIS_REPO/tools/save_trace.sh"; }
[ -f "$TRACE_HELPER" ] || TRACE_HELPER=""

if [ -n "$TRACE_HELPER" ]; then
  bash "$TRACE_HELPER" \
    --skill "<skill-name>" \
    --purpose "<purpose>" \
    --model "<model that actually ran — the RESOLVED pair, not the target>" \
    --effort "<effort that actually ran>" \
    --fallback-reason "<why the capability chain stepped down; empty when it didn't>" \
    --status "<ok | fallback_used | error>" \
    --thread-id "<threadId from response>" \
    --backend "<codex | copilot | manual | oracle-pro | agy>" \
    --tool "<mcp__codex__codex | copilot --agent | mcp__manual_review__review | ...>" \
    --executor "<claude-code | copilot | codex>" \
    --executor-model "<from --executor-model; unavailable if not set>" \
    --executor-family "<openai | anthropic | google | unknown>" \
    --reviewer-profile "<profile name for copilot backend; empty for others>" \
    --reviewer-family "<openai | anthropic | google | unknown>" \
    --requested-reviewer-model "<model originally requested>" \
    --reported-reviewer-model "<model the backend reports it used>" \
    --memory-hash "<sha256 of memory artifact if available; empty otherwise>" \
    --independence-verified "<true | false>" \
    --prompt "<full prompt as sent>" \
    --response "<full response content>"
else
  # Required fallback: the resolver exhausted all three layers and
  # save_trace.sh is unreachable, but trace artifacts are still
  # required (unless `--- trace: off` was explicitly set on this
  # SKILL invocation). Write the four files below directly per the
  # schemas in "File Schemas", into:
  #   .aris/traces/<skill-name>/<YYYY-MM-DD>_run<NN>/
  #     run.meta.json
  #     <NNN>-<purpose>.request.json
  #     <NNN>-<purpose>.response.md
  #     <NNN>-<purpose>.meta.json
  # Do NOT silently skip — trace_path is load-bearing for any
  # mandatory audit emitting `trace_path` in its artifact (see
  # assurance-contract.md §"Required Audit Artifact Schema").
  echo "WARN: save_trace.sh not resolved; writing trace files directly per review-tracing.md schema." >&2
fi
```

The helper, when present, handles directory creation, run numbering,
and file writing. The fallback branch above documents what to do
when the helper is unreachable — the trace is forensic evidence, so
"helper missing" never means "skip the trace."

## File Schemas

### `run.meta.json`
```json
{
  "skill": "auto-review-loop",
  "run_id": "2026-04-15_run01",
  "started_at": "2026-04-15T14:30:00+08:00",
  "executor": "claude-code",
  "executor_model": "claude-sonnet-4-5",
  "executor_family": "anthropic",
  "reviewer_family": "openai",
  "reviewer_backend": "codex",
  "project_dir": "/path/to/project"
}
```

- `executor`: the name of the running executor (from `--executor` parameter; defaults to `"claude-code"`). Dynamic — set by the caller, not hardcoded.
- `executor_model`: the model running this ARIS invocation (from `--executor-model` parameter when available; otherwise `"unavailable"`).
- `executor_family`: derived from `executor_model` (`openai` / `anthropic` / `google` / `unknown`).
- `reviewer_family`: the reviewer model's family, determined at spawn time from the reviewer backend's active model.
- `reviewer_backend`: `codex` / `copilot` / `manual` / `oracle-pro` / `agy` — the backend used for review calls.

### `NNN-<purpose>.request.json`
```json
{
  "call_number": 1,
  "purpose": "round-1-review",
  "timestamp": "2026-04-15T14:31:00+08:00",
  "tool": "mcp__codex__codex",
  "backend": "codex",
  "model": "gpt-5.6-sol",
  "config": {"model_reasoning_effort": "xhigh"},
  "reviewer_profile": null,
  "files_referenced": ["paper/sections/3_method.tex", "results/table1.csv"],
  "prompt": "<full prompt text>"
}
```

For copilot backend (`--reviewer: copilot`):
```json
{
  "call_number": 1,
  "purpose": "round-1-review",
  "timestamp": "2026-04-15T14:31:00+08:00",
  "tool": "copilot --agent",
  "backend": "copilot",
  "model": "gpt-5.4",
  "effort_unpinned": true,
  "config": {},
  "reviewer_profile": "aris-reviewer-openai",
  "requested_reviewer_model": "gpt-5.4",
  "reported_reviewer_model": null,
  "executor_model": "claude-sonnet-4-5",
  "executor_family": "anthropic",
  "reviewer_family": "openai",
  "independence_verified": true,
  "files_referenced": ["paper/sections/3_method.tex", "results/table1.csv"],
  "prompt": "<full prompt text>"
}
```

Fields:
- `tool`: the tool name used (`mcp__codex__codex`, `copilot --agent`, `mcp__manual_review__review`, etc.).
- `backend`: the logical backend (`codex`, `copilot`, `manual`, `oracle-pro`, `agy`).
- `effort_unpinned`: `true` when the backend cannot pin reasoning effort (copilot profiles have no effort control); `false` otherwise.
- `reviewer_profile`: for copilot, the custom agent profile name (e.g., `aris-reviewer-openai`); `null` for other backends.
- `requested_reviewer_model`: the model pinned in the selected profile frontmatter (parsed from `.github/agents/<profile>.agent.md`); `null` when unavailable.
- `reported_reviewer_model`: the model the tool reports actually using; `null` when the tool does not surface this information.
- `executor_model`: from `--executor-model` parameter; `"unavailable"` if not provided.
- `executor_family`: derived from `executor_model`.
- `reviewer_family`: the reviewer's model family (`openai` / `anthropic` / `google` / `unknown`).
- `independence_verified`: derived from actual executor and reviewer model families — `true` when `executor_family != reviewer_family` and both are known; `false` otherwise; `"unverified"` when families are not both available to derive.

### `NNN-<purpose>.response.md`
The reviewer's full response, verbatim. No truncation, no summarization.

### `NNN-<purpose>.meta.json`
```json
{
  "call_number": 1,
  "purpose": "round-1-review",
  "timestamp": "2026-04-15T14:33:00+08:00",
  "thread_id": "019d8fe0-b25d-...",
  "model": "gpt-5.6-sol",
  "model_family": "openai",
  "executor_family": "anthropic",
  "independence_verified": true,
  "reviewer_profile": null,
  "duration_ms": 142000,
  "status": "ok"
}
```

For copilot backend:
```json
{
  "call_number": 1,
  "purpose": "round-1-review",
  "timestamp": "2026-04-15T14:33:00+08:00",
  "thread_id": null,
  "model": "gpt-5.4",
  "model_family": "openai",
  "effort_unpinned": true,
  "executor_family": "anthropic",
  "requested_reviewer_model": "gpt-5.4",
  "reported_reviewer_model": null,
  "independence_verified": true,
  "reviewer_profile": "aris-reviewer-openai",
  "duration_ms": 142000,
  "status": "ok"
}
```

Fields new per this fix:
- `model_family`: `openai` / `anthropic` / `google` / `unknown` — derived from the model that actually ran.
- `effort_unpinned`: `true` when the backend cannot pin reasoning effort (copilot backend); `false` otherwise.
- `executor_family`: from `--executor-model` derivation (copilot) or executor introspection (other backends); `"unavailable"` if not known.
- `requested_reviewer_model`: the model pinned in the selected profile frontmatter; `null` when not available.
- `reported_reviewer_model`: the model the tool reports actually using; `null` when the tool does not surface this.
- `independence_verified`: derived from actual executor and reviewer families — `true` only when they differ and both are known; `false` if same-family; `"unverified"` if families cannot be resolved.
- `reviewer_profile`: for copilot backend only, the custom agent profile name; `null` for other backends.
- `memory_hash`: SHA-256 of `REVIEWER_MEMORY.md` at trace time; `null` when no memory file exists.

## Configuration

Tracing respects three modes, set via inline parameter `--- trace: off | meta | full`:
- **`full`** (default): save full prompt + full response
- **`meta`**: save metadata only (no prompt/response text), useful for sensitive projects
- **`off`**: disable tracing entirely

## Integration with events.jsonl

After writing a trace, append a compact summary event to `.aris/meta/events.jsonl`:

```json
{"event":"review_trace","skill":"auto-review-loop","purpose":"round-1-review","thread_id":"...","trace_path":".aris/traces/auto-review-loop/2026-04-15_run01/","backend":"copilot","tool":"copilot --agent","executor_family":"anthropic","reviewer_family":"openai","independence_verified":true,"status":"ok"}
```

This allows `/meta-optimize` to discover traces without reading the full trace files.

## Debugging With Traces

Traces are not only audit evidence — they are the **first place to look when a
verdict is surprising**: a score regresses round-to-round, two reviewer backends
disagree, or `/result-to-claim` contradicts an earlier claim. Before re-invoking
the reviewer for "a better answer", read the raw transcript and find the moment
its judgment actually changed:

```bash
# Diff the raw response bodies across the two calls in question
skill=auto-review-loop run=2026-04-15_run01
diff ".aris/traces/$skill/$run/002-round-2.response.md" \
     ".aris/traces/$skill/$run/003-round-3.response.md"

# Grep for the sentence where the assessment turned
grep -En 'however|but|concern|missing|cannot' \
     ".aris/traces/$skill/$run/003-round-3.response.md"
```

The paragraph where the assessment changed **is** the causal explanation for the
divergence — cite it, don't guess. Re-running the reviewer without reading the
trace is tuning by vibe: you get a new opinion, not an explanation.

This is the same muscle ARIS already applies to code failures (the "**Read the
error** — parse traceback, stderr, and log files" step in `/experiment-bridge`'s
auto-debug sequence, and `/codex:rescue` reading tracebacks before a retry) —
applied to saved AI-judgment transcripts instead of stderr. The trace is written
in English and most of it is the reviewer talking to itself; the discipline is
identical: read the primary artifact first, then act on the exact divergence
point rather than re-rolling the dice.

Practical triggers:

| Surprise | Trace move |
|---|---|
| Score dropped after a "fix" round | diff the two rounds' `.response.md`; find which criterion flipped |
| Two backends disagree (codex vs gemini/manual) | grep both responses for the SAME artifact path; compare what each actually read |
| Reviewer "forgot" an earlier concern | grep prior rounds for the concern keyword; if present-then-absent, cite it in the next prompt instead of restating from memory |
| Verdict contradicts a deterministic checker | read the request `.md` — was the checker's output actually in the files the reviewer was pointed at? |

## Privacy

- `.aris/traces/` should be in `.gitignore` — traces are project-local, never committed
- Traces may contain sensitive research content; treat them as confidential
- Use `--- trace: off` for projects with strict confidentiality requirements
