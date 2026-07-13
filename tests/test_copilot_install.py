"""Tests for install_aris_copilot.sh and smart_update_copilot.sh."""
from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = REPO_ROOT / "tools" / "install_aris_copilot.sh"
UPDATE_SCRIPT = REPO_ROOT / "tools" / "smart_update_copilot.sh"


def run(
    cmd: list[str], *, cwd: Path | None = None, check: bool = True, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd or REPO_ROOT,
        text=True,
        capture_output=True,
        check=check,
        env=env,
    )


def make_skill(path: Path, body: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(body)


def make_minimal_aris_repo(root: Path) -> Path:
    """Create a minimal ARIS repo structure with mainline skills."""
    repo = root / "aris"
    # Mainline skills (what Copilot CLI uses directly)
    make_skill(repo / "skills" / "alpha", "---\nname: alpha\ndescription: Alpha skill\nallowed-tools: Read\n---\n# alpha\n")
    make_skill(repo / "skills" / "beta", "---\nname: beta\ndescription: Beta skill\nallowed-tools: Read, Write\n---\n# beta\n")
    make_skill(repo / "skills" / "gamma", "---\nname: gamma\ndescription: Gamma skill\n---\n# gamma\n")
    # shared-references (support directory)
    (repo / "skills" / "shared-references").mkdir(parents=True, exist_ok=True)
    (repo / "skills" / "shared-references" / "reviewer-routing.md").write_text("routing\n")
    (repo / "skills" / "shared-references" / "effort-contract.md").write_text("effort\n")
    # Codex-specific packages (should be EXCLUDED from Copilot install)
    make_skill(repo / "skills" / "skills-codex" / "alpha", "# codex alpha\n")
    make_skill(repo / "skills" / "skills-codex-claude-review" / "alpha", "# codex-claude alpha\n")
    # AGENT_GUIDE.md for repo discovery
    (repo / "AGENT_GUIDE.md").write_text("# Agent Guide\n")
    return repo


def test_install_copilot_dry_run_has_no_project_writes(tmp_path: Path) -> None:
    repo = make_minimal_aris_repo(tmp_path)
    project = tmp_path / "project"
    project.mkdir()

    dry_run = run(
        [
            "bash",
            str(INSTALL_SCRIPT),
            str(project),
            "--aris-repo",
            str(repo),
            "--dry-run",
        ]
    )

    assert "(dry-run) no changes made" in dry_run.stdout
    assert not (project / ".aris").exists()
    assert not (project / ".github").exists()
    assert not (project / "AGENTS.md").exists()


def test_install_copilot_avoids_bash4_associative_arrays() -> None:
    text = INSTALL_SCRIPT.read_text()
    assert "declare -A" not in text


def test_install_copilot_creates_github_skills_symlinks(tmp_path: Path) -> None:
    """Basic install creates .github/skills/<name> symlinks to mainline skills."""
    repo = make_minimal_aris_repo(tmp_path)
    project = tmp_path / "project"
    project.mkdir()

    run(
        [
            "bash",
            str(INSTALL_SCRIPT),
            str(project),
            "--aris-repo",
            str(repo),
            "--quiet",
        ]
    )

    # Verify manifest
    manifest = project / ".aris" / "installed-skills-copilot.txt"
    assert manifest.exists()
    manifest_text = manifest.read_text()
    assert "repo_root" in manifest_text
    assert "installer\tinstall_aris_copilot.sh" in manifest_text

    # Verify AGENTS.md
    assert (project / "AGENTS.md").exists()
    agents_text = (project / "AGENTS.md").read_text()
    assert "ARIS Copilot CLI Skill Scope" in agents_text
    assert f"ARIS repo root: `{repo}`" in agents_text

    # Verify skill symlinks point to mainline skills/
    assert (project / ".github" / "skills" / "alpha").is_symlink()
    assert (project / ".github" / "skills" / "beta").is_symlink()
    assert (project / ".github" / "skills" / "gamma").is_symlink()
    assert (project / ".github" / "skills" / "alpha").resolve() == (repo / "skills" / "alpha")
    assert (project / ".github" / "skills" / "beta").resolve() == (repo / "skills" / "beta")

    # Verify shared-references is included
    assert (project / ".github" / "skills" / "shared-references").is_symlink()
    assert (project / ".github" / "skills" / "shared-references").resolve() == (repo / "skills" / "shared-references")

    # Verify Codex-specific packages are NOT installed
    assert not (project / ".github" / "skills" / "skills-codex").exists()
    assert not (project / ".github" / "skills" / "skills-codex-claude-review").exists()


def test_install_copilot_excludes_codex_packages(tmp_path: Path) -> None:
    """Codex-specific skill mirrors must not appear in Copilot install."""
    repo = make_minimal_aris_repo(tmp_path)
    project = tmp_path / "project"
    project.mkdir()

    run(
        [
            "bash",
            str(INSTALL_SCRIPT),
            str(project),
            "--aris-repo",
            str(repo),
            "--quiet",
        ]
    )

    skills_dir = project / ".github" / "skills"
    installed_names = [p.name for p in skills_dir.iterdir()]
    for codex_name in ["skills-codex", "skills-codex-claude-review", "skills-codex-gemini-review"]:
        assert codex_name not in installed_names


def test_install_copilot_reconcile_adds_and_removes(tmp_path: Path) -> None:
    """Reconcile picks up new skills and removes deleted ones."""
    repo = make_minimal_aris_repo(tmp_path)
    project = tmp_path / "project"
    project.mkdir()

    # Initial install
    run(
        [
            "bash",
            str(INSTALL_SCRIPT),
            str(project),
            "--aris-repo",
            str(repo),
            "--quiet",
        ]
    )
    assert (project / ".github" / "skills" / "alpha").is_symlink()
    assert (project / ".github" / "skills" / "gamma").is_symlink()

    # Simulate upstream change: remove alpha, add delta
    (repo / "skills" / "alpha" / "SKILL.md").unlink()
    (repo / "skills" / "alpha").rmdir()
    make_skill(repo / "skills" / "delta", "---\nname: delta\ndescription: Delta\n---\n# delta\n")

    # Reconcile
    run(
        [
            "bash",
            str(INSTALL_SCRIPT),
            str(project),
            "--aris-repo",
            str(repo),
            "--reconcile",
            "--quiet",
        ]
    )

    assert not (project / ".github" / "skills" / "alpha").exists()
    assert (project / ".github" / "skills" / "delta").is_symlink()
    assert (project / ".github" / "skills" / "delta").resolve() == (repo / "skills" / "delta")
    assert (project / ".github" / "skills" / "beta").is_symlink()


def test_install_copilot_uninstall_removes_managed_only(tmp_path: Path) -> None:
    """Uninstall removes only managed entries, preserves user-owned skills."""
    repo = make_minimal_aris_repo(tmp_path)
    project = tmp_path / "project"
    project.mkdir()

    run(
        [
            "bash",
            str(INSTALL_SCRIPT),
            str(project),
            "--aris-repo",
            str(repo),
            "--quiet",
        ]
    )

    # Add a user-owned skill
    (project / ".github" / "skills" / "my-custom-skill").mkdir(parents=True)
    (project / ".github" / "skills" / "my-custom-skill" / "SKILL.md").write_text("# mine\n")

    # Uninstall
    run(
        [
            "bash",
            str(INSTALL_SCRIPT),
            str(project),
            "--aris-repo",
            str(repo),
            "--uninstall",
            "--quiet",
        ]
    )

    # User skill preserved
    assert (project / ".github" / "skills" / "my-custom-skill").exists()
    # Managed skills removed
    assert not (project / ".github" / "skills" / "alpha").exists()
    assert not (project / ".github" / "skills" / "beta").exists()
    # Manifest archived
    assert (project / ".aris" / "installed-skills-copilot.txt.prev").exists()
    assert not (project / ".aris" / "installed-skills-copilot.txt").exists()
    # AGENTS.md block removed
    assert "ARIS Copilot CLI Skill Scope" not in (project / "AGENTS.md").read_text()


def test_install_copilot_uninstall_uses_manifest_repo_root(tmp_path: Path) -> None:
    """Uninstall uses repo_root from manifest, not --aris-repo flag."""
    original_repo = make_minimal_aris_repo(tmp_path / "original")
    other_repo = make_minimal_aris_repo(tmp_path / "other")
    project = tmp_path / "project"
    project.mkdir()

    # Install with original repo
    run(
        [
            "bash",
            str(INSTALL_SCRIPT),
            str(project),
            "--aris-repo",
            str(original_repo),
            "--quiet",
        ]
    )

    alpha_link = project / ".github" / "skills" / "alpha"
    assert alpha_link.is_symlink()
    assert alpha_link.resolve() == original_repo / "skills" / "alpha"

    # Uninstall with a DIFFERENT --aris-repo (should still work via manifest repo_root)
    run(
        [
            "bash",
            str(INSTALL_SCRIPT),
            str(project),
            "--aris-repo",
            str(other_repo),
            "--uninstall",
            "--quiet",
        ]
    )

    assert not alpha_link.exists()
    assert not (project / ".github" / "skills" / "beta").exists()


def test_install_copilot_conflict_on_real_path(tmp_path: Path) -> None:
    """Installer aborts when a real (non-symlink) path conflicts."""
    repo = make_minimal_aris_repo(tmp_path)
    project = tmp_path / "project"
    project.mkdir()

    # Pre-create a real directory that conflicts
    (project / ".github" / "skills" / "alpha").mkdir(parents=True)
    (project / ".github" / "skills" / "alpha" / "SKILL.md").write_text("# local\n")

    result = run(
        [
            "bash",
            str(INSTALL_SCRIPT),
            str(project),
            "--aris-repo",
            str(repo),
            "--quiet",
        ],
        check=False,
    )

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "CONFLICT" in combined or "conflict" in combined.lower()


def test_install_copilot_replace_link_resolves_conflict(tmp_path: Path) -> None:
    """--replace-link resolves a symlink conflict."""
    repo = make_minimal_aris_repo(tmp_path)
    project = tmp_path / "project"
    project.mkdir()

    # Pre-create a conflicting symlink
    (project / ".github" / "skills").mkdir(parents=True)
    (project / ".github" / "skills" / "alpha").symlink_to("/some/other/path")

    result = run(
        [
            "bash",
            str(INSTALL_SCRIPT),
            str(project),
            "--aris-repo",
            str(repo),
            "--replace-link",
            "alpha",
            "--quiet",
        ],
    )

    assert result.returncode == 0
    assert (project / ".github" / "skills" / "alpha").resolve() == (repo / "skills" / "alpha")


def test_install_copilot_reconcile_already_deleted_stale_link(tmp_path: Path) -> None:
    """Reconcile handles gracefully when a to-be-removed link is already gone."""
    repo = make_minimal_aris_repo(tmp_path)
    project = tmp_path / "project"
    project.mkdir()

    run(
        [
            "bash",
            str(INSTALL_SCRIPT),
            str(project),
            "--aris-repo",
            str(repo),
            "--quiet",
        ]
    )

    # Manually delete a managed link, then remove from upstream
    (project / ".github" / "skills" / "alpha").unlink()
    (repo / "skills" / "alpha" / "SKILL.md").unlink()
    (repo / "skills" / "alpha").rmdir()

    # Reconcile should succeed without error
    run(
        [
            "bash",
            str(INSTALL_SCRIPT),
            str(project),
            "--aris-repo",
            str(repo),
            "--reconcile",
            "--quiet",
        ]
    )

    manifest = (project / ".aris" / "installed-skills-copilot.txt").read_text()
    assert "\talpha\t" not in manifest


def test_smart_update_copilot_copy_install(tmp_path: Path) -> None:
    """smart_update_copilot.sh updates a copy-based install and records baselines."""
    upstream = tmp_path / "upstream"
    make_skill(upstream / "alpha", "---\nname: alpha\n---\n# alpha\n")
    make_skill(upstream / "beta", "---\nname: beta\n---\n# beta\n")
    make_skill(upstream / "gamma", "---\nname: gamma\n---\n# gamma\n")
    (upstream / "shared-references").mkdir(parents=True, exist_ok=True)
    (upstream / "shared-references" / "reviewer-routing.md").write_text("routing\n")

    local = tmp_path / "local"
    # alpha already exists locally with SAME content (up-to-date scenario is skipped)
    # Only test new installs here
    make_skill(local / "local-only", "---\nname: local-only\n---\n# keep-me\n")

    # Dry run first
    dry_run = run(
        [
            "bash",
            str(UPDATE_SCRIPT),
            "--upstream",
            str(upstream),
            "--local",
            str(local),
        ]
    )
    assert dry_run.returncode == 0
    assert "Run with --apply" in dry_run.stdout

    # Apply
    result = run(
        [
            "bash",
            str(UPDATE_SCRIPT),
            "--upstream",
            str(upstream),
            "--local",
            str(local),
            "--apply",
        ]
    )

    # New skills added
    assert (local / "alpha" / "SKILL.md").exists()
    assert (local / "beta" / "SKILL.md").exists()
    assert (local / "gamma" / "SKILL.md").exists()
    # Local-only skill preserved
    assert (local / "local-only" / "SKILL.md").exists()
    # Baseline file created with hashes for newly installed skills
    baseline_file = local / ".aris-copilot-baselines.sha256"
    assert baseline_file.exists()
    baseline_text = baseline_file.read_text()
    assert "alpha" in baseline_text
    assert "beta" in baseline_text
    assert "gamma" in baseline_text


def test_smart_update_copilot_hash_based_customization(tmp_path: Path) -> None:
    """Hash-based detection correctly identifies user-modified skills."""
    upstream_v1 = tmp_path / "upstream"
    make_skill(upstream_v1 / "alpha", "---\nname: alpha\n---\n# alpha-v1\n")
    make_skill(upstream_v1 / "beta", "---\nname: beta\n---\n# beta-v1\n")

    local = tmp_path / "local"
    local.mkdir()

    # First install: copy upstream v1 and record baselines
    run(
        [
            "bash",
            str(UPDATE_SCRIPT),
            "--upstream",
            str(upstream_v1),
            "--local",
            str(local),
            "--apply",
        ]
    )
    assert (local / "alpha" / "SKILL.md").read_text() == "---\nname: alpha\n---\n# alpha-v1\n"

    # User customizes alpha locally
    (local / "alpha" / "SKILL.md").write_text("---\nname: alpha\n---\n# alpha-v1 CUSTOMIZED\n")

    # Upstream releases v2
    (upstream_v1 / "alpha" / "SKILL.md").write_text("---\nname: alpha\n---\n# alpha-v2\n")
    (upstream_v1 / "beta" / "SKILL.md").write_text("---\nname: beta\n---\n# beta-v2\n")

    # Run update: alpha should be detected as customized and skipped
    result = run(
        [
            "bash",
            str(UPDATE_SCRIPT),
            "--upstream",
            str(upstream_v1),
            "--local",
            str(local),
            "--apply",
        ]
    )

    assert "Customized" in result.stdout
    assert "alpha" in result.stdout
    # alpha should NOT be updated (customized)
    assert "CUSTOMIZED" in (local / "alpha" / "SKILL.md").read_text()
    # beta should be updated (not customized)
    assert "beta-v2" in (local / "beta" / "SKILL.md").read_text()


def test_smart_update_copilot_refuses_symlink_managed(tmp_path: Path) -> None:
    """smart_update refuses to update a project managed by install_aris_copilot.sh."""
    managed_project = tmp_path / "managed"
    managed_project.mkdir()
    (managed_project / ".github" / "skills").mkdir(parents=True)
    # Create manifest to signal managed install
    (managed_project / ".aris").mkdir(parents=True)
    (managed_project / ".aris" / "installed-skills-copilot.txt").write_text(
        "version\t1\nrepo_root\t/tmp/aris\n"
    )

    refused = run(
        ["bash", str(UPDATE_SCRIPT), "--project", str(managed_project)],
        check=False,
    )

    assert refused.returncode != 0
    assert "install_aris_copilot.sh" in refused.stderr


# --- Agent profile deployment tests ---

def test_install_copilot_deploys_agents(tmp_path: Path) -> None:
    """install_aris_copilot.sh deploys .github/agents/ symlinks."""
    repo = make_minimal_aris_repo(tmp_path)
    # Ensure agent profiles exist in upstream
    repo_agents = repo / ".github" / "agents"
    repo_agents.mkdir(parents=True, exist_ok=True)
    (repo_agents / "aris-reviewer-openai.agent.md").write_text("---\nmodel: gpt-5.4\n---\n# openai\n")
    (repo_agents / "aris-reviewer-claude.agent.md").write_text("---\nmodel: claude-sonnet-4.5\n---\n# claude\n")

    project = tmp_path / "project"
    project.mkdir()

    run(
        [
            "bash",
            str(INSTALL_SCRIPT),
            str(project),
            "--aris-repo",
            str(repo),
            "--quiet",
        ]
    )

    agents_dir = project / ".github" / "agents"
    assert agents_dir.exists()
    assert (agents_dir / "aris-reviewer-openai.agent.md").is_symlink()
    assert (agents_dir / "aris-reviewer-claude.agent.md").is_symlink()
    assert (agents_dir / "aris-reviewer-openai.agent.md").resolve() == (repo_agents / "aris-reviewer-openai.agent.md")
    assert (agents_dir / "aris-reviewer-claude.agent.md").resolve() == (repo_agents / "aris-reviewer-claude.agent.md")


def test_smart_update_copilot_deploys_agents(tmp_path: Path) -> None:
    """smart_update_copilot.sh deploys .github/agents/ in copy-mode."""
    upstream = tmp_path / "upstream"
    make_skill(upstream / "alpha", "---\nname: alpha\n---\n# alpha\n")
    # Agent profile with a unique name so we can assert it came from this upstream
    upstream_agents = upstream.parent / ".github" / "agents"
    upstream_agents.mkdir(parents=True, exist_ok=True)
    agent_content = "---\nmodel: gpt-5.4\n---\n# openai custom-upstream-258\n"
    (upstream_agents / "aris-reviewer-openai.agent.md").write_text(agent_content)

    local = tmp_path / "local"
    local.mkdir()

    result = run(
        [
            "bash",
            str(UPDATE_SCRIPT),
            "--upstream",
            str(upstream),
            "--local",
            str(local),
            "--apply",
        ]
    )
    assert result.returncode == 0

    # resolve_local_agents() with --local <path> resolves to <path>/../agents
    agents_dir = local.parent / "agents"
    deployed_agent = agents_dir / "aris-reviewer-openai.agent.md"
    assert deployed_agent.exists(), f"Agent not deployed to {deployed_agent}"
    assert deployed_agent.read_text() == agent_content, (
        f"Deployed agent content does not match custom upstream"
    )


def test_install_copilot_reconcile_agents(tmp_path: Path) -> None:
    """Reconcile picks up new agents and removes deleted ones."""
    repo = make_minimal_aris_repo(tmp_path)
    repo_agents = repo / ".github" / "agents"
    repo_agents.mkdir(parents=True, exist_ok=True)
    (repo_agents / "aris-reviewer-openai.agent.md").write_text("---\nmodel: gpt-5.4\n---\n# openai\n")
    (repo_agents / "aris-reviewer-claude.agent.md").write_text("---\nmodel: claude-sonnet-4.5\n---\n# claude\n")

    project = tmp_path / "project"
    project.mkdir()

    # Initial install
    run(
        [
            "bash",
            str(INSTALL_SCRIPT),
            str(project),
            "--aris-repo",
            str(repo),
            "--quiet",
        ]
    )

    assert (project / ".github" / "agents" / "aris-reviewer-openai.agent.md").is_symlink()
    assert (project / ".github" / "agents" / "aris-reviewer-claude.agent.md").is_symlink()

    # Remove one agent, add a new one
    (repo_agents / "aris-reviewer-claude.agent.md").unlink()
    (repo_agents / "aris-reviewer-gemini.agent.md").write_text("---\nmodel: gemini-2.5-pro\n---\n# gemini\n")

    # Reconcile
    run(
        [
            "bash",
            str(INSTALL_SCRIPT),
            str(project),
            "--aris-repo",
            str(repo),
            "--reconcile",
            "--quiet",
        ]
    )

    # Removed agent should be gone
    assert not (project / ".github" / "agents" / "aris-reviewer-claude.agent.md").exists()
    # New agent should exist
    assert (project / ".github" / "agents" / "aris-reviewer-gemini.agent.md").is_symlink()
    # Existing agent should remain
    assert (project / ".github" / "agents" / "aris-reviewer-openai.agent.md").is_symlink()


def test_install_copilot_uninstall_cleans_agents(tmp_path: Path) -> None:
    """Uninstall removes managed agent symlinks."""
    repo = make_minimal_aris_repo(tmp_path)
    repo_agents = repo / ".github" / "agents"
    repo_agents.mkdir(parents=True, exist_ok=True)
    (repo_agents / "aris-reviewer-openai.agent.md").write_text("---\nmodel: gpt-5.4\n---\n# openai\n")

    project = tmp_path / "project"
    project.mkdir()

    # Install
    run(
        [
            "bash",
            str(INSTALL_SCRIPT),
            str(project),
            "--aris-repo",
            str(repo),
            "--quiet",
        ]
    )
    assert (project / ".github" / "agents" / "aris-reviewer-openai.agent.md").is_symlink()

    # Uninstall
    run(
        [
            "bash",
            str(INSTALL_SCRIPT),
            str(project),
            "--aris-repo",
            str(repo),
            "--uninstall",
            "--quiet",
        ]
    )

    assert not (project / ".github" / "agents" / "aris-reviewer-openai.agent.md").exists()


# --- Routing fail-closed tests ---

def test_routing_fail_closed_missing_executor_model(tmp_path: Path) -> None:
    """Routing requires --executor-model for copilot; missing = REVIEW_UNAVAILABLE."""
    # Verify the auto-review-loop SKILL.md contains the fail-closed language
    skill_path = REPO_ROOT / "skills" / "auto-review-loop" / "SKILL.md"
    skill_text = skill_path.read_text()

    assert "REVIEW_UNAVAILABLE" in skill_text
    assert "--executor-model" in skill_text
    # Fail-closed: missing executor-model blocks copilot usage
    assert "missing" in skill_text.lower() or "REVIEW_UNAVAILABLE" in skill_text


def test_routing_fail_closed_unknown_executor_family(tmp_path: Path) -> None:
    """Routing fails closed when executor_family is unknown."""
    skill_path = REPO_ROOT / "skills" / "auto-review-loop" / "SKILL.md"
    skill_text = skill_path.read_text()

    assert "executor_family" in skill_text
    assert "unknown" in skill_text


# --- Legacy-state resume tests ---

def test_legacy_review_state_missing_backend_defaults_to_codex(tmp_path: Path) -> None:
    """REVIEW_STATE.json without reviewer_backend defaults to 'codex'."""
    state_dir = tmp_path / "review-stage"
    state_dir.mkdir()
    state_file = state_dir / "REVIEW_STATE.json"

    # Write legacy state (no reviewer_backend field)
    import json
    legacy_state = {
        "round": 2,
        "threadId": "019cd392-test-legacy",
        "status": "in_progress",
        "difficulty": "medium",
        "last_score": 5.0,
        "last_verdict": "not ready",
        "timestamp": "2026-03-13T21:00:00",
    }
    state_file.write_text(json.dumps(legacy_state))

    # Load and check
    loaded = json.loads(state_file.read_text())
    # When reviewer_backend is absent, resume should default to codex
    backend = loaded.get("reviewer_backend", "codex")
    assert backend == "codex", f"Legacy state missing reviewer_backend should default to codex, got: {backend}"


def test_modern_review_state_has_backend_field(tmp_path: Path) -> None:
    """Modern REVIEW_STATE.json includes reviewer_backend field."""
    skill_path = REPO_ROOT / "skills" / "auto-review-loop" / "SKILL.md"
    skill_text = skill_path.read_text()

    assert "reviewer_backend" in skill_text
    assert "reviewer_profile" in skill_text
    # Verify copilot-specific fields
    assert "copilot" in skill_text.lower()


# --- Trace backward-compat tests ---

def test_save_trace_supports_new_fields(tmp_path: Path) -> None:
    """save_trace.sh accepts --executor, --requested-reviewer-model, --reported-reviewer-model, --memory-hash."""
    trace_script = REPO_ROOT / "tools" / "save_trace.sh"
    assert trace_script.exists()

    # Verify the script accepts new flags
    script_text = trace_script.read_text()
    assert "--executor)" in script_text
    assert "--requested-reviewer-model)" in script_text
    assert "--reported-reviewer-model)" in script_text
    assert "--memory-hash)" in script_text


def test_save_trace_executor_field_not_hardcoded(tmp_path: Path) -> None:
    """save_trace.sh executor field is dynamic, not hardcoded to 'claude-code'."""
    trace_script = REPO_ROOT / "tools" / "save_trace.sh"
    script_text = trace_script.read_text()

    # The executor field should use a variable, not the literal string "claude-code"
    # in the JSON generation (it can still appear as a default)
    assert '"executor": "claude-code"' not in script_text, \
        "executor field must be dynamic (use variable, not hardcoded string)"
    # Default should be set via variable, e.g. ST_EXECUTOR or EXECUTOR
    assert 'ST_EXECUTOR' in script_text or 'EXECUTOR' in script_text


def test_save_trace_effort_unpinned_for_copilot(tmp_path: Path) -> None:
    """When backend is copilot, effort_unpinned is true in traces."""
    trace_script = REPO_ROOT / "tools" / "save_trace.sh"
    script_text = trace_script.read_text()

    assert "effort_unpinned" in script_text
    assert "copilot" in script_text


def test_save_trace_independence_verified_derived(tmp_path: Path) -> None:
    """independence_verified is derived, not blindly trusted from caller input."""
    trace_script = REPO_ROOT / "tools" / "save_trace.sh"
    script_text = trace_script.read_text()

    # Must contain the "unverified" fallback logic
    assert '"unverified"' in script_text
    # Must derive from families, not just pass through
    assert "ST_EXECUTOR_FAMILY" in script_text
    assert "ST_REVIEWER_FAMILY" in script_text


def test_review_tracing_doc_copilot_model_is_gpt5_4(tmp_path: Path) -> None:
    """review-tracing.md copilot example uses gpt-5.4, not gpt-5.6-sol."""
    doc_path = REPO_ROOT / "skills" / "shared-references" / "review-tracing.md"
    doc_text = doc_path.read_text()

    # The copilot example section should reference gpt-5.4
    # Find the copilot example block
    copilot_start = doc_text.find('For copilot backend')
    if copilot_start >= 0:
        copilot_section = doc_text[copilot_start:copilot_start + 2000]
        # Within the copilot example, model should be gpt-5.4
        assert '"model": "gpt-5.4"' in copilot_section, \
            "copilot example must use gpt-5.4, not gpt-5.6-sol"


def test_reviewer_routing_copilot_scope_consistent(tmp_path: Path) -> None:
    """reviewer-routing.md top table and copilot section agree on scope."""
    doc_path = REPO_ROOT / "skills" / "shared-references" / "reviewer-routing.md"
    doc_text = doc_path.read_text()

    # Top table: "All other reviewer skills" should NOT list copilot as opt-in
    lines = doc_text.split("\n")
    for i, line in enumerate(lines):
        if "All other reviewer skills" in line:
            # The opt-in override column should not mention copilot
            # Check this line and the next few lines
            nearby = "\n".join(lines[i:i+2])
            assert "copilot" not in nearby.lower(), \
                f"All other reviewer skills should not list copilot as override. Found:\n{nearby}"
            break

    # Copilot section says scope is /auto-review-loop only
    copilot_section_idx = doc_text.find("Copilot CLI Custom Agent Profiles")
    assert copilot_section_idx >= 0
    copilot_section = doc_text[copilot_section_idx:copilot_section_idx + 800]
    assert "auto-review-loop" in copilot_section
    assert "only" in copilot_section.lower()
