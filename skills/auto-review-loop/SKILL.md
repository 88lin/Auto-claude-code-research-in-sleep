---
name: auto-review-loop
description: Autonomous multi-round research review loop. Repeatedly reviews via external reviewer backend (Codex or manual), implements fixes, and re-reviews until positive assessment or max rounds reached. Use when user says "auto review loop", "review until it passes", or wants autonomous iterative improvement.
argument-hint: "[topic-or-scope]"
allowed-tools: Bash(*), Read, Grep, Glob, Write, Edit, Skill, Task, mcp__codex__codex, mcp__codex__codex-reply, mcp__manual_review__review, mcp__manual_review__review_reply
---

# Auto Review Loop: Autonomous Research Improvement

> 🔒 **Do not wrap this skill in `/loop`, `/schedule`, or `CronCreate`.** It
> already loops internally (review → fix → re-review) and the reviewer carries
> round-to-round memory in one `threadId` (`codex-reply`). An external timer
> re-enters from the top each tick — fresh `threadId`, reviewer memory reset —
> firing the verdict on wall-clock time instead of on artifact change: zero new
> signal, full token cost. If you want to schedule something, schedule the
> *external wait that precedes it* (experiments done → then run this once). See
> [`shared-references/external-cadence.md`](../shared-references/external-cadence.md).

Autonomously iterate: review → implement fixes → re-review, until the external reviewer gives a positive assessment or MAX_ROUNDS is reached.

## Context: $ARGUMENTS

## Constants

