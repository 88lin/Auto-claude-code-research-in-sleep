# Third-Party Notices

## MetaSkill proof skill suite

The following material is adapted from MetaSkill commit
`f49ce5dd6b0bfb7565c35063e10aa1ac42a480e9`:

- `skills/proof-orchestrator/`
- the matching directory under `skills/skills-codex/`
- the adversarial proof-audit rubric, DeepSeek reviewer routing, and audit
  output contract internalized in those directories

Those files remain available under the Mozilla Public License 2.0. A copy is
included at [`LICENSES/MetaSkill-MPL-2.0.txt`](LICENSES/MetaSkill-MPL-2.0.txt).
ARIS-specific integration changes include host-neutral executor wording, use of
the existing `llm-chat` MCP route, Codex same-family assurance labeling,
skill-catalog/install-group registration, and non-conflicting routing alongside
the existing `/proof-checker`.