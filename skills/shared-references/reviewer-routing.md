# Reviewer Routing

## Default Routing

The default reviewer backend depends on the skill AND the execution environment:

| Skill | Default backend | Opt-in override |
|-------|----------------|-----------------|
| `/auto-review-loop` | **`codex`** (default) | `--reviewer: copilot` (explicit opt-in), `--reviewer: codex` |
| All other reviewer skills | **Codex MCP** (`mcp__codex__codex`), model **`gpt-5.6-sol`** | `--reviewer: oracle-pro` / `agy` / `manual` |

**Copilot CLI for `/auto-review-loop` is explicit opt-in only.** The `COPILOT_CLI` environment variable does not exist persistently (it is an open proposal at github/copilot-cli#2107, not a shipped feature). Until a reliable auto-detection signal ships, `--reviewer: copilot` must be passed explicitly. The default reviewer for `/auto-review-loop` is `codex` (preserving backward compatibility — no breaking change for existing Claude Code users).

**Scope:** this is a drive-only partial implementation related to [#258](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep/issues/258), not the issue's requested automatic/default or end-to-end MCP-free acceptance path. Copilot can drive iterative review rounds, but a positive Copilot verdict must be finalized by Codex/manual; if that backend is unavailable, the run ends `REVIEW_UNAVAILABLE`.

See the [Copilot section](#copilot-cli-custom-agent-profiles---reviewer-copilot--explicit-opt-in-for-auto-review-loop) for the auto-review-loop override and the [Codex section](#codex-capability-fallback-new-reviewer-sessions-only) for the Codex fallback chain.

### Codex MCP Tiered Reasoning-Effort Policy

When Codex MCP is the active backend (default for all non-auto-review-loop skills, or explicit `--reviewer: codex`), model **`gpt-5.6-sol`** (GPT-5.6-Sol) is used with a **two-tier reasoning-effort policy** (since 2026-07-10; `ultra`/`max` need codex-cli ≥ 0.144.1):

| Tier | `model_reasoning_effort` | Which calls |
|------|--------------------------|-------------|
| **Deep-audit** | `ultra` | `/proof-checker` · `/kill-argument` (attack / defense / adjudication threads; beast-mode extra axis probes stay `xhigh`) · `/research-review` · `/experiment-audit` · `/paper-claim-audit` · `/result-to-claim` · `/meta-apply` |
| **Regular** | `xhigh` | every other reviewer call — including ALL rounds of `/auto-review-loop` and other multi-round loops (a `codex-reply` cannot change model/effort mid-thread), and per-item fan-outs like `/citation-audit` (per-entry fresh calls would multiply `ultra`'s delegation cost for no verdict gain) |

**Always pin BOTH `model` and `config.model_reasoning_effort` explicitly in the first call of every thread.** Do not rely on the user's `~/.codex/config.toml`: the catalog default effort for gpt-5.6-sol is `low`, far below the review floor.

`ultra` = deepest reasoning + automatic task delegation — right for one-shot verdict-bearing audits, wrong for per-item loops (slower, pricier). Effort enums accepted by codex-cli ≥ 0.144.1: `none / minimal / low / medium / high / xhigh / max / ultra`.

> **Do not confuse the two "max"es.** ARIS's `— effort: lite|balanced|max|beast` ([effort-contract.md](effort-contract.md)) sets how much WORK the pipeline does; Codex's `model_reasoning_effort: …|max|ultra` sets how hard the REVIEWER thinks. `— effort: max` does NOT imply `model_reasoning_effort: max`.

### Codex capability fallback (new reviewer sessions only)

Resolve the reviewer pair on the **first new Codex session of each tier** in a run, then reuse that resolved pair for later sessions of the same tier. Try the declared pair first (`gpt-5.6-sol` + `ultra` for deep-audit; `gpt-5.6-sol` + `xhigh` for regular). Then:

- Only if the call fails **before returning a usable thread** AND the error **explicitly identifies the requested effort as unsupported** (older codex-cli): retry `gpt-5.6-sol` + `xhigh`. (This step exists only for the deep tier's `ultra` — a regular-tier `xhigh` call skips it; `xhigh` predates 0.144.1.)
- Only if the error **explicitly identifies `gpt-5.6-sol` as unknown or unavailable** to this account/plan: retry `gpt-5.5` + `xhigh` (skip redundant intermediate steps).
- **NEVER downgrade on** timeout, rate-limit/capacity, authentication, transport/protocol, server, sandbox/tool, context-length, malformed-request, or response-parse errors — a blind downgrade retry there risks double-running (and double-billing) a review that may have gone through.
- **Never run a verdict-bearing review below `xhigh`.** `gpt-5.4` is available only as an explicit user override for legacy/repro runs — it is NOT part of the automatic chain.
- Replies (`codex-reply`) inherit the successful session's model and effort — pass only the saved `threadId` plus the message.
- Trace every attempt, the resolved pair, and the fallback reason (see `review-tracing.md`); the trace records the pair that actually ran, not the target pair.
- If no allowed pair succeeds, emit `REVIEW_UNAVAILABLE` (or, for a mandatory audit gate, `ERROR`) — never a substantive verdict.
- This automatic chain applies only when no explicit reviewer-model override was supplied.

### After upgrading codex-cli

MCP servers are spawned per session: after upgrading codex-cli (e.g. to 0.144.1 for `ultra`/`max`), **restart the Claude Code session** so `codex mcp-server` runs the new binary — an old server process rejects the new effort enums even though the CLI on disk is new.

## Optional: GPT-5.5 Pro via Oracle

When the user explicitly passes `— reviewer: oracle-pro`, route the review through Oracle MCP instead of Codex MCP.

### Routing Logic (add to any reviewer-invoking skill)

```
Parse $ARGUMENTS for `— reviewer:` directive.

If not specified OR `— reviewer: codex`:
    → Use mcp__codex__codex with model: gpt-5.6-sol at the tier's effort
      (deep-audit: ultra / regular: xhigh — see the Default table above).
    → This is the DEFAULT. No change from current behavior.

If `— reviewer: oracle-pro`:
    → Check if mcp__oracle__consult tool is available
    → If available:
        Use mcp__oracle__consult with:
          model: "gpt-5.5-pro"
          prompt: [same prompt you would send to Codex]
          files: [file paths for reviewer to read directly]
        Note: Oracle may use API mode (fast, needs OPENAI_API_KEY)
              or browser mode (slow ~1-2 min, needs Chrome + ChatGPT login)
    → If NOT available:
        Print: "⚠️ Oracle MCP not installed. Falling back to Codex at this call's declared tier."
        Use mcp__codex__codex as normal.
```

### Invariants

- `— reviewer: oracle-pro` ONLY takes effect when explicitly passed
- Reviewer independence protocol still applies (pass file paths, not summaries)
- `effort` and `difficulty` are orthogonal — they don't change reviewer backend
- `beast` mode may RECOMMEND oracle-pro but never requires it
- Browser mode: acceptable for one-shot reviews; NOT recommended inside multi-round loops (too slow/brittle)

### Oracle MCP Call Format

```
mcp__oracle__consult:
  prompt: |
    [role + task + output schema]
    Read all listed files directly.
  model: "gpt-5.5-pro"
  files:
    - /absolute/path/to/file1
    - /absolute/path/to/file2
```

### Skills That Support `— reviewer: oracle-pro`

| Skill | Use case for Pro |
|-------|-----------------|
| `/research-review` | Deeper critique on paper drafts |
| `/auto-review-loop` | Final stress test (last round only in browser mode) |
| `/experiment-audit` | Line-by-line eval code audit |
| `/proof-checker` | Deep mathematical reasoning |
| `/rebuttal` | Stress test before submission |
| `/idea-creator` | Idea evaluation depth |
| `/research-lit` | Literature analysis depth |

### Installation

```bash
# Install Oracle CLI + MCP
npm install -g @steipete/oracle

# Add Oracle MCP to Claude Code
claude mcp add oracle -s user -- oracle-mcp

# Restart Claude Code session to load

# API mode (fast, recommended):
export OPENAI_API_KEY="your-key"

# Browser mode (no API key, slower):
# Just log in to ChatGPT in Chrome
```

### NOT installed = ZERO impact

If Oracle is not installed, `— reviewer: oracle-pro` gracefully falls back to Codex. No error, no breakage, just a warning.

### Upstream development & known issues

Oracle MCP is maintained at [`steipete/oracle`](https://github.com/steipete/oracle). When you invoke `— reviewer: oracle-pro` (and especially the `o3-deep-research` / `gpt-5.5-pro` paths), it's worth checking the **[open PRs](https://github.com/steipete/oracle/pulls)** for in-flight fixes that may affect your run — e.g., model routing changes, browser-mode auth fixes, rate-limit handling, or new model alias support. ARIS does not vendor Oracle MCP; you're running the published version from `npm install -g @steipete/oracle`. If a behavior surprises you, the upstream PR queue is the first place to check before opening an issue here.

## Optional: Gemini via Antigravity CLI (`— reviewer: agy`)

When the user explicitly passes `— reviewer: agy`, route the review through the **gemini-review MCP** with the Antigravity (`agy`) backend — a native cross-model reviewer for Antigravity users who don't run Codex MCP / Oracle. Added in [#267](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep/pull/267).

### Routing Logic (add to any reviewer-invoking skill)

```
Parse $ARGUMENTS for `— reviewer:` directive.

If `— reviewer: agy`:
    → Check if the gemini-review MCP tool is available (mcp__gemini_review__review).
    → If available (server configured with GEMINI_REVIEW_BACKEND=agy):
        Use mcp__gemini_review__review with:
          prompt: [same prompt you would send to Codex]
        For round 2+: mcp__gemini_review__review_reply with the saved threadId.
        For long paper/project reviews (avoid the ~120s MCP tool timeout):
          mcp__gemini_review__review_start + mcp__gemini_review__review_status (async).
    → If NOT available:
        Print: "⚠️ gemini-review (agy) MCP not configured. Falling back to Codex at this call's declared tier."
        Use mcp__codex__codex as normal.
```

### Invariants

- `— reviewer: agy` ONLY takes effect when explicitly passed.
- **Cross-model family holds by construction.** The `agy` backend is fail-closed on ARIS's invariant: it recovers the *actual* Gemini-family model id from the current invocation's Antigravity transcript, **refuses** to return a verdict if the routed model is non-Gemini (no `"agy-cli"` placeholder), and binds the recovered transcript to *this* call via a **user-event nonce** (a model echo can't spoof the binding). So when the executor is Claude, `— reviewer: agy` (Gemini) satisfies the cross-model gate.
- Reviewer independence still applies — pass prompt context only (the `tools` arg is accepted for compatibility but ignored).
- `effort` and `difficulty` are orthogonal — they don't change the reviewer backend.

### Install

```bash
# Install + authenticate the Antigravity CLI (`agy`), then add the MCP with the agy backend:
claude mcp add gemini-review --env GEMINI_REVIEW_BACKEND=agy -- python3 <path>/mcp-servers/gemini-review/server.py
# (codex mcp add gemini-review ... for Codex CLI). Without the env var the server defaults to the direct Gemini API.
```

### NOT installed = ZERO impact

If the gemini-review (agy) MCP isn't configured, `— reviewer: agy` gracefully falls back to Codex at the call's declared tier (deep-audit: ultra / regular: xhigh). No error, no breakage, just a warning.

## Optional: Manual Review (any model, zero API cost)

When the user explicitly passes `— reviewer: manual`, route the review through the manual-review MCP server. Instead of calling an API, it opens a browser page (or writes a file on headless Linux) where the user copies the prompt to any model and pastes the response back.

**Zero API cost. Works with any text-capable model.**

### Routing Logic

```
Parse $ARGUMENTS for `— reviewer:` directive.

If `— reviewer: manual`:
    → Check if mcp__manual_review__review tool is available
    → If available:
        Use mcp__manual_review__review with:
          prompt: [same review prompt you would send to Codex; the manual
                   transport wrapper also requires the response's first line
                   to be `Reviewer-Model: <exact-model-id>`]
          config: {"model_reasoning_effort": "xhigh", "executor_model": "<actual executor model>", "require_reviewer_model": true}
        For round 2+ in multi-round skills:
          Use mcp__manual_review__review_reply with:
            threadId: [saved from prior call]
            prompt: [follow-up prompt]
            config: {"model_reasoning_effort": "xhigh", "executor_model": "<actual executor model>", "require_reviewer_model": true}
    → If NOT available:
        Print: "⚠️ Manual Review MCP not installed. Install with: claude mcp add manual-review -s user -- python3 /path/to/mcp-servers/manual-review/server.py"
        STOP. Do NOT fall back to Codex (the target user likely has no Codex subscription).
```

### Invariants

- `— reviewer: manual` ONLY takes effect when explicitly passed
- **Cross-model family is mandatory, not optional.** "any model" above means any *non-executor-family* model, determined dynamically from the actual executor model — not merely "non-Claude." Every verdict-bearing response must start with `Reviewer-Model: <exact-model-id>`; derive its family and compare it with the model-derived executor family. Missing, unknown, ambiguous, or same-family identity is `REVIEW_UNAVAILABLE` for an acceptance gate. The UI warning is advisory; the traced model identities and derivation are the gate.
- Prompt fidelity: the review task text is exactly what Codex would receive; the manual transport wrapper may add only the model-identity response-format line used by the provenance gate
- `config.model_reasoning_effort` is shown as a recommendation badge, not embedded in the prompt
- Thread continuity: `review_reply` shows previous exchanges so the user can maintain context in their chosen model
- Reviewer independence protocol still applies

### Thread continuity

For round 2+ in multi-round skills (`/auto-review-loop`, `/proof-checker` Phase 3):
- Use `mcp__manual_review__review_reply` with the saved `threadId`
- The browser page displays previous prompt/response exchanges
- The user should continue the conversation in the same model session for best results

### Installation

```bash
claude mcp add manual-review -s user -- python3 /path/to/mcp-servers/manual-review/server.py
```

### Modes

- **Browser mode** (default): opens a local web page on Windows/macOS/Linux desktop
- **File mode** (`MANUAL_REVIEW_MODE=file`): writes prompt to a per-thread subdirectory. Read `.aris/pending_review/pending_review.json` for the `prompt_file` and `response_file` paths — for headless/SSH environments

### Skills That Support `— reviewer: manual`

The following skills are wired for manual review (Claude Code only):

| Skill | Manual support |
|-------|----------------|
| `/research-review` | Yes |
| `/auto-review-loop` | Yes |
| `/experiment-audit` | Yes |
| `/proof-checker` | Yes |
| `/rebuttal` | Yes |
| `/idea-creator` | Yes |

> `/research-lit` supports `oracle-pro` only; manual review is not wired because the skill has no reviewer call blocks.

> **Platform note**: Manual review requires MCP tools (available only in Claude Code). Mirrored skill packs under `skills/skills-codex/` and `skills/skills-codex-*-review/` do NOT include manual-review wiring — they target Codex CLI and other platforms that lack MCP support. Oracle-pro support in those mirrors is unaffected.

### Nightmare mode (Codex-only)

Manual review supports medium/hard MCP-style review. Codex-exec nightmare mode is Codex-only and must fail closed when reviewer is manual.

### NOT installed = explicit error (not silent fallback)

If manual-review MCP is not installed, `— reviewer: manual` prints install instructions and stops. It does NOT fall back to Codex — the target user likely has no Codex subscription, so a silent fallback would fail anyway.

### `codex exec` CLI is NOT an equivalent Codex backend

The mainline reviewer contract is `mcp__codex__codex` + `mcp__codex__codex-reply`: skills rely on **thread continuity** (e.g. `/idea-creator` Phase 4 runs its devil's-advocate triage as a same-thread `codex-reply`), structured returns, and saved `threadId` traces. `codex exec --ephemeral` is a stateless one-shot — fine for a single self-contained review, but NOT a drop-in replacement: hand-rewriting every MCP call to `codex exec` silently loses reply continuity and tends to mangle SKILL.md instructions (observed in the wild as "the executor skips phases and improvises" — issue #284).

If Codex MCP is broken in your setup, prefer in order:

1. Fix the MCP registration: `claude mcp add codex -s user -- codex mcp-server`, then `/mcp` in-session to (re)connect.
2. Codex-CLI-as-executor: use the native mirror pack [`skills/skills-codex/`](../skills-codex/) — designed to run inside Codex CLI without Claude-side MCP.
3. One-shot `codex exec` only for skills whose review is a single call with no follow-up reply.

## Copilot CLI Custom Agent Profiles (`--reviewer: copilot`) — explicit opt-in for auto-review-loop

**Scope: vertical slice for `/auto-review-loop` only.** It does NOT claim to support all reviewer skills. Other skills (research-review, experiment-audit, proof-checker, rebuttal, idea-creator) are not wired and continue to use Codex MCP regardless of the `--reviewer: copilot` flag.

Copilot CLI with custom agent profiles is an **explicit opt-in** reviewer backend for `/auto-review-loop`. Pass `--reviewer: copilot` to use the documented `copilot --agent` subprocess with custom agent profiles for review instead of an external MCP server. The `COPILOT_CLI` environment variable is not used for auto-detection (it is an open proposal, github/copilot-cli#2107, not a shipped feature).

**Default**: The default reviewer backend for `/auto-review-loop` is `codex` — preserving backward compatibility. Pass `--reviewer: copilot` to explicitly opt into Copilot CLI mode.

### Prerequisites — Custom Agent Profiles

Copilot CLI uses custom agent profiles (declared in `.github/agents/` or equivalent) to pin reviewer models. Two profiles are required:

| Profile name | Pinned model | Model family | File |
|-------------|-------------|-------------|------|
| `aris-reviewer-openai` | `gpt-5.4` | `openai` | `.github/agents/aris-reviewer-openai.agent.md` |
| `aris-reviewer-claude` | `claude-sonnet-4.5` | `anthropic` | `.github/agents/aris-reviewer-claude.agent.md` |

Both profiles must exist and be loadable by the Copilot CLI (`copilot --agent`). If a profile file is missing, emit `REVIEW_UNAVAILABLE` with the missing profile path — the user must create it before the copilot reviewer can function.

### Opposite-Family Routing (MANDATORY — identity assurance is limited)

The selected reviewer model family MUST differ from the family derived from the declared executor model. Same-family routing is forbidden. However, the current Copilot CLI integration cannot independently attest the parent executor's actual model, so this is a fail-closed routing rule—not proof of runtime independence.

Unlike the previous broken model-inheritance approach, the router reads the selected profile's `model:` field and passes that same value through the subprocess-level `--model` flag. This outer pin is mandatory because Copilot CLI may ignore a custom agent's model when the session model is Auto.

**Family detection requires `--executor-model`:**

The skill MUST receive `--executor-model` as a parameter. From it, derive `executor_family`:
- Model names containing `gpt`, `o1`, `o3`, `o4`, `chatgpt` → `openai`
- Model names containing `claude`, `sonnet`, `opus`, `haiku` → `anthropic`
- Model names containing `gemini` → `google`
- Anything else → `unknown`

**Router rule — pick the OPPOSITE family profile:**

```
executor_family = openai  → reviewer_profile = "aris-reviewer-claude"  (anthropic)
executor_family = anthropic → reviewer_profile = "aris-reviewer-openai" (openai)
executor_family = google  → reviewer_profile = "aris-reviewer-openai"  (openai, default cross-family)
executor_family = unknown → REVIEW_UNAVAILABLE. Stop. "Cannot determine executor model family.
                            Supply --executor-model <model> to identify the executor model."
```

This selects an opposite-family reviewer relative to the declared executor identity. If that declaration is missing or its family cannot be determined, fail closed. Do not describe the result as independently verified.

### Identity Declaration and Evidence Limits — `--executor-model`

The auto-review-loop SKILL.md MUST accept `--executor-model <model>` as a parameter. This is NOT optional when `--reviewer: copilot` is used. It is the available routing input, but it is caller-declared—not an independently attested runtime identity.

**In the state JSON (`REVIEW_STATE.json`) and every trace, record:**

```json
{
  "executor_model": "claude-sonnet-4-5",
  "executor_model_source": "caller-declared",
  "executor_family": "anthropic",
  "reviewer_profile": "aris-reviewer-openai",
  "requested_reviewer_model": "gpt-5.4",
  "reported_reviewer_model": "<model the copilot CLI actually reports using, if available>",
  "reviewer_model_source": "requested",
  "reviewer_family": "openai",
  "family_relation": "different",
  "independence_verified": "unverified"
}
```

- `executor_model` comes from `--executor-model`; record `executor_model_source: "caller-declared"`.
- `executor_family` is derived from `executor_model` via the rules above.
- `reviewer_profile` is the profile name selected by the router.
- `requested_reviewer_model` is read from the selected profile file and passed explicitly with `--model`.
- `reported_reviewer_model` is what the Copilot CLI reports (for example through a captured `gen_ai.response.model` OpenTelemetry attribute), if available; otherwise it is `"unavailable"`.
- `reviewer_family` is derived from `reported_reviewer_model` (if available) or `requested_reviewer_model`; caller-supplied family labels are never trusted.
- `family_relation` is `different`, `same`, or `unknown`, derived from the two model strings.
- `independence_verified` is `false` for a known same-family pair and `"unverified"` when the pair differs but the executor identity is caller-declared. Different strings alone never produce `true`.

**Fail closed when:**
- `--executor-model` is missing AND `--reviewer: copilot` is used → `REVIEW_UNAVAILABLE`.
- `executor_family` is `unknown` → `REVIEW_UNAVAILABLE`.
- The selected profile file does not exist → `REVIEW_UNAVAILABLE`.
- The profile has no non-empty `model:` field, or the derived reviewer family is unknown/same-family → `REVIEW_UNAVAILABLE`.
- `copilot --help` does not advertise `--model`, `--effort`, and `--allow-tool` → `REVIEW_UNAVAILABLE`; do not silently run an older unpinned CLI.
- `family_relation` is `same` or `unknown` → `REVIEW_UNAVAILABLE` for Copilot routing. `family_relation: different` is usable for drive routing but remains `independence_verified: "unverified"`.

### Routing Logic

```
Parse $ARGUMENTS for `--reviewer:` and `--executor-model` directives.

If `--reviewer: copilot` (explicit opt-in):
    → Require `--executor-model`. If missing:
        Print: "⚠️ --reviewer: copilot requires --executor-model <model> for
                opposite-family routing (identity remains caller-declared)."
        Emit REVIEW_UNAVAILABLE. Stop.
    → Derive executor_family from --executor-model.
    → If executor_family is unknown:
        Print: "⚠️ Cannot determine model family for executor model '<model>'.
                Known families: openai (gpt, o1, o3, o4, chatgpt),
                anthropic (claude, sonnet, opus, haiku), google (gemini)."
        Emit REVIEW_UNAVAILABLE. Stop.
    → Select reviewer_profile = opposite family profile (see table above).
    → Verify the profile file exists (e.g., .github/agents/<profile>.agent.md).
      If missing:
        Print: "⚠️ Custom agent profile '<profile>.agent.md' not found.
                Create it at .github/agents/<profile>.agent.md with model: <model>."
        Emit REVIEW_UNAVAILABLE. Stop.
    → Read the first frontmatter `model:` value as requested_reviewer_model.
      Derive reviewer_family from that model string and confirm it differs from
      executor_family. Never trust a free-form model_family field.
    → Verify `copilot` CLI is available (`command -v copilot`). If not:
        Print: "⚠️ --reviewer: copilot requires Copilot CLI (`copilot` command)."
        Emit REVIEW_UNAVAILABLE. Do NOT silently change the requested drive
        transport to Codex/manual. This does not remove the separately
        documented requirement for a Codex/manual finalizer after a positive
        Copilot verdict.
    → Verify the CLI supports `--model`, `--effort`, and `--allow-tool`.
    → Use `copilot --agent` with the selected profile, the parsed model,
      `--effort xhigh`, and read-only tool permission for each review round.

If no `--reviewer:` specified:
    → Default to Codex MCP (`codex` backend).
      This preserves backward compatibility — existing Claude Code users
      do NOT need to add --reviewer: codex to keep their current behavior.
    → `--reviewer: copilot` must be passed explicitly. The `COPILOT_CLI`
      environment variable is not shipped (github/copilot-cli#2107 is an
      open proposal) and is not used for auto-detection.
```

### Copilot Subprocess Review Call

For the copilot reviewer, use the documented `copilot --agent` subprocess form with custom agent profiles:

```bash
# PROFILE_FILE is the router-selected .agent.md file.
REVIEWER_MODEL="$(python3 - "$PROFILE_FILE" <<'PY'
import pathlib, sys
lines = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
models = []
if lines and lines[0].strip() == "---":
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith("model:"):
            models.append(line.split(":", 1)[1].strip().strip("\"'"))
if len(models) == 1:
    print(models[0])
PY
)"
[[ -n "$REVIEWER_MODEL" ]] || { echo "REVIEW_UNAVAILABLE: profile has no model" >&2; exit 1; }
COPILOT_HELP="$(copilot --help 2>&1)" || { echo "REVIEW_UNAVAILABLE: copilot unavailable" >&2; exit 1; }
for required_flag in --model --effort --allow-tool; do
  grep -q -- "$required_flag" <<<"$COPILOT_HELP" || {
    echo "REVIEW_UNAVAILABLE: copilot lacks $required_flag" >&2
    exit 1
  }
done

# Build the complete round prompt as a data file using the host's file-writing
# API. Never render untrusted paths/content into shell source.
REVIEW_TASK_FILE="review-stage/ROUND_${ROUND}_COPILOT_PROMPT.md"
[[ -f "$REVIEW_TASK_FILE" ]] || { echo "REVIEW_UNAVAILABLE: missing prompt artifact" >&2; exit 1; }
PROMPTFILE="$(mktemp)" || { echo "REVIEW_UNAVAILABLE: mktemp failed" >&2; exit 1; }
trap 'rm -f "$PROMPTFILE"' EXIT
cat -- "$REVIEW_TASK_FILE" > "$PROMPTFILE"
copilot --agent "$REVIEWER_PROFILE" --model "$REVIEWER_MODEL" \
  --effort xhigh --allow-tool=read --prompt "$(cat "$PROMPTFILE")"
```

The profile name is the router-selected opposite-family profile (`aris-reviewer-openai` or `aris-reviewer-claude`).

**VERIFIED:** `copilot --agent NAME --prompt "..."` is the documented subprocess invocation form per GitHub Copilot CLI docs. Custom agent profiles (`.agent.md` files in `.github/agents/`) are discovered automatically.

**VERIFIED:** `copilot --agent` runs synchronously (like `codex exec`), returning the response to stdout. Multi-round state is maintained via a reviewer-owned memory artifact, not a persistent subagent handle.

### Multi-Round Continuity

`copilot --agent` does **not** expose a persistent thread/agent handle (no equivalent to `threadId` or `agentId`). For multi-round review (`/auto-review-loop`):

1. **Each round is a fresh `copilot --agent` call** with the same profile.
2. **Reviewer memory is carried via one canonical written artifact** (`review-stage/REVIEWER_MEMORY.md`), passed as context in each round's prompt. The reviewer writes to this artifact at the end of each round.
3. The executor appends the reviewer's raw response to `review-stage/REVIEWER_MEMORY.md`, then includes that same artifact in the next round's prompt. There is no project-root fallback.

**Pattern for round 2+:**

First use the host's **Write tool**—never Bash, `echo`, a heredoc, or generated
shell assignments—to overwrite
`review-stage/CURRENT_REVIEW_INPUTS.md`. Store the exact changed paths, diff
artifact/range, and updated result paths under static labels. Those values may
contain arbitrary repository-controlled bytes and must remain file data.

```bash
# ARIS_ROUND2_COPILOT_BEGIN
# Dynamic values were written with the Write tool; shell only reads them as data.
MEMORY_FILE="review-stage/REVIEWER_MEMORY.md"
ROUND_INPUT_FILE="review-stage/CURRENT_REVIEW_INPUTS.md"
[[ -f "$MEMORY_FILE" && -f "$ROUND_INPUT_FILE" ]] || {
  echo "REVIEW_UNAVAILABLE: missing reviewer memory or round inputs" >&2
  exit 1
}
PROMPTFILE="$(mktemp)" || { echo "REVIEW_UNAVAILABLE: mktemp failed" >&2; exit 1; }
trap 'rm -f "$PROMPTFILE"' EXIT
{
cat <<'ARIS_MEMORY_HEADER'
[Round N/MAX_ROUNDS]

## Your Memory From Previous Rounds
ARIS_MEMORY_HEADER
cat -- "$MEMORY_FILE"
cat <<'ARIS_MEMORY_FOOTER'

## Current State
Since your last review these files changed — read them yourself:
ARIS_MEMORY_FOOTER
cat -- "$ROUND_INPUT_FILE"
cat <<'ARIS_MEMORY_INSTRUCTIONS'

Please re-score and re-assess. Are the remaining concerns addressed?
Same format: Score, Verdict, Remaining Weaknesses, Minimum Fixes.

At the end of your review, write (or append to) the Memory Update section
in your response — this will be passed back to you next round.
ARIS_MEMORY_INSTRUCTIONS
} > "$PROMPTFILE"
copilot --agent "$REVIEWER_PROFILE" --model "$REVIEWER_MODEL" \
  --effort xhigh --allow-tool=read --prompt "$(cat "$PROMPTFILE")"
# ARIS_ROUND2_COPILOT_END
```

**IMPORTANT:** This is architecturally different from `SendMessage` (which would require a persistent subagent handle that `copilot --agent` does not provide). The memory-artifact pattern is the documented alternative for stateful multi-round workflows in Copilot CLI.

### Known Limitations & Upstream Dependencies

| Capability | Codex MCP | Copilot `--agent` + profiles | Status |
|-----------|-----------|--------------------------|--------|
| Task spawning | `mcp__codex__codex` | `copilot --agent` subprocess (documented Copilot CLI form) | **Verified** — in Copilot CLI docs |
| Model pinning | `gpt-5.6-sol` param | Profile model repeated as subprocess `--model` | **Verified** — prevents Auto-session inheritance |
| Cross-model family | Configurable (agy, manual, llm-chat) | Router picks opposite-family profile from declared executor model | **Route verified; executor identity unverified** |
| Thread continuity | `codex-reply` (threadId) | New `copilot --agent` call + `review-stage/REVIEWER_MEMORY.md` artifact | **Verified** — memory-artifact pattern |
| Reasoning effort control | `xhigh` / `ultra` tiers | Subprocess `--effort xhigh` | **Verified** — capability-gated before review |
| File reading | Reads listed files | Can read files via restricted custom-agent tools | **Verified** — profile + `--allow-tool=read` |
| Review tracing | `.aris/traces/` schema | Same schema + model sources/family relation | **Verified with explicit identity limit** |

**What is verified vs assumed:**

| Assertion | Status | Source |
|----------|--------|--------|
| `copilot --agent NAME --prompt "..."` invocation form | **Verified** | Live Copilot CLI testing; documented subprocess form |
| Custom agent profiles (`.agent.md` files) discovered automatically | **Verified** | `.github/agents/` convention documented, `.agent.md` extension confirmed |
| Profile pins model in frontmatter | **Verified** | Agent profile format from Copilot CLI docs |
| `copilot --agent` runs synchronously | **Verified** | Returns response to stdout; confirmed by live testing |
| Memory-artifact multi-round pattern | **Verified** | `review-stage/REVIEWER_MEMORY.md` carries state between fresh subprocesses |
| Reasoning effort for Copilot | **Verified** | Explicit subprocess `--effort xhigh`; unsupported CLIs fail closed |
| Parent executor's actual resolved model | **Unverified** | `--executor-model` is caller-declared; no stable parent-session attestation is available to the skill |
| End-to-end acceptance without MCP/manual | **Not provided** | Copilot is drive-only; a positive drive verdict requires a Codex/manual finalizer |

### Invariants

- `--reviewer: copilot` is an **explicit opt-in** for `/auto-review-loop`. The default reviewer backend is `codex` (backward compatible). Use `--reviewer: codex` or `--reviewer: copilot` to select.
- `--executor-model` is **MANDATORY** when `--reviewer: copilot` is used. Fail closed if missing.
- **Opposite-family route is mandatory** relative to the caller-declared executor model. Same/unknown family → `REVIEW_UNAVAILABLE`; a different relation is recorded as `independence_verified: "unverified"`, not as attestation.
- **Review floor: Copilot remains drive-only by policy.** Copilot calls pin `xhigh` and record `effort_unpinned: false`, but final acceptance still requires a separately traced `codex` or `manual` finalizer. This intentionally reduces MCP use during drive rounds; it does not eliminate the finalizer dependency.
- Custom agent profile models are repeated with subprocess `--model`; do not rely on profile-only pinning under an Auto session.
- Explicit reviewer directives (`codex`, `oracle-pro`, `agy`, `manual`) are separate from copilot.
- Reviewer independence protocol still applies (pass file paths, not summaries).
- `effort` and `difficulty` are orthogonal — they don't change the reviewer backend.
- If `copilot` CLI is unavailable → `REVIEW_UNAVAILABLE` for the requested drive round (no silent backend substitution). A successful Copilot-positive path still requires the documented external finalizer.
- If executor family is unknown → `REVIEW_UNAVAILABLE` (fail closed).
- NEVER fabricate a review verdict without an actual reviewer call.

### Using Codex Instead of Copilot

Pass `--reviewer: codex` to use Codex MCP instead of the Copilot CLI backend. `codex` is the default — no explicit flag needed.