- MAX_ROUNDS = 4
- POSITIVE_THRESHOLD: score >= 6/10 **AND** verdict ∈ {"ready", "almost"} — **both** must hold. This matches the operative Phase-E STOP CONDITION exactly; the verdict vocabulary is {"ready", "almost", "not ready"} (a high score with a "not ready" verdict does NOT stop the loop). Earlier wording here used `or` and a stale verdict set ("accept"/"sufficient"/"ready for submission") — that was an internal inconsistency; the `AND` form is authoritative.
- REVIEW_DOC: `review-stage/AUTO_REVIEW.md` (cumulative log) *(fall back to `./AUTO_REVIEW.md` for legacy projects)*
- REVIEWER_MODEL = `gpt-5.6-sol` — Default model for the Codex backend. Must be an OpenAI model (e.g., `gpt-5.6-sol`, `o3`, `gpt-4o`). Manual backend uses whatever model the user chooses.
- **REVIEWER_BACKEND** — Default is `codex` (Codex MCP, xhigh — backward compatible, no change for existing users). Override with `— reviewer: copilot` (explicit Copilot CLI — uses `copilot --agent` subprocess + custom agent profiles, cross-family enforced via opposite-family profile selection, requires `--executor-model`), `— reviewer: oracle-pro` for Oracle MCP, or `— reviewer: manual` for Manual Review MCP. If manual-review MCP is unavailable, stop and print the install command; do not fall back to Codex. See `shared-references/reviewer-routing.md`. **Note:** `COPILOT_CLI` env var does not exist persistently (open proposal, github/copilot-cli#2107). Copilot reviewer is explicit-only until a reliable auto-detection signal ships.
- **OUTPUT_DIR = `review-stage/`** — All review-stage outputs go here. Create the directory if it doesn't exist.
- **HUMAN_CHECKPOINT = false** — When `true`, pause after each round's review (Phase B) and present the score + weaknesses to the user. Wait for user input before proceeding to Phase C. The user can: approve the suggested fixes, provide custom modification instructions, skip specific fixes, or stop the loop early. When `false` (default), the loop runs fully autonomously.
- **COMPACT = false** — When `true`, (1) read `EXPERIMENT_LOG.md` and `findings.md` instead of parsing full logs on session recovery, (2) append key findings to `findings.md` after each round.
- **REVIEWER_DIFFICULTY = medium** — Controls how adversarial the reviewer is. Three levels:
  - `medium` (default): Current behavior — MCP-based review, the executor controls what context the reviewer sees.
  - `hard`: Adds **Reviewer Memory** (the reviewer tracks its own suspicions across rounds) + **Debate Protocol** (the executor can rebut, the reviewer rules).
  - `nightmare`: Everything in `hard` + **Codex exec reviewer reads the repo directly** via `codex exec` (the executor cannot filter what the reviewer sees) + **Adversarial Verification** (the reviewer independently checks if code matches claims).
- **RENDER_HTML = true** — When `true` (default), auto-render `review-stage/AUTO_REVIEW.md` to HTML on loop termination via `/render-html`. Uses `--no-review` (the loop itself IS the cross-model review; the HTML is a structural conversion). Set `false` to skip, or pass `— render html: false`.

> ⚠️ **Nightmare + Manual incompatibility**: If `REVIEWER_BACKEND = manual` and `REVIEWER_DIFFICULTY = nightmare`, STOP with:
> "difficulty: nightmare requires Codex CLI / codex exec and is not compatible with --reviewer: manual. Use difficulty: hard, or switch reviewer to codex."

> 💡 Override: `/auto-review-loop "topic" — compact: true, human checkpoint: true, difficulty: hard`

## Reviewer Calling Convention

When calling the reviewer, branch on REVIEWER_BACKEND:

**If REVIEWER_BACKEND = `copilot`:**
  **Require `--executor-model`:** if not provided → emit `REVIEW_UNAVAILABLE`.
  **Determine executor family** from `--executor-model` (see reviewer-routing.md).
  **Router picks opposite-family profile:**
  - executor_family=openai → profile="aris-reviewer-claude" (anthropic)
  - executor_family=anthropic → profile="aris-reviewer-openai" (openai)
  - executor_family=google → profile="aris-reviewer-openai" (openai, default cross)
  - executor_family=unknown → `REVIEW_UNAVAILABLE` (fail closed).
  **Verify the profile file** exists at `.github/agents/<profile>.agent.md`.
  If missing → `REVIEW_UNAVAILABLE`.
  **Use the `copilot --agent` subprocess** (documented Copilot CLI form)
  with the selected profile for each review call.
  **Multi-round:** each round is a fresh `copilot --agent` call with the same
  profile; reviewer memory is carried via `REVIEWER_MEMORY.md` artifact.
  If `copilot` CLI is unavailable → `REVIEW_UNAVAILABLE` (no MCP-dependent
  fallback — the user chose copilot because they may have no MCP access).
  See `shared-references/reviewer-routing.md` for the full copilot contract.

**If REVIEWER_BACKEND = `codex`:**
  Use `mcp__codex__codex` for new review threads.
  Use `mcp__codex__codex-reply` for follow-up rounds (reuse threadId).

**If REVIEWER_BACKEND = `manual`:**
  Use `mcp__manual_review__review` for new review threads with:
    prompt: [exact same prompt that would go to Codex]
    config: {"model_reasoning_effort": "xhigh"}
  Save the returned `threadId`.
  Use `mcp__manual_review__review_reply` for follow-up rounds with:
    threadId: [saved manual-review threadId]
    prompt: [follow-up prompt]
    config: {"model_reasoning_effort": "xhigh"}

Prompt fidelity: the manual prompt must be exactly the same text that Codex would receive.
Review tracing applies equally to both backends.

## State Persistence (Compact Recovery)

Long-running loops may hit the context window limit, triggering automatic compaction. To survive this, persist state to `review-stage/REVIEW_STATE.json` after each round:

```json
{
  "run_id": "run_20260713_a1b2c3d4",
  "round": 2,
  "threadId": "019cd392-...",
  "reviewer_profile": "aris-reviewer-openai",
  "reviewer_backend": "copilot",
  "executor_model": "claude-sonnet-4-5",
  "executor_family": "anthropic",
  "reviewer_family": "openai",
  "independence_verified": true,
  "status": "in_progress",
  "difficulty": "medium",
  "last_score": 5.0,
  "last_verdict": "not ready",
  "pending_experiments": ["screen_name_1"],
  "timestamp": "2026-03-13T21:00:00"
}
```

- **`run_id`** — Globally unique per invocation. Generated on fresh start as `run_<YYYYMMDD>_<8-char-hex>` (e.g., `run_20260713_a1b2c3d4`). Preserved across round writes. On resume, read from state file unchanged. This binds all round state, reviewer-memory appends, and acquittal receipts to one run so a stale completed state from a previous invocation cannot leak into the current run's acquittal check.

When REVIEWER_BACKEND = `copilot`, save `reviewer_profile` (the custom agent profile name used), `executor_model` (from `--executor-model`), `executor_family` (derived), `reviewer_family` (from profile's pinned model), and `independence_verified: true` (confirmed `executor_family != reviewer_family`). Copilot tasks do not return a persistent agent ID — each round is a fresh `task` call with the same profile. For `codex` backend, save `threadId` (Codex MCP thread ID). For `manual` backend, save `threadId` (manual-review thread ID). On resume, use the `reviewer_backend` field to determine the correct continuation mechanism (fresh `task` call with profile for copilot, `codex-reply` for codex, `manual_review_reply` for manual).

**Write this file at the end of every Phase E** (after documenting the round). Overwrite each time — only the latest round's state matters. The `run_id` field MUST persist unchanged across overwrites within the same run.

**On completion** (positive assessment or max rounds), set `"status": "completed"` so future invocations don't accidentally resume a finished loop.

### Append-Only Acquittal Receipt

In addition to the overwritable state file, maintain an **append-only** acquittal log at `review-stage/ACQUITTAL_LOG.jsonl`. Each line is a standalone JSON object recording an acquitting positive verdict:

```jsonl
{"run_id":"run_20260713_a1b2c3d4","round":3,"backend":"codex","effort":"xhigh","verdict":"ready","score":7.5,"trace_id":"auto-review-loop/2026-07-13_run03","timestamp":"2026-07-13T14:22:00Z"}
```

**Rules (non-negotiable):**

| Rule | Detail |
|------|--------|
| **Append-only** | Never delete, never truncate, never overwrite lines. Only `>>`. |
| **Who writes** | Only `codex` or `manual` backends at `xhigh`+ effort. Copilot NEVER writes an acquittal line. |
| **When to write** | At the end of Phase E, immediately after a positive verdict (score >= 6 AND verdict ∈ {"ready", "almost"}) from a qualifying backend. |
| **`run_id` binding** | Every acquittal line carries the current `run_id`. The stop-evaluation gate for Copilot MUST verify `run_id` matches the current run before accepting an acquittal. |
| **Trace linkage** | `trace_id` MUST reference a trace artifact in `.aris/traces/` (per Review Tracing protocol) so every acquittal is independently verifiable. |
| **No overwrite** | `REVIEW_STATE.json` is overwritten each round (only latest state). `ACQUITTAL_LOG.jsonl` is NEVER overwritten — it is the permanent, cumulative record. |

**Why this exists:** `REVIEW_STATE.json` is overwritten each round (only the latest state matters per the contract above). When a run completes with `status: "completed"` and a codex/manual positive verdict, a subsequent fresh-start invocation writes a new `REVIEW_STATE.json` — obliterating the prior run's acquittal data. The Copilot stop-evaluation gate (Phase B.5.1) must check for an acquittal from the **current run**, not a stale state file. The append-only `ACQUITTAL_LOG.jsonl`, with `run_id` matching, is the only reliable source of truth.

## Output Protocols

> Follow these shared protocols for all output files:
> - **[Output Versioning Protocol](../shared-references/output-versioning.md)** — write timestamped file first, then copy to fixed name
> - **[Output Manifest Protocol](../shared-references/output-manifest.md)** — log every output to MANIFEST.md
> - **[Output Language Protocol](../shared-references/output-language.md)** — respect the project's language setting

## Workflow

### Initialization

1. **Check for `review-stage/REVIEW_STATE.json`** *(fall back to `./REVIEW_STATE.json` if not found — legacy path)*:
   - If neither path exists: **fresh start** (normal case, identical to behavior before this feature existed)
     - **Generate `run_id`**: `run_<YYYYMMDD>_<8-char-hex>` (e.g., `run_20260713_a1b2c3d4`). Use `date +%Y%m%d` and 8 random hex characters. This run_id persists across all round writes and binds acquittal receipts to this invocation.
   - If it exists AND `status` is `"completed"`: **fresh start** (previous loop finished normally — but its `ACQUITTAL_LOG.jsonl` entries are retained as an audit trail with their own `run_id`, and are NOT valid for the current run's stop gate)
     - **Generate a new `run_id`** for this invocation.
   - If it exists AND `status` is `"in_progress"` AND `timestamp` is older than 24 hours: **fresh start** (stale state from a killed/abandoned run — delete the file and start over)
     - **Generate a new `run_id`** for this invocation.
   - If it exists AND `status` is `"in_progress"` AND `timestamp` is within 24 hours: **resume**
     - Read the state file to recover `run_id`, `round`, `threadId` (or `reviewer_profile` for copilot backend), `reviewer_backend`, `last_score`, `pending_experiments`
     - **Legacy backward compat**: if `reviewer_backend` is absent from the state file, default to `codex` (pre-copilot-era states did not record this field). If `run_id` is absent from the state file (pre-run_id era), generate a new `run_id` and log: "No run_id in legacy state file; assigned run_<...> for this resume."
     - Read `review-stage/AUTO_REVIEW.md` to restore full context of prior rounds *(fall back to `./AUTO_REVIEW.md`)*
     - If `pending_experiments` is non-empty, check if they have completed (e.g., check screen sessions)
     - Resume from the next round (round = saved round + 1)
     - Use `reviewer_backend` to determine continuation: `codex-reply` for codex, fresh `task` call with saved `reviewer_profile` for copilot, `manual_review_reply` for manual
     - Log: "Recovered from context compaction. Resuming at Round N."
2. Read project narrative documents, memory files, and any prior review documents. **When `COMPACT = true` and compact files exist**: read `findings.md` + `EXPERIMENT_LOG.md` instead of full `review-stage/AUTO_REVIEW.md` and raw logs — saves context window.
3. Read recent experiment results (check output directories, logs)
4. Identify current weaknesses and open TODOs from prior reviews
5. Initialize round counter = 1 (unless recovered from state file)
6. Create/update `review-stage/AUTO_REVIEW.md` with header and timestamp

### Loop (repeat up to MAX_ROUNDS)

**Step 0 — Initialize `round_backend`:** At the start of each round, before Phase A, snapshot the current `REVIEWER_BACKEND` value: `round_backend = <current REVIEWER_BACKEND>`. This variable labels which backend actually ran the CURRENT round. If escalation occurs later in Phase B.5.1 (copilot → codex/manual), `round_backend` retains the pre-escalation value (the backend that ran), while `REVIEWER_BACKEND` in state is updated for the NEXT round. Phase E references `round_backend` for documentation and the acquittal gate.

#### Phase A: Review

**Route by REVIEWER_BACKEND and REVIEWER_DIFFICULTY.**

If REVIEWER_BACKEND = `copilot`, enforce cross-family invariant FIRST:
- Require `--executor-model <model>` parameter. If missing → `REVIEW_UNAVAILABLE`. Stop.
- Derive `executor_family` from `executor_model`:
  - Model names containing `gpt`, `o1`, `o3`, `o4`, `chatgpt` → `openai`
  - Model names containing `claude`, `sonnet`, `opus`, `haiku` → `anthropic`
  - Model names containing `gemini` → `google`
  - Anything else → `unknown`
- If `executor_family` is `unknown` → `REVIEW_UNAVAILABLE` (fail closed). Stop.
- Router picks opposite-family profile:
  - `openai` → `"aris-reviewer-claude"` (anthropic, forced cross-family)
  - `anthropic` → `"aris-reviewer-openai"` (openai, forced cross-family)
  - `google` → `"aris-reviewer-openai"` (openai default)
- Verify the profile file exists at `.github/agents/<profile>.agent.md`.
  If missing → `REVIEW_UNAVAILABLE`. Stop.
- Adapt the Codex MCP calls below to use the **`copilot --agent`** subprocess
  (documented Copilot CLI form):
  - Replace `mcp__codex__codex` with `copilot --agent "<profile>" --prompt "..."`
  - Each round is a fresh `copilot --agent` call with the same profile +
    `REVIEWER_MEMORY.md` artifact carrying round-to-round state.
  - The prompt text and Review Tracing are identical to the Codex path.
  - If `copilot` CLI is unavailable → `REVIEW_UNAVAILABLE` (no MCP fallback).
  - If `REVIEWER_DIFFICULTY = nightmare`, skip Copilot (nightmare requires Codex
    exec): emit `REVIEW_UNAVAILABLE`.
  See `shared-references/reviewer-routing.md`.

**If REVIEWER_BACKEND ∈ {codex, manual}:** use the backend-specific MCP call per the
Reviewer Calling Convention above. The prompt text is the same regardless of backend.

##### Medium (default) — MCP Review

Send comprehensive context to the external reviewer using the selected backend.

*For codex backend:*

```
mcp__codex__codex:
  model: gpt-5.6-sol
  config: {"model_reasoning_effort": "xhigh"}
  prompt: |
    [Round N/MAX_ROUNDS of autonomous review loop]

    Review the work directly from its artifacts — executor notes are not
    evidence, so read the files yourself rather than trusting my framing:
    - Claims / paper draft: <path>
    - Methods / code under review: <path(s)>
    - Raw results (verbatim files, not a summary): <path(s)>
    - Changed since last round: <changed-file paths> — read the diff, not my description

    Please act as a senior ML reviewer (NeurIPS/ICML level). Start from the
    assumption that the work is broken somewhere — your job is to find where.
    Be adversarial. Trust nothing the author tells you — verify everything
    yourself.

    1. Score this work 1-10 for a top venue
    2. List remaining critical weaknesses (ranked by severity)
    3. For each weakness, specify the MINIMUM fix (experiment, analysis, or reframing)
    4. State clearly: is this READY for submission? Yes/No/Almost

    Be brutally honest. If, after genuinely trying to break it, the work holds
    up and is ready, say so clearly.
```

*For manual backend:* use `mcp__manual_review__review` with the `prompt` text above and `config: {"model_reasoning_effort": "xhigh"}`. Save the returned `threadId`.

If this is round 2+, use `mcp__codex__codex-reply` (codex) or `mcp__manual_review__review_reply` (manual) with the saved threadId.

##### Hard — MCP Review + Reviewer Memory

Same as medium, but **prepend Reviewer Memory** to the prompt. Use the selected backend.

*For codex backend:*

```
mcp__codex__codex:
  model: gpt-5.6-sol
  config: {"model_reasoning_effort": "xhigh"}
  prompt: |
    [Round N/MAX_ROUNDS of autonomous review loop]

    ## Your Reviewer Memory (persistent across rounds)
    [Paste full contents of REVIEWER_MEMORY.md here]

    IMPORTANT: You have memory from prior rounds. Check whether your
    previous suspicions were genuinely addressed or merely sidestepped.
    The author (Claude) controls what context you see — be skeptical
    of convenient omissions.

    Review directly from the artifacts (paths below) — read the files yourself:
    - Claims / methods / code: <path(s)>
    - Raw results: <path(s)>
    - Changed since last round: <changed-file paths> (read the raw diff)

    Please act as a senior ML reviewer (NeurIPS/ICML level).
    1. Score this work 1-10 for a top venue
    2. List remaining critical weaknesses (ranked by severity)
    3. For each weakness, specify the MINIMUM fix
    4. State clearly: is this READY for submission? Yes/No/Almost
    5. **Memory update**: List any new suspicions, unresolved concerns,
       or patterns you want to track in future rounds.

    Be brutally honest. Actively look for things the author might be hiding.
```

##### Nightmare — Codex Exec (GPT reads repo directly)

**Do NOT use MCP.** Instead, let GPT access the repo autonomously via `codex exec`:

```bash
codex exec "$(cat <<'PROMPT'
You are an adversarial senior ML reviewer (NeurIPS/ICML level).
This is Round N/MAX_ROUNDS of an autonomous review loop.

## Your Reviewer Memory (persistent across rounds)
[Paste full contents of REVIEWER_MEMORY.md]

## Instructions
You have FULL READ ACCESS to this repository. The author (Claude) does NOT
control what you see — explore freely. Your job is to find problems the
author might hide or downplay.

DO THE FOLLOWING:
1. Read the experiment code, results files (JSON/CSV), and logs YOURSELF
2. Verify that reported numbers match what's actually in the output files
3. Check if evaluation metrics are computed correctly (ground truth, not model output)
4. Look for cherry-picked results, missing ablations, or suspicious hyperparameter choices
5. Read NARRATIVE_REPORT.md or review-stage/AUTO_REVIEW.md for the author's claims — then verify each against code

OUTPUT FORMAT:
- Score: X/10
- Verdict: ready / almost / not ready
- Verified claims: [which claims you independently confirmed]
- Unverified/false claims: [which claims don't match the code or results]
- Weaknesses (ranked): [with MINIMUM fix for each]
- Memory update: [new suspicions and patterns to track next round]

Be adversarial. Trust nothing the author tells you — verify everything yourself.
PROMPT
)" --skip-git-repo-check 2>&1
```

**Key difference**: In nightmare mode, GPT independently reads code, result files, and logs. Claude cannot filter or curate what GPT sees. This is the closest analog to a real hostile reviewer who reads your actual paper + supplementary materials.

#### Phase B: Parse Assessment

**CRITICAL: Save the FULL raw response** from the external reviewer verbatim (store in a variable for Phase E). Do NOT discard or summarize — the raw text is the primary record.

Then extract structured fields:
- **Score** (numeric 1-10)
- **Verdict** ("ready" / "almost" / "not ready")
- **Action items** (ranked list of fixes)

#### Phase B.5: Reviewer Memory Update

After parsing the assessment, append to `REVIEWER_MEMORY.md` in the project root. Copilot backend depends on this file for round-to-round continuity (every round is a fresh process), so the update runs regardless of `REVIEWER_DIFFICULTY`:

```markdown
# Reviewer Memory

## Round 1 — Score: X/10

### Raw Reviewer Response (verbatim)
[Paste the COMPLETE raw reviewer response here — never summarized or curated by the executor.]

### Memory Update
[Reviewer's own memory update section, if provided — verbatim.]
- **Suspicion**: [what the reviewer flagged]
- **Unresolved**: [concerns not yet addressed]
- **Patterns**: [recurring issues the reviewer noticed]

---

## Round 2 — Score: X/10

### Raw Reviewer Response (verbatim)
[Paste the COMPLETE raw reviewer response here.]

### Memory Update
- **Previous suspicions addressed?**: [yes/no for each, with reviewer's judgment]
- **New suspicions**: [...]
- **Unresolved**: [carried forward + new]

---
```

**Rules**:
- **Append-only — never delete, never truncate.** The file is a reviewer-owned audit trail. The executor must never summarize, curate, or edit prior rounds' content. Append the reviewer's full raw response for this round verbatim, then append a memory update section if the reviewer provided one.
- Each round's append must be the reviewer's own words — if the reviewer's response includes a "Memory update" section, copy it verbatim as a `## Round N — Memory Update` subsection after the raw response.
- This file is passed back to the reviewer in the next round's Phase A — it is the reviewer's persistent memory.
- **Record the file's SHA-256 hash before each reviewer call** and pass it to `save_trace.sh` via `--memory-hash`. Hash the memory as supplied to the call (pre-call artifact), not the post-append version, so the trace proves which memory was in play for that invocation.
- **If the score REGRESSES round-to-round**, don't just write a new memory line:
  diff the two rounds' raw `.response.md` files in `.aris/traces/` first and find
  the exact criterion that flipped (see `shared-references/review-tracing.md`
  § *Debugging With Traces*). The memory file is a summary; the trace is evidence.

#### Phase B.5.1: Stop-Evaluation Gate

**STOP CONDITION — branch by REVIEWER_BACKEND:**

- **If REVIEWER_BACKEND ∈ {codex, manual}:** If score >= 6 AND verdict ∈ {"ready", "almost"} (exact match — "not ready" does NOT qualify) → stop loop, document final state. (The acquittal line is recorded in Phase E — this gate decides, Phase E documents. Do NOT write the acquittal line here.)
- **If REVIEWER_BACKEND = copilot:** Copilot is drive-only (effort-unpinned, per Key Rules). Do NOT stop on a copilot-issued positive verdict unless a `codex` or `manual` backend at `xhigh`+ effort has already issued an acquitting positive verdict **in this same run**. To check: scan `review-stage/ACQUITTAL_LOG.jsonl` for a line whose `run_id` matches the **current** `run_id` AND `backend` ∈ {codex, manual} AND `effort` (case-insensitive) equals `"xhigh"` AND `verdict` ∈ {"ready", "almost"} AND `score` >= 6 AND `trace_id` is non-empty AND the trace directory `.aris/traces/<trace_id>/` exists on disk. If such an acquittal exists: stop. If no same-run acquittal exists AND copilot returned a positive verdict (score >= 6, verdict ∈ {"ready", "almost"}): the loop MUST escalate — schedule the next round to use a cross-family backend for a mandatory acquittal review.

    **Escalation backend selection (cross-family check):** Determine the escalation backend by comparing `executor_family` (derived from `--executor-model` in Phase A):
    - `executor_family = anthropic` or `google` → escalate to `codex` (codex uses GPT models = openai family, guaranteed cross-family from non-openai executors).
    - `executor_family = openai` → escalate to `manual` instead of `codex` (codex is same-family, defeating the cross-family acquittal guarantee). Manual is the terminal escalation — no codex fallback (which would reopen the same-family acquittal gap). If manual is unavailable, emit `REVIEW_UNAVAILABLE`.
    - `executor_family = unknown` → `REVIEW_UNAVAILABLE` (fail closed — cannot guarantee cross-family acquittal).

    **State snapshot before escalation:** `round_backend` was already snapshotted at round start (step 0) and equals `"copilot"`. Update `reviewer_backend` in `REVIEW_STATE.json` to the selected escalation backend for the next round, and note in `AUTO_REVIEW.md` that the copilot drive triggered a mandatory cross-family acquittal. Phase E uses `round_backend` (still `"copilot"`) to label which backend ran the CURRENT round. If copilot returned a negative verdict: continue to next round with copilot backend as usual. Copilot NEVER writes an acquittal line itself.

**Why `ACQUITTAL_LOG.jsonl` instead of `REVIEW_STATE.json`:** `REVIEW_STATE.json` is overwritten every round (only the latest state matters per the state contract). A prior run's completed state with a codex/manual positive verdict is obliterated when the current run's first round is written. The append-only `ACQUITTAL_LOG.jsonl` is never overwritten — but each entry carries a `run_id`, and only entries whose `run_id` matches the current invocation count. A stale acquittal from a prior run (different `run_id`) is an audit artifact, not a valid stop signal for the current run.

This evaluation runs AFTER Phase B.5 so the terminal-round memory is always appended to REVIEWER_MEMORY.md before exit.

#### Phase B.6: Debate Protocol (hard + nightmare only)

**Skip entirely if `REVIEWER_DIFFICULTY = medium`.**

After parsing the review, the executor gets a chance to **rebut**:

**Step 1 — Executor Rebuttal:**

For each weakness the reviewer identified, the executor writes a structured response:

```markdown
### Rebuttal to Weakness #1: [title]
- **Accept / Partially Accept / Reject**
- **Argument**: [why this criticism is invalid, already addressed, or based on a misunderstanding]
- **Evidence**: [point to specific code, results, or prior round fixes]
```

Rules for the executor's rebuttal:
- Must be honest — do NOT fabricate evidence or misrepresent results
- Can point out factual errors in the review (reviewer misread code, wrong metric, etc.)
- Can argue a weakness is out of scope or would require unreasonable effort
- Maximum 3 rebuttals per round (pick the most impactful to contest)

**Step 2 — Reviewer Rules on Rebuttal:**

Send the executor's rebuttal back to the reviewer for a ruling:

*Hard mode — use the selected backend for the rebuttal step:*

*For copilot:* fresh `copilot --agent` subprocess with the same profile + REVIEWER_MEMORY.md context:
```bash
# Write assembled prompt to a temp file to avoid shell injection
# from untrusted REVIEWER_MEMORY.md content (which may contain quotes,
# backticks, or $() that would be re-interpreted in a double-quoted arg)
PROMPTFILE=$(mktemp) || PROMPTFILE="/tmp/reviewer_prompt_$$.txt"
trap 'rm -f "$PROMPTFILE"' EXIT
cat > "$PROMPTFILE" <<'PROMPT_EOF'
[Rebutal ruling — same reviewer]

## Your Memory From Previous Rounds
[Paste full contents of REVIEWER_MEMORY.md]

The author rebuts your review:

[paste executor's rebuttal]

For each rebuttal, rule:
- SUSTAINED (author's argument is valid, withdraw this weakness)
- OVERRULED (your original criticism stands, explain why)
- PARTIALLY SUSTAINED (revise the weakness to a narrower scope)

Then update your score if any weaknesses were withdrawn.
Include a Memory Update section at the end of your response.
PROMPT_EOF
copilot --agent "<saved-reviewer-profile>" --prompt "$(cat "$PROMPTFILE")"
```

*For codex:*
```
mcp__codex__codex-reply:
  threadId: [saved]
  # inherits the thread's model/effort — do not re-send
  prompt: |
    The author rebuts your review:
```

*For manual:* use `mcp__manual_review__review_reply` with the same `threadId` and prompt.

The prompt content:

```
    The author rebuts your review:

    [paste executor's rebuttal]

    For each rebuttal, rule:
    - SUSTAINED (author's argument is valid, withdraw this weakness)
    - OVERRULED (your original criticism stands, explain why)
    - PARTIALLY SUSTAINED (revise the weakness to a narrower scope)

    Then update your score if any weaknesses were withdrawn.
```

*Nightmare mode (codex exec):*
```bash
codex exec "$(cat <<'PROMPT'
You are the same adversarial reviewer. The author rebuts your review:

[paste executor's rebuttal]

VERIFY the author's evidence claims yourself — read the files they reference.
Do NOT take their word for it.

For each rebuttal, rule:
- SUSTAINED (verified and valid)
- OVERRULED (evidence doesn't check out or argument is weak)
- PARTIALLY SUSTAINED (partially valid, narrow the weakness)

Update your score. Update your memory.
PROMPT
)" --skip-git-repo-check 2>&1
```

**Step 3 — Update score and action items** based on the ruling:
- SUSTAINED weaknesses: remove from action items
- OVERRULED: keep as-is
- PARTIALLY SUSTAINED: revise scope

Append the full debate transcript to `review-stage/AUTO_REVIEW.md` under the round's entry.

#### Human Checkpoint (if enabled)

**Skip this step entirely if `HUMAN_CHECKPOINT = false`.**

When `HUMAN_CHECKPOINT = true`, present the review results and wait for user input:

```
📋 Round N/MAX_ROUNDS review complete.

Score: X/10 — [verdict]
Top weaknesses:
1. [weakness 1]
2. [weakness 2]
3. [weakness 3]

Suggested fixes:
1. [fix 1]
2. [fix 2]
3. [fix 3]

Options:
- Reply "go" or "continue" → implement all suggested fixes
- Reply with custom instructions → implement your modifications instead
- Reply "skip 2" → skip fix #2, implement the rest
- Reply "stop" → end the loop, document current state
```

Wait for the user's response. Parse their input:
- **Approval** ("go", "continue", "ok", "proceed"): proceed to Phase C with all suggested fixes
- **Custom instructions** (any other text): treat as additional/replacement guidance for Phase C. Merge with reviewer suggestions where appropriate
- **Skip specific fixes** ("skip 1,3"): remove those fixes from the action list
- **Stop** ("stop", "enough", "done"): terminate the loop, jump to Termination

#### Feishu Notification (if configured)

After parsing the score, check if `~/.claude/feishu.json` exists and mode is not `"off"`:
- Send a `review_scored` notification: "Round N: X/10 — [verdict]" with top 3 weaknesses
- If **interactive** mode and verdict is "almost": send as checkpoint, wait for user reply on whether to continue or stop
- If config absent or mode off: skip entirely (no-op)

#### Phase C: Implement Fixes (if not stopping)

For each action item (highest priority first):

1. **Code changes**: Write/modify experiment scripts, model code, analysis scripts
2. **Run experiments**: Deploy to GPU server via SSH + screen/tmux
3. **Analysis**: Run evaluation, collect results, update figures/tables
4. **Documentation**: Update project notes and review document

Prioritization rules:
- Skip fixes requiring excessive compute (flag for manual follow-up)
- Skip fixes requiring external data/models not available
- Prefer reframing/analysis over new experiments when both address the concern
- Always implement metric additions (cheap, high impact)

#### Phase D: Wait for Results

If experiments were launched:
- Monitor remote sessions for completion
- Collect results from output files and logs
- **Training quality check** — if W&B is configured, invoke `/training-check` to verify training was healthy (no NaN, no divergence, no plateau). If W&B not available, skip silently. Flag any quality issues in the next review round.

#### Phase E: Document Round

Append to `review-stage/AUTO_REVIEW.md`:

```markdown
## Round N (timestamp)

### Assessment (Summary)
- Score: X/10
- Verdict: [ready/almost/not ready]
- Key criticisms: [bullet list]

### Reviewer Raw Response

<details>
<summary>Click to expand full reviewer response</summary>

[Paste the COMPLETE raw response from the external reviewer here — verbatim, unedited.
This is the authoritative record. Do NOT truncate or paraphrase.]

</details>

### Debate Transcript (hard + nightmare only)

<details>
<summary>Click to expand debate</summary>

**Executor Rebuttal:**
[paste rebuttal]

**Reviewer Ruling:**
[paste ruling — SUSTAINED / OVERRULED / PARTIALLY SUSTAINED for each]

**Score adjustment**: X/10 → Y/10

</details>

### Actions Taken
- [what was implemented/changed]

### Results
- [experiment outcomes, if any]

### Status
- [continuing to round N+1 / stopping]
- Difficulty: [medium/hard/nightmare]
```

**Write `review-stage/REVIEW_STATE.json`** with current `run_id`, round, threadId, score, verdict, and any pending experiments. The `run_id` field MUST persist unchanged from initialization; do NOT regenerate it per round.

**Backend labeling for the state file:** The `reviewer_backend` field in `REVIEW_STATE.json` controls the continuation mechanism for the NEXT round (used on resume), not the round just documented. During Phase E:
- Use `round_backend` (snapshotted at round start, step 0) to label the CURRENT round in `AUTO_REVIEW.md` documentation (e.g., "Reviewer backend: copilot").
- Write `reviewer_backend` in `REVIEW_STATE.json` to the value that should control the NEXT round — this is either (a) unchanged from the current round's backend if no escalation occurred, or (b) the escalation backend set during Phase B.5.1. Never write `round_backend` itself to the state file; the state file's `reviewer_backend` is always forward-looking.
- When no escalation happened, `round_backend == reviewer_backend` (trivially safe).

**If `round_backend ∈ {codex, manual}` AND score >= 6 AND verdict ∈ {"ready", "almost"}:** append an acquittal line to `review-stage/ACQUITTAL_LOG.jsonl`:
```
{"run_id":"<current-run_id>","round":<N>,"backend":"<codex|manual>","effort":"xhigh","verdict":"<ready|almost>","score":<score>,"trace_id":"<skill>/<YYYY-MM-DD>_run<NN>","timestamp":"<ISO8601>"}
```
Use `>>` (append), never `>`. The `trace_id` MUST be the actual trace directory path relative to `.aris/traces/` (e.g., `auto-review-loop/2026-07-13_run01`), matching the RUN_ID format from `save_trace.sh`: `<YYYY-MM-DD>_run<NN>` with the skill-name subdirectory prefix. Do NOT fabricate a synthetic `trace_...` identifier — use the real directory that `save_trace.sh` created for this round's reviewer call.

**Append to `findings.md`** (when `COMPACT = true`): one-line entry per key finding this round:

```markdown
- [Round N] [positive/negative/unexpected]: [one-sentence finding] (metric: X.XX → Y.YY)
```

Increment round counter → back to Phase A.

### Termination

When loop ends (positive assessment or max rounds):

1. Update `review-stage/REVIEW_STATE.json` with `"status": "completed"`
2. Write final summary to `review-stage/AUTO_REVIEW.md`
3. Update project notes with conclusions
4. **Write method/pipeline description** to `review-stage/AUTO_REVIEW.md` under a `## Method Description` section — a concise 1-2 paragraph description of the final method, its architecture, and data flow. This serves as input for `/paper-illustration` in Workflow 3 (so it can generate architecture diagrams automatically).
5. **Generate claims from results** — invoke `/result-to-claim` to convert experiment results from `review-stage/AUTO_REVIEW.md` into structured paper claims. Output: `CLAIMS_FROM_RESULTS.md`. This bridges Workflow 2 → Workflow 3 so `/paper-plan` can directly use validated claims instead of extracting them from scratch. If `/result-to-claim` is not installed, skip this step (no `CLAIMS_FROM_RESULTS.md` is produced; `/paper-plan` extracts claims from the narrative as before) — but NEVER fabricate the file or its verdict. If it ran but its output starts with `verdict: REVIEW_UNAVAILABLE`, keep that file AS-IS (do not overwrite or paraphrase it) and record in `AUTO_REVIEW.md` that claims are UNADJUDICATED — downstream paper stages must not treat them as validated.
6. If stopped at max rounds without positive assessment:
   - List remaining blockers
   - Estimate effort needed for each
   - Suggest whether to continue manually or pivot
7. **Feishu notification** (if configured): Send `pipeline_done` with final score progression table
8. **Render HTML view** (if `RENDER_HTML = true`, default): invoke `/render-html` on the cumulative review log:
   ```
   /render-html "review-stage/AUTO_REVIEW.md" --no-review --state review-stage/REVIEW_STATE.json
   ```
   Pass `--state` explicitly (the helper does not auto-discover the sidecar). Drop the `--state` flag if `REVIEW_STATE.json` doesn't exist. HTML lands at `review-stage/AUTO_REVIEW.html` with embedded source SHA256. **Non-blocking**: if `/render-html` fails, log the error and continue — the HTML is a convenience, not a termination prerequisite. Skip if `RENDER_HTML = false`.

## Key Rules

- **Large file handling**: If the Write tool fails due to file size, immediately retry using Bash (`cat << 'EOF' > file`) to write in chunks. Do NOT ask the user for permission — just do it silently.

- ALWAYS use `config: {"model_reasoning_effort": "xhigh"}` for maximum reasoning depth
- **Copilot backend is drive-only (effort-unpinned).** Copilot profiles cannot set reasoning effort. Copilot verdicts are recorded as `effort_unpinned: true` and can iterate the loop, but final acceptance must come from a `codex` or `manual` backend at `xhigh`+ effort. Do not terminate the loop on a copilot-issued positive verdict without an acquitting cross-review.
- Save `threadId` (codex/manual) or `reviewer_profile` (copilot) from first call; use the appropriate continuation tool for subsequent rounds per the Reviewer Calling Convention
- **Anti-hallucination citations**: When adding references during fixes, NEVER fabricate BibTeX. Use the same DBLP → CrossRef → `[VERIFY]` chain as `/paper-write`: (1) `curl -s "https://dblp.org/search/publ/api?q=TITLE&format=json"` → get key → `curl -s "https://dblp.org/rec/{key}.bib"`, (2) if not found, `curl -sLH "Accept: application/x-bibtex" "https://doi.org/{doi}"`, (3) if both fail, mark with `% [VERIFY]`. Do NOT generate BibTeX from memory.
- Be honest — include negative results and failed experiments
- Do NOT hide weaknesses to game a positive score
- Implement fixes BEFORE re-reviewing (don't just promise to fix)
- **Exhaust before surrendering** — before marking any reviewer concern as "cannot address": (1) try at least 2 different solution paths, (2) for experiment issues, adjust hyperparameters or try an alternative baseline, (3) for theory issues, provide a weaker version of the result or an alternative argument, (4) only then concede narrowly and bound the damage. Never give up on the first attempt.
- If an experiment takes > 30 minutes, launch it and continue with other fixes while waiting
- Document EVERYTHING — the review log should be self-contained
- Update project notes after each round, not just at the end

## Prompt Template for Round 2+

Use the selected backend. *For copilot:* fresh `copilot --agent` subprocess with the same profile + `REVIEWER_MEMORY.md` artifact. *For codex:* `mcp__codex__codex-reply` with the saved threadId. *For manual:* `mcp__manual_review__review_reply` with the saved threadId.

```
[For copilot:]

# Write assembled prompt to a temp file to avoid shell injection
# from untrusted REVIEWER_MEMORY.md content (which may contain quotes,
# backticks, or $() that would be re-interpreted in a double-quoted arg)
PROMPTFILE=$(mktemp) || PROMPTFILE="/tmp/reviewer_prompt_$$.txt"
trap 'rm -f "$PROMPTFILE"' EXIT
cat > "$PROMPTFILE" <<'PROMPT_EOF'
[Round N update]

## Your Memory From Previous Rounds
[Paste full contents of REVIEWER_MEMORY.md]

Since your last review these files changed — read them yourself; do not
take my word for what changed or whether it worked:
- Changed files: <paths>
- Raw diff: <path, or the `git diff` range>
- Updated raw results: <result-file paths> (verbatim files, not a pasted table)

Please re-score and re-assess. Are the remaining concerns addressed?
Same format: Score, Verdict, Remaining Weaknesses, Minimum Fixes.

At the end of your review, include a Memory Update section — this will
be passed back to you next round.
PROMPT_EOF
copilot --agent "<saved-reviewer-profile>" --prompt "$(cat "$PROMPTFILE")"

[For codex:] mcp__codex__codex-reply:
  threadId: [saved from round 1]
  # inherits the thread's model/effort — do not re-send
  prompt: |
    [Round N update]

    Since your last review these files changed — read them yourself; do not
    take my word for what changed or whether it worked:
    - Changed files: <paths>
    - Raw diff: <path, or the `git diff` range>
    - Updated raw results: <result-file paths> (verbatim files, not a pasted table)

    Please re-score and re-assess. Are the remaining concerns addressed?
    Same format: Score, Verdict, Remaining Weaknesses, Minimum Fixes.
```

## Review Tracing

After each reviewer call (`mcp__codex__codex`, `mcp__codex__codex-reply`, `mcp__manual_review__review`, `mcp__manual_review__review_reply`, `copilot --agent` subprocess for copilot backend), save the trace following `shared-references/review-tracing.md` (Policy C — forensic; never silently skip). Use `save_trace.sh` (resolved per the chain in `shared-references/integration-contract.md` §2) or write files directly to `.aris/traces/<skill>/<date>_run<NN>/`. Respect the `--- trace:` parameter (default: `full`).

## Acquittal Gate Test Specifications

The following test cases validate the `run_id` + append-only acquittal receipt mechanism. These must be verified before merging changes to the stop-evaluation gate.

### Test 1: Fresh Start — No Acquittal, Copilot Positive → Escalation

**Setup:** Delete `review-stage/REVIEW_STATE.json` and `review-stage/ACQUITTAL_LOG.jsonl`. Run with `--reviewer: copilot --executor-model claude-sonnet-4-5`. No same-run acquittal in `ACQUITTAL_LOG.jsonl`.

**Action:** Copilot round 1 returns score=7, verdict="ready".

**Expected:** Loop does NOT stop immediately on the copilot verdict alone. Acquittal check scans `ACQUITTAL_LOG.jsonl` for run_id match — file is empty. The escalation path triggers: `reviewer_backend` switches to `codex` for round 2, which performs a mandatory cross-family acquittal review. If codex returns positive, Phase E writes the acquittal line and the loop stops normally. Without escalation, a pure copilot run would iterate until MAX_ROUNDS without ever being able to terminate on a positive verdict.

### Test 2: Codex Acquits → Copilot Stops (Same Run, Mixed Backend)

**Setup:** Fresh start. Round 1: `REVIEWER_BACKEND=codex`, returns score=7, verdict="ready". Phase E writes acquittal line to `ACQUITTAL_LOG.jsonl` with current `run_id`, `effort: "xhigh"`, valid `trace_id` referencing an existing trace directory under `.aris/traces/auto-review-loop/`. Loop stops with `status: "completed"`. Simulate user re-entering: resume state, switch reviewer to copilot for round 2.

**Action B:** Copilot round 2 returns score=8, verdict="ready". Stop gate scans `ACQUITTAL_LOG.jsonl` → finds line with matching `run_id`, `backend=codex`, `effort="xhigh"`, `verdict="ready"`, `score=7`, non-empty `trace_id` with existing trace directory. All gate predicates validated: match. Stop.

**Expected:** Copilot-issued verdict terminates because a same-run codex acquittal with validated effort and trace exists in the append-only log.

### Test 3: Stale Completed State — Old Run's Acquittal Does NOT Satisfy New Run

**Setup:** Run 1 (run_id=`run_20260713_aaaaaaaa`) completes with `status: "completed"` and writes acquittal: `{"run_id":"run_20260713_aaaaaaaa","backend":"codex","verdict":"ready","score":7}` to `ACQUITTAL_LOG.jsonl`. Then a fresh-start invocation generates run_id=`run_20260713_bbbbbbbb` and begins with `REVIEWER_BACKEND=copilot`.

**Action:** Copilot round 1 returns score=7, verdict="ready". Stop gate scans `ACQUITTAL_LOG.jsonl`.

**Expected:** Loop does NOT stop. The acquittal line has `run_id=run_20260713_aaaaaaaa` which does NOT match the current `run_id=run_20260713_bbbbbbbb`. Only a current-run acquittal counts.

### Test 4: Legacy State File — No run_id Field

**Setup:** Create a `REVIEW_STATE.json` with `status: "in_progress"`, a fresh timestamp, but NO `run_id` field (simulating pre-fix state). Resume.

**Expected:** Initialization detects missing `run_id` and generates one. Log message: "No run_id in legacy state file; assigned run_<...> for this resume." Subsequent acquittal checks use the newly generated run_id.

### Test 5: Copilot NEVER Writes Acquittal

**Setup:** Fresh start with `REVIEWER_BACKEND=copilot`. Copilot returns score=8, verdict="ready" in round 1. The escalation path triggers: `REVIEWER_BACKEND` switches to `codex` for round 2. Codex round 2 returns score=7, verdict="ready".

**Action:** After round 1 Phase E: check `ACQUITTAL_LOG.jsonl`. After round 2 Phase E: check `ACQUITTAL_LOG.jsonl`.

**Expected:** After round 1: `ACQUITTAL_LOG.jsonl` is NOT appended to. Only `codex` or `manual` backends write acquittal lines. After round 2: exactly one acquittal line appears (from the codex escalation round), with `backend=codex`, same `run_id`. The copilot round 1 verdict is recorded in `REVIEW_STATE.json` and `AUTO_REVIEW.md` but did NOT create an acquittal receipt.

### Test 6: Append-Only Integrity

**Setup:** Run with codex backend producing three rounds: round 1 (score=5), round 2 (score=7, "ready"), round 3 (score=8, "ready").

**Action:** After the loop, inspect `ACQUITTAL_LOG.jsonl`.

**Expected:** File contains exactly 2 lines (round 2 and round 3 acquittals), each with the same `run_id`. Lines are never overwritten or deleted. File size monotonically increases.

### Test 7: Manual Backend Acquittal Works Same as Codex

**Setup:** Fresh start with `REVIEWER_BACKEND=manual`. Manual review returns score=7, verdict="ready".

**Action:** Phase E appends to `ACQUITTAL_LOG.jsonl`.

**Expected:** Acquittal line with `backend=manual` is written. A subsequent copilot round in the same run would find this acquittal and stop.

### Test 8: Pure Copilot Run — Escalation Completes the Loop

**Setup:** Fresh start with `REVIEWER_BACKEND=copilot --executor-model claude-sonnet-4-5`. Copilot round 1 returns score=7, verdict="ready". No prior acquittal in `ACQUITTAL_LOG.jsonl`. MAX_ROUNDS=4.

**Action A:** Stop gate (Phase B.5.1) determines: copilot positive, no same-run acquittal with valid effort/trace → escalation triggered. `reviewer_backend` in `REVIEW_STATE.json` switches to `codex`. Round 2 begins.

**Action B:** Codex round 2 returns score=8, verdict="ready". Stop gate (codex branch): score >= 6, verdict "ready" → stop. Phase E appends acquittal line to `ACQUITTAL_LOG.jsonl` with `effort="xhigh"`, valid `trace_id`.

**Expected:** Loop stops at round 2. `ACQUITTAL_LOG.jsonl` has exactly 1 acquittal line (`backend=codex`). The escalation path is the only mechanism that lets a pure copilot-driven loop terminate on a positive verdict — without it, copilot would iterate until MAX_ROUNDS with no path to a valid acquittal.
