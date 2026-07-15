#!/usr/bin/env python3
"""Deterministic state transitions for /auto-review-loop reviewer backends.

The skill remains the orchestrator.  This helper owns only the stop/continue/
escalate decision so that the safety-critical transition table is executable
and testable instead of existing solely as prose in SKILL.md.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import asdict, dataclass


KNOWN_FAMILIES = {"openai", "anthropic", "google"}
POSITIVE_VERDICTS = {"ready", "almost"}
VALID_BACKENDS = {"codex", "manual", "copilot", "oracle-pro", "agy"}
VALID_VERDICTS = POSITIVE_VERDICTS | {"not ready"}


@dataclass(frozen=True)
class Transition:
    decision: str
    next_backend: str | None
    requires_external_acquittal: bool
    identity_assurance: str
    reason: str


def _normalized(value: str) -> str:
    return value.strip().lower()


def derive_model_family(model: str) -> str:
    name = _normalized(model)
    families: set[str] = set()
    if re.search(r"(^|[^a-z0-9])(gpt|chatgpt|codex|oracle|o1|o3|o4)([^a-z0-9]|$)", name):
        families.add("openai")
    if re.search(r"(^|[^a-z0-9])(claude|sonnet|opus|haiku|anthropic)([^a-z0-9]|$)", name):
        families.add("anthropic")
    if re.search(r"(^|[^a-z0-9])(gemini|google)([^a-z0-9]|$)", name):
        families.add("google")
    return next(iter(families)) if len(families) == 1 else "unknown"


def evaluate_transition(
    *,
    round_backend: str,
    score: float,
    verdict: str,
    requires_external_acquittal: bool = False,
    executor_model: str = "",
    reviewer_model: str = "",
    codex_available: bool = False,
    manual_available: bool = False,
    manual_identity_reported: bool = False,
) -> Transition:
    """Return the authoritative transition for one completed review round.

    ``executor_model`` is caller-declared in the
    current Copilot integration.  It is useful for fail-closed route selection,
    but the resulting family relation is not independent identity attestation.
    Family strings are never accepted as inputs; this helper derives them from
    the model identities itself.
    """

    backend = _normalized(round_backend)
    normalized_verdict = _normalized(verdict)
    executor = derive_model_family(executor_model)
    reviewer = derive_model_family(reviewer_model)

    if backend not in VALID_BACKENDS:
        return Transition(
            "review_unavailable",
            None,
            requires_external_acquittal,
            "unverified",
            f"unknown reviewer backend: {round_backend}",
        )
    if normalized_verdict not in VALID_VERDICTS:
        return Transition(
            "review_unavailable",
            None,
            requires_external_acquittal,
            "unverified",
            f"unknown verdict: {verdict}",
        )
    if not math.isfinite(score) or not 1 <= score <= 10:
        return Transition(
            "review_unavailable",
            None,
            requires_external_acquittal,
            "unverified",
            f"score must be finite and within 1..10: {score}",
        )

    positive = score >= 6 and normalized_verdict in POSITIVE_VERDICTS

    if backend == "copilot":
        if requires_external_acquittal:
            return Transition(
                "review_unavailable",
                None,
                True,
                "unverified",
                "invalid state: copilot cannot resume after finalizer escalation",
            )
        if not positive:
            return Transition(
                "continue",
                "copilot",
                False,
                "unverified",
                "copilot drive verdict is not positive",
            )
        if executor not in KNOWN_FAMILIES:
            return Transition(
                "review_unavailable",
                None,
                False,
                "unverified",
                "cannot select an opposite-family finalizer from an unknown executor family",
            )

        if executor == "openai":
            if not manual_available:
                return Transition(
                    "review_unavailable",
                    None,
                    False,
                    "caller_declared",
                    "OpenAI-family executor requires a non-OpenAI manual finalizer",
                )
            next_backend = "manual"
        elif codex_available:
            next_backend = "codex"
        elif manual_available:
            next_backend = "manual"
        else:
            return Transition(
                "review_unavailable",
                None,
                False,
                "caller_declared",
                "no policy-approved finalizer is available",
            )

        return Transition(
            "escalate",
            next_backend,
            True,
            "caller_declared",
            "copilot is drive-only; a positive verdict requires an external finalizer",
        )

    if not positive:
        return Transition(
            "continue",
            backend,
            requires_external_acquittal,
            "unverified",
            "positive threshold not met",
        )

    if backend in {"codex", "oracle-pro", "agy"} and not requires_external_acquittal:
        return Transition(
            "stop",
            None,
            False,
            "not_required",
            "non-Copilot backend preserves the pre-Copilot positive-stop contract",
        )

    if backend in {"oracle-pro", "agy"} and requires_external_acquittal:
        return Transition(
            "review_unavailable",
            None,
            True,
            "unverified",
            "Copilot finalizer state permits only codex or manual",
        )

    if backend == "manual" and not manual_identity_reported:
        return Transition(
            "review_unavailable",
            None,
            requires_external_acquittal,
            "unverified",
            "manual final verdict is missing its required reported model identity",
        )

    if backend == "manual":
        if executor not in KNOWN_FAMILIES or reviewer not in KNOWN_FAMILIES:
            return Transition(
                "review_unavailable",
                None,
                requires_external_acquittal,
                "unverified",
                "manual verdict family relation cannot be derived",
            )
        if executor == reviewer:
            return Transition(
                "review_unavailable",
                None,
                requires_external_acquittal,
                "failed",
                "manual reviewer is same-family as the declared executor model",
            )

    if requires_external_acquittal:
        if executor not in KNOWN_FAMILIES or reviewer not in KNOWN_FAMILIES:
            return Transition(
                "review_unavailable",
                None,
                True,
                "unverified",
                "finalizer family relation cannot be derived",
            )
        if executor == reviewer:
            return Transition(
                "review_unavailable",
                None,
                True,
                "failed",
                "finalizer is same-family as the declared executor model",
            )
        return Transition(
            "stop",
            None,
            False,
            "caller_declared",
            "policy-approved finalizer returned a positive verdict; executor identity remains caller-declared",
        )

    return Transition(
        "stop",
        None,
        False,
        "caller_declared",
        "explicit manual backend returned a positive verdict with its required model identity",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round-backend", required=True, choices=sorted(VALID_BACKENDS))
    parser.add_argument("--score", required=True, type=float)
    parser.add_argument("--verdict", required=True, choices=sorted(VALID_VERDICTS))
    parser.add_argument("--requires-external-acquittal", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--executor-model", default="")
    parser.add_argument("--reviewer-model", default="")
    parser.add_argument("--codex-available", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--manual-available", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--manual-identity-reported", action=argparse.BooleanOptionalAction, default=False)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    transition = evaluate_transition(
        round_backend=args.round_backend,
        score=args.score,
        verdict=args.verdict,
        requires_external_acquittal=args.requires_external_acquittal,
        executor_model=args.executor_model,
        reviewer_model=args.reviewer_model,
        codex_available=args.codex_available,
        manual_available=args.manual_available,
        manual_identity_reported=args.manual_identity_reported,
    )
    print(json.dumps(asdict(transition), sort_keys=True))


if __name__ == "__main__":
    main()
